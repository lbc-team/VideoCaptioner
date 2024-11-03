# -*- coding: utf-8 -*-

import datetime
import os
from pathlib import Path
import sys
from PyQt5.QtCore import *
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication, QLabel, QHeaderView, QFileDialog
from PyQt5.QtGui import QPixmap, QFont, QStandardItemModel, QDragEnterEvent, QDropEvent
from qfluentwidgets import ComboBox, SwitchButton, SimpleCardWidget, CaptionLabel, CardWidget, ToolTipFilter, \
    ToolTipPosition, LineEdit, PrimaryPushButton, ProgressBar, PushButton, InfoBar, BodyLabel, PillPushButton, setFont, \
    InfoBadge, ProgressRing, TableWidget, TableItemDelegate, TableView

from app.core.thread.subtitle_optimization_thread import SubtitleOptimizationThread
from ..core.bk_asr.ASRData import ASRData, from_subtitle_file,from_srt, from_vtt, from_youtube_vtt, from_json
from ..core.thread.create_task_thread import CreateTaskThread
from PyQt5.QtWidgets import QTableWidgetItem,QAbstractItemView
from ..core.entities import Task, VideoInfo, OutputSubtitleFormatEnum
from ..common.config import cfg
from ..core.entities import OutputSubtitleFormatEnum, SupportedSubtitleFormats

class SubtitleTableModel(QAbstractTableModel):
    def __init__(self, data):
        super().__init__()
        self._data = data

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return 4

    def data(self, index, role):
        if role == Qt.DisplayRole or role == Qt.EditRole:
            row = index.row()
            col = index.column()
            item = list(self._data.values())[row]
            if col == 0:
                return QTime(0, 0, 0).addMSecs(item['start_time']).toString('hh:mm:ss.zzz')
            elif col == 1:
                return QTime(0, 0, 0).addMSecs(item['end_time']).toString('hh:mm:ss.zzz')
            elif col == 2:
                return item['original_subtitle']
            elif col == 3:
                return item['translated_subtitle']
        return None
    
    def update_data(self, new_data):
        updated_rows = set()

        # 更新内部数据
        for key, value in new_data.items():
            if key in self._data:
                if "\n" in value:
                    original_subtitle, translated_subtitle = value.split("\n", 1)
                    self._data[key]['original_subtitle'] = original_subtitle
                    self._data[key]['translated_subtitle'] = translated_subtitle
                else:
                    self._data[key]['translated_subtitle'] = value
                row = list(self._data.keys()).index(key)
                updated_rows.add(row)
        
        # 如果有更新，发出dataChanged信号
        if updated_rows:
            min_row = min(updated_rows)
            max_row = max(updated_rows)
            top_left = self.index(min_row, 2)
            bottom_right = self.index(max_row, 3)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.EditRole])

    def update_all(self, data):
        print("update all =====")
        self._data= data
        self.layoutChanged.emit()

    def setData(self, index, value, role):
        if role == Qt.EditRole:
            row = index.row()
            col = index.column()
            item = list(self._data.values())[row]
            if col == 0:
                time = QTime.fromString(value, 'hh:mm:ss.zzz')
                item['start_time'] = QTime(0, 0, 0).msecsTo(time)
            elif col == 1:
                time = QTime.fromString(value, 'hh:mm:ss.zzz')
                item['end_time'] = QTime(0, 0, 0).msecsTo(time)
            elif col == 2:
                item['original_subtitle'] = value
            elif col == 3:
                item['translated_subtitle'] = value
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def flags(self, index):
        return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                headers = ["开始时间", "结束时间", "字幕内容", "翻译字幕" if cfg.need_translate.value else "优化字幕"]
                return headers[section]
            elif orientation == Qt.Vertical:
                return str(section + 1)
        return None

class SubtitleOptimizationInterface(QWidget):
    finished = pyqtSignal(Task)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task = None
        self._init_ui()
        self._setup_signals()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        self._setup_top_layout()
        self._setup_subtitle_table()
        self._setup_bottom_layout()

    def _setup_top_layout(self):
        self.top_layout = QHBoxLayout()
        
        # 左侧布局
        self.left_layout = QHBoxLayout()
        self.format_combobox = ComboBox(self)
        self.format_combobox.addItems([format.value for format in OutputSubtitleFormatEnum])
        self.save_button = PushButton("保存", self)
        self.left_layout.addWidget(self.format_combobox)
        self.left_layout.addWidget(self.save_button)
        
        # 右侧布局
        self.right_layout = QHBoxLayout()
        self.file_select_button = PushButton("选择SRT文件", self)
        self.open_folder_button = PushButton("打开文件夹", self)
        self.start_button = PrimaryPushButton("开始", self)
        self.right_layout.addWidget(self.file_select_button)
        self.right_layout.addWidget(self.open_folder_button)
        self.right_layout.addWidget(self.start_button)
        
        # 添加到主布局
        self.top_layout.addLayout(self.left_layout)
        self.top_layout.addStretch(1)
        self.top_layout.addLayout(self.right_layout)
        
        self.main_layout.addLayout(self.top_layout)

    def _setup_subtitle_table(self):
        self.subtitle_table = TableView(self)
        self.model = SubtitleTableModel("")
        self.subtitle_table.setModel(self.model)
        self.subtitle_table.setBorderVisible(True)
        self.subtitle_table.setBorderRadius(8)
        self.subtitle_table.setWordWrap(True)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.subtitle_table.setColumnWidth(0, 120)
        self.subtitle_table.setColumnWidth(1, 120)
        self.subtitle_table.verticalHeader().setDefaultSectionSize(50)
        self.subtitle_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.main_layout.addWidget(self.subtitle_table)

    def _setup_bottom_layout(self):
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel("就绪", self)
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.bottom_layout.addWidget(self.progress_bar, 1)
        self.bottom_layout.addWidget(self.status_label)
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self):
        self.start_button.clicked.connect(self.process)
        self.file_select_button.clicked.connect(self.on_file_select)
        self.save_button.clicked.connect(self.on_save_clicked)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)

    def create_task(self, file_path):
        """创建任务"""
        self.task = CreateTaskThread.create_subtitle_optimization_task(file_path)

    def set_task(self, task: Task):
        """设置任务并更新UI"""
        self.task = task
        self.update_info(task)

    def update_info(self, task: Task):
        """更新页面信息"""
        original_subtitle_save_path = Path(self.task.original_subtitle_save_path)
        if original_subtitle_save_path.suffix == '.srt':
            asr_data = from_srt(Path(self.task.original_subtitle_save_path).read_text(encoding="utf-8"))
        elif original_subtitle_save_path.suffix == '.vtt':
            try:
                asr_data = from_youtube_vtt(Path(self.task.original_subtitle_save_path).read_text(encoding="utf-8"))
            except Exception as e:
                asr_data = from_vtt(Path(self.task.original_subtitle_save_path).read_text(encoding="utf-8"))
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(f"已加载文件")

    def process(self):
        """主处理函数"""
        self.start_button.setEnabled(False)
        self.file_select_button.setEnabled(False)
        self._update_task_config()
        
        self.subtitle_optimization_thread = SubtitleOptimizationThread(self.task)
        self.subtitle_optimization_thread.finished.connect(self.on_subtitle_optimization_finished)
        self.subtitle_optimization_thread.progress.connect(self.on_subtitle_optimization_progress)
        self.subtitle_optimization_thread.update.connect(self.update_data)
        self.subtitle_optimization_thread.update_all.connect(self.update_all)
        self.subtitle_optimization_thread.error.connect(self.on_subtitle_optimization_error)
        self.subtitle_optimization_thread.start()
        InfoBar.info(self.tr("开始优化"), self.tr("开始优化字幕"), duration=3000, parent=self)

    def _update_task_config(self):
        self.task.need_optimize = cfg.need_optimize.value
        self.task.need_translate = cfg.need_translate.value
        self.task.api_key = cfg.api_key.value
        self.task.base_url = cfg.api_base.value
        self.task.llm_model = cfg.model.value
        self.task.batch_size = cfg.batch_size.value
        self.task.thread_num = cfg.thread_num.value
        self.task.target_language = cfg.target_language.value.value

    def on_subtitle_optimization_finished(self, task: Task):
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        if self.task.status == Task.Status.PENDING:
            self.finished.emit(task)
        InfoBar.success(self.tr("优化完成"), self.tr("优化完成字幕"), duration=3000, parent=self)
    
    def on_subtitle_optimization_error(self, error):
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        InfoBar.error(self.tr("优化失败"), self.tr(error), duration=20000, parent=self)

    def on_subtitle_optimization_progress(self, value, status):
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def update_data(self, data):
        self.model.update_data(data)

    def update_all(self, data):
        self.model.update_all(data)

    def on_file_select(self):
        # 构建文件过滤器
        subtitle_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedSubtitleFormats)
        filter_str = f"字幕文件 ({subtitle_formats})"
        
        file_path, _ = QFileDialog.getOpenFileName(self, "选择字幕文件", "", filter_str)
        if file_path:
            self.file_select_button.setProperty("selected_file", file_path)
            self.load_subtitle_file(file_path)

    def on_save_clicked(self):
        # 检查是否有任务
        if not self.task:
            InfoBar.warning(
                self.tr("警告"), 
                self.tr("请先加载字幕文件"), 
                duration=2000, 
                parent=self
            )
            return
            
        # 获取保存路径
        default_name = os.path.splitext(os.path.basename(self.task.original_subtitle_save_path))[0]
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存字幕文件",
            default_name,  # 使用原文件名作为默认名
            f"字幕文件 (*.{self.format_combobox.currentText()})"
        )
        if not file_path:
            return
            
        try:
            # 转换并保存字幕
            asr_data = from_json(self.model._data)
            asr_data.save(file_path)
            InfoBar.success(
                self.tr("保存成功"), 
                self.tr(f"字幕已保存至: {file_path}"), 
                duration=2000, 
                parent=self
            )
        except Exception as e:
            InfoBar.error(
                self.tr("保存失败"), 
                self.tr(f"保存字幕文件失败: {str(e)}"), 
                duration=3000, 
                parent=self
            )

    def on_open_folder_clicked(self):
        if not self.task:
            InfoBar.warning(self.tr("警告"), self.tr("请先加载字幕文件"), duration=2000, parent=self)
            return
        os.startfile(os.path.dirname(self.task.original_subtitle_save_path))

    def load_subtitle_file(self, file_path):
        self.create_task(file_path)
        asr_data = from_subtitle_file(file_path)
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(f"已加载文件")

    def dragEnterEvent(self, event: QDragEnterEvent):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue
                
            file_ext = os.path.splitext(file_path)[1][1:].lower()
            
            # 检查文件格式是否支持
            supported_formats = {fmt.value for fmt in SupportedSubtitleFormats}
            is_supported = file_ext in supported_formats
                        
            if is_supported:
                self.file_select_button.setProperty("selected_file", file_path)
                self.load_subtitle_file(file_path)
                InfoBar.success(
                    self.tr("导入成功"), 
                    self.tr(f"成功导入{os.path.basename(file_path)}"),
                    duration=2000,
                    parent=self
                )
                break
            else:
                InfoBar.error(
                    self.tr(f"格式错误{file_ext}"),
                    self.tr(f"支持的字幕格式: {supported_formats}"),
                    duration=2000,
                    parent=self
                )
        event.accept()

    def closeEvent(self, event):
        self.subtitle_optimization_thread.terminate()
        print("closeEvent")
        super().closeEvent(event)

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = SubtitleOptimizationInterface()
    window.show()
    sys.exit(app.exec_())