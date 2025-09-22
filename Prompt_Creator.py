import sys
import os
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTextEdit, QPushButton, QLabel, QFileDialog,
    QSizePolicy, QDialog, QMessageBox,
    QCheckBox, QDialogButtonBox, QListWidget, QListWidgetItem,
    QSplitter, QAbstractItemView, QRadioButton, QButtonGroup, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSettings
from PyQt5.QtGui import QTextDocument, QTextCursor, QKeySequence, QPainter

# ==================== 新增：Nord 主题 QSS 样式表 ====================
NORD_QSS = """
/* Nord Theme - https://www.nordtheme.com/ */
QWidget {
    background-color: #2E3440; /* nord0 */
    color: #D8DEE9; /* nord4 */
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 14px;
    border: none;
}

/* === Main Window and Dialogs === */
QMainWindow, QDialog, QWidget {
    background-color: #2E3440; /* nord0 */
}

/* === Input Fields === */
QLineEdit, QTextEdit, QListWidget {
    background-color: #3B4252; /* nord1 */
    color: #E5E9F0; /* nord5 */
    border: 1px solid #434C5E; /* nord2 */
    border-radius: 4px;
    padding: 5px;
    selection-background-color: #4C566A; /* nord3 */
    selection-color: #ECEFF4; /* nord6 */
}

QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #5E81AC; /* nord10 */
}

/* === Buttons === */
QPushButton {
    background-color: #434C5E; /* nord2 */
    color: #ECEFF4; /* nord6 */
    border: 1px solid #4C566A; /* nord3 */
    padding: 8px 12px;
    border-radius: 4px;
    min-height: 1em;
}

QPushButton:hover {
    background-color: #4C566A; /* nord3 */
}

QPushButton:pressed {
    background-color: #5E81AC; /* nord10 */
    border-color: #81A1C1; /* nord9 */
}

QPushButton:disabled {
    background-color: #3B4252; /* nord1 */
    color: #4C566A; /* nord3 */
    border-color: #434C5E; /* nord2 */
}

/* Special Buttons */
QPushButton#generateButton {
    background-color: #A3BE8C; /* nord14 - Green */
    color: #2E3440; /* nord0 */
    font-weight: bold;
}
QPushButton#generateButton:hover {
    background-color: #b1d09a;
}
QPushButton#generateButton:pressed {
    background-color: #8da977;
}

QPushButton#deleteButton {
    background-color: transparent;
    color: #BF616A; /* nord11 - Red */
    font-weight: bold;
    font-size: 16px;
    padding: 2px;
}
QPushButton#deleteButton:hover {
    color: #d77c86;
}
QPushButton#deleteButton:pressed {
    color: #ECEFF4; /* nord6 */
}

QPushButton#addButton {
    background-color: #81A1C1; /* nord9 */
    color: #2E3440; /* nord0 */
    font-size: 20px;
    font-weight: bold;
    padding: 2px;
}
QPushButton#addButton:hover {
    background-color: #8fbcbb; /* nord7 */
}

QPushButton#pathButton {
    background-color: #3B4252; /* nord1 */
    border: 1px solid #4C566A; /* nord3 */
}
QPushButton#pathButton:hover {
    background-color: #434C5E; /* nord2 */
}


/* === GroupBox === */
QGroupBox {
    border: 1px solid #434C5E; /* nord2 */
    border-radius: 5px;
    margin-top: 1em; /* space for title */
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    background-color: #434C5E; /* nord2 */
    border-radius: 4px;
    color: #ECEFF4; /* nord6 */
    font-weight: bold;
}

/* === Splitter === */
QSplitter::handle {
    background-color: #2E3440; /* nord0 */
}

QSplitter::handle:horizontal {
    width: 6px;
    image: url(none);
}

QSplitter::handle:vertical {
    height: 6px;
    image: url(none);
}

QSplitter::handle:hover {
    background-color: #5E81AC; /* nord10 */
}

QSplitter::handle:pressed {
    background-color: #81A1C1; /* nord9 */
}


/* === CheckBox and RadioButton === */
QCheckBox, QRadioButton {
    spacing: 8px;
}

QCheckBox::indicator, QRadioButton::indicator {
    border: 1px solid #4C566A; /* nord3 */
    width: 16px;
    height: 16px;
    background-color: #3B4252; /* nord1 */
}

QRadioButton::indicator {
    border-radius: 9px;
}

QCheckBox::indicator {
    border-radius: 3px;
}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #81A1C1; /* nord9 */
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #88C0D0; /* nord8 */
    border-color: #81A1C1; /* nord9 */
}

QRadioButton::indicator:checked {
    background-color: #88C0D0; /* nord8 */
    border: 4px solid #3B4252; /* Creates the inner dot effect */
}
QRadioButton::indicator:checked:hover {
    border-color: #434C5E;
}


/* === ScrollBar === */
QScrollBar:vertical {
    background: #3B4252; /* nord1 */
    width: 12px;
    margin: 0px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #4C566A; /* nord3 */
    min-height: 25px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #5E81AC; /* nord10 */
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #3B4252; /* nord1 */
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background: #4C566A; /* nord3 */
    min-width: 25px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #5E81AC; /* nord10 */
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* === ListWidget in History Dialog === */
QListWidget::item {
    padding: 8px;
    border-radius: 4px; /* For hover effect */
}

QListWidget::item:hover {
    background-color: #434C5E; /* nord2 */
}

QListWidget::item:selected {
    background-color: #5E81AC; /* nord10 */
    color: #ECEFF4; /* nord6 */
}

/* === Other === */
QToolTip {
    background-color: #3B4252; /* nord1 */
    color: #ECEFF4; /* nord6 */
    border: 1px solid #4C566A; /* nord3 */
    padding: 5px;
    border-radius: 4px;
    opacity: 230;
}

/* Dialog Button Box */
QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* Adjust font sizes for hierarchy */
#project_name_input {
    font-size: 20pt;
    font-weight: bold;
    padding: 8px;
}

#prompt_input {
    font-size: 16pt;
    padding: 8px;
}

"""
# ==================== 代码修改结束 ====================

class ElidedLabel(QLabel):
    """
    一个 QLabel 子类，它会在绘制时根据当前宽度自动用左侧省略号展示过长的文字。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._full_text = ""
        # 不自动换行
        self.setWordWrap(False)

    def setText(self, text: str):
        # 保存完整文字，实际显示用省略号
        self._full_text = text
        self.update()  # 触发重绘

    def paintEvent(self, event):
        painter = QPainter(self)
        fm = painter.fontMetrics()
        elided = fm.elidedText(self._full_text, Qt.ElideLeft, self.width())
        # 调用父类画文字
        painter.drawText(self.rect(), self.alignment(), elided)

HISTORY_FILE = "/Users/yanzhang/Coding/python_code/Modules/Prompt_history.json" # 请确保这个路径对您的系统是正确的
DEFAULT_FILE_SELECTION_PATH = "/Users/yanzhang/Coding" # 定义默认文件选择路径
LAST_FILE_SELECTION_PATH = DEFAULT_FILE_SELECTION_PATH

# --- 自定义查找/替换对话框 ---
class SearchReplaceDialog(QDialog):
    def __init__(self, target_text_edit, parent=None):
        super().__init__(parent)
        self.target_text_edit = target_text_edit
        self.setWindowTitle("查找/替换")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("查找:"))
        self.find_input = QLineEdit()
        find_layout.addWidget(self.find_input)
        layout.addLayout(find_layout)
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("替换:"))
        self.replace_input = QLineEdit()
        replace_layout.addWidget(self.replace_input)
        layout.addLayout(replace_layout)
        options_layout = QHBoxLayout()
        self.case_sensitive_cb = QCheckBox("区分大小写")
        options_layout.addWidget(self.case_sensitive_cb)
        self.whole_words_cb = QCheckBox("全字匹配")
        options_layout.addWidget(self.whole_words_cb)
        options_layout.addStretch()
        layout.addLayout(options_layout)
        self.find_next_button = QPushButton("查找下一个")
        self.replace_button = QPushButton("替换")
        self.replace_all_button = QPushButton("全部替换")
        self.close_button = QPushButton("关闭")
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.find_next_button)
        button_layout.addWidget(self.replace_button)
        button_layout.addWidget(self.replace_all_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
        self.find_next_button.clicked.connect(self.find_next)
        self.replace_button.clicked.connect(self.replace_current)
        self.replace_all_button.clicked.connect(self.replace_all)
        self.close_button.clicked.connect(self.close)
        self.find_input.textChanged.connect(self._update_button_states)
        self._update_button_states()

    def _update_button_states(self):
        has_find_text = bool(self.find_input.text())
        self.find_next_button.setEnabled(has_find_text)
        self.replace_button.setEnabled(has_find_text and self.target_text_edit.textCursor().hasSelection())
        self.replace_all_button.setEnabled(has_find_text)

    def set_search_focus(self):
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _get_find_flags(self):
        flags = QTextDocument.FindFlags()
        if self.case_sensitive_cb.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        return flags

    def find_next(self, search_backward=False):
        if not self.target_text_edit: return False
        query = self.find_input.text()
        if not query: return False
        flags = self._get_find_flags()
        if search_backward: flags |= QTextDocument.FindBackward
        found = self.target_text_edit.find(query, flags)
        if not found:
            cursor = self.target_text_edit.textCursor()
            cursor.movePosition(QTextCursor.Start if not search_backward else QTextCursor.End)
            self.target_text_edit.setTextCursor(cursor)
            found = self.target_text_edit.find(query, flags)
        self._update_button_states()
        return found

    def replace_current(self):
        if not self.target_text_edit or not self.target_text_edit.textCursor().hasSelection(): return
        self.target_text_edit.textCursor().insertText(self.replace_input.text())
        self.find_next()
        self._update_button_states()

    def replace_all(self):
        if not self.target_text_edit: return
        query, replace_text = self.find_input.text(), self.replace_input.text()
        if not query: return
        flags = self._get_find_flags()
        count = 0
        cursor = self.target_text_edit.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.target_text_edit.setTextCursor(cursor)
        while self.target_text_edit.find(query, flags):
            self.target_text_edit.textCursor().insertText(replace_text)
            count += 1
        QMessageBox.information(self, "全部替换", f"已替换 {count} 处。" if count > 0 else f"未找到 '{query}'。")
        self._update_button_states()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.close()
        else: super().keyPressEvent(event)

# --- 自定义文本编辑器 ---
class FileContentTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_dialog = None
        self.setAcceptRichText(False)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Find):
            self.show_search_dialog()
            event.accept()
        else:
            super().keyPressEvent(event)

    def show_search_dialog(self):
        if not self.search_dialog:
            self.search_dialog = SearchReplaceDialog(self, self.window())
        current_selection = self.textCursor().selectedText()
        if current_selection:
            self.search_dialog.find_input.setText(current_selection)
        self.search_dialog.show()
        self.search_dialog.activateWindow()
        self.search_dialog.set_search_focus()

    def focusInEvent(self, event):
        if self.search_dialog: self.search_dialog._update_button_states()
        super().focusInEvent(event)

    def cursorPositionChanged(self):
        if self.search_dialog: self.search_dialog._update_button_states()
        super().cursorPositionChanged()

# --- 单个文件块控件 ---
class FileBlockWidget(QWidget):
    delete_requested = pyqtSignal(QWidget)
    files_selected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.original_content_on_load = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        path_layout = QHBoxLayout()
        self.path_button = QPushButton("选择文件")
        self.path_button.setObjectName("pathButton") # 修改：为按钮设置对象名
        self.path_button.clicked.connect(self.select_file)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("输入/粘贴路径后按Enter加载, 或直接编辑下方内容")
        self.path_input.editingFinished.connect(self._on_path_manually_entered)
        
        self.delete_button = QPushButton("X")
        self.delete_button.setObjectName("deleteButton") # 修改：为按钮设置对象名
        self.delete_button.setFixedSize(32, 22)
        self.delete_button.setToolTip("删除此文件块")
        self.delete_button.clicked.connect(self._request_delete_self)
        path_layout.addWidget(self.path_button)
        
        path_layout.addWidget(self.path_input, 1)

        path_layout.addWidget(self.delete_button)
        layout.addLayout(path_layout)
        self.content_edit = FileContentTextEdit()
        self.content_edit.setPlaceholderText("文件内容将在此显示和编辑...")
        self.content_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.content_edit)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def _request_delete_self(self):
        self.delete_requested.emit(self)

    def _on_path_manually_entered(self):
        """
        当用户在路径输入框中完成编辑时（例如按回车），此方法被调用。
        """
        path = self.path_input.text().strip()
        if path.startswith("file://"):
            path = path[7:]
            
        if path and os.path.isfile(path):
            self.populate_with_file(path)
        elif not path:
            self.file_path = None
            self.content_edit.clear()
            self.original_content_on_load = ""

    def select_file(self):
        global LAST_FILE_SELECTION_PATH
        start_path = LAST_FILE_SELECTION_PATH
        if not os.path.exists(start_path):
            start_path = os.path.expanduser("~")
        
        # 支持 Kotlin 源码：加入 *.kt
        formats = "*.swift *.py *.html *.css *.js *.scpt *.txt *.json *.csv *.db *.kt *.xml *.kts"
        f_paths, _ = QFileDialog.getOpenFileNames(self, "选择一个或多个文件", start_path, f"支持的文件 ({formats});;所有文件 (*)")
        
        if f_paths:
            LAST_FILE_SELECTION_PATH = os.path.dirname(f_paths[0])
            
            settings = QSettings("MyCustomTools", "PromptGeneratorApp")
            settings.setValue("last_path", LAST_FILE_SELECTION_PATH)

            self.files_selected.emit(f_paths)

    def populate_with_file(self, f_path):
        """
        用给定的文件路径 f_path 来加载和显示文件信息。
        """
        global LAST_FILE_SELECTION_PATH
        if not f_path: return

        LAST_FILE_SELECTION_PATH = os.path.dirname(f_path)
        self.file_path = f_path
        
        self.path_input.setText(f_path)
        self.path_input.setToolTip(f_path)
        
        _, file_extension = os.path.splitext(f_path)
        
        if file_extension.lower() in (".db", ".scpt"):
            self.content_edit.clear()
            self.content_edit.setPlaceholderText(f"这是一个 {file_extension} 二进制文件，内容未加载。\n您可以在此手动输入或编辑与该数据库文件相关的信息或说明。")
            self.original_content_on_load = ""
        else:
            try:
                with open(f_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.content_edit.setPlainText(content)
                self.original_content_on_load = content
            except Exception as e:
                QMessageBox.warning(self, "读取文件错误", f"无法读取文件 {f_path}:\n{e}")
                self.content_edit.clear()
                self.original_content_on_load = ""

    def get_file_info(self):
        filename = "未知文件"
        current_path_text = self.path_input.text().strip()

        if self.file_path:
            filename = os.path.basename(self.file_path)
        elif current_path_text:
            filename = os.path.basename(current_path_text)

        content = self.content_edit.toPlainText()
        actual_path = self.file_path if self.file_path else current_path_text
        return actual_path, filename, content

    def load_data(self, path_text, content_text):
        self.file_path = path_text
        self.path_input.setText(path_text if path_text else "")
        self.path_input.setToolTip(path_text if path_text else "")
        self.content_edit.setPlainText(content_text)
        self.original_content_on_load = content_text


# --- 输出对话框 ---
class OutputDialog(QDialog):
    def __init__(self, text_content, parent=None):
        super().__init__(parent)
        self.original_title = "生成结果"
        self.setWindowTitle(self.original_title)
        self.setMinimumSize(600, 400)
        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text_content)

        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        self.button_box = QDialogButtonBox()
        self.ok_button = self.button_box.addButton(QDialogButtonBox.Ok)
        self.ok_button.setText("确定")
        self.button_box.accepted.connect(self.accept)

        self.copy_btn = QPushButton("复制到剪贴板")
        self.copy_btn.setShortcut("C")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.button_box.addButton(self.copy_btn, QDialogButtonBox.ActionRole)

        layout.addWidget(self.button_box)

    def copy_to_clipboard(self):
        """复制内容到剪贴板，然后立即关闭对话框。"""
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        self.setWindowTitle("已复制到剪贴板!")
        QTimer.singleShot(2000, self.restore_title)
        self.accept()

    def restore_title(self):
        self.setWindowTitle(self.original_title)

# --- 历史记录选择对话框 ---
class HistoryDialog(QDialog):
    record_selected = pyqtSignal(dict)
    def __init__(self, history_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.setMinimumSize(850, 550)
        self.history_data = list(history_data)
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._populate_list_widget()
        self.list_widget.itemDoubleClicked.connect(self.load_selected_record)
        self.list_widget.currentItemChanged.connect(self.update_preview)
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        splitter.addWidget(self.list_widget)
        preview_group = QWidget()
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(0,0,0,0)
        self.prompt_preview_edit = QTextEdit()
        self.prompt_preview_edit.setReadOnly(True)
        self.prompt_preview_edit.setPlaceholderText("在此预览选定记录的文件列表和Prompt指令...")
        preview_layout.addWidget(self.prompt_preview_edit)
        splitter.addWidget(preview_group)
        splitter.setSizes([300, 550])
        main_layout.addWidget(splitter)
        self.buttons_box = QDialogButtonBox()
        self.load_button = self.buttons_box.addButton("加载选中记录", QDialogButtonBox.AcceptRole)
        self.delete_button = self.buttons_box.addButton("删除选中记录", QDialogButtonBox.DestructiveRole)
        self.cancel_button = self.buttons_box.addButton(QDialogButtonBox.Cancel)
        self.cancel_button.setText("取消")
        self.load_button.clicked.connect(self.load_selected_record)
        self.delete_button.clicked.connect(self.delete_selected_records)
        self.cancel_button.clicked.connect(self.reject)
        main_layout.addWidget(self.buttons_box)
        self._update_button_states()
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            self.update_preview(self.list_widget.currentItem())

    def _populate_list_widget(self):
        self.list_widget.clear()
        for i, record in enumerate(reversed(self.history_data)):
            timestamp_str = record.get("id", f"记录 {len(self.history_data) - i}")
            project_name = record.get("project_name", "未命名项目")
            list_item_text = f"{timestamp_str} - {project_name}"
            item = QListWidgetItem(list_item_text)
            original_index = len(self.history_data) - 1 - i
            item.setData(Qt.UserRole, original_index)
            self.list_widget.addItem(item)

    def _update_button_states(self):
        has_selection = bool(self.list_widget.selectedItems())
        self.load_button.setEnabled(len(self.list_widget.selectedItems()) == 1)
        self.delete_button.setEnabled(has_selection)

    def _save_history_to_file_internal(self):
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            QMessageBox.warning(self, "保存历史失败", f"无法将更改保存到历史记录文件: {e}")
            return False

    def update_preview(self, current_item, previous_item=None):
        if not current_item:
            self.prompt_preview_edit.clear()
            self.prompt_preview_edit.setPlaceholderText("请选择一条历史记录以预览。")
            return
        original_index = current_item.data(Qt.UserRole)
        if not (0 <= original_index < len(self.history_data)):
            self.prompt_preview_edit.setPlainText("错误：无法获取记录数据。")
            return
        selected_record_data = self.history_data[original_index]
        preview_lines = []
        files_in_record = selected_record_data.get("files", [])
        if files_in_record:
            preview_lines.append("--- 文件列表 ---")
            for file_entry in files_in_record:
                filename = file_entry.get("filename")
                if not filename or filename == "未知文件":
                     path = file_entry.get("path")
                     filename = os.path.basename(path) if path else "未知文件"
                
                if filename != "未知文件" or file_entry.get("content","").strip():
                    preview_lines.append(f"  • {filename}")
            preview_lines.append("")
        prompt_content = selected_record_data.get("final_prompt", "").strip()
        preview_lines.append("--- 最终Prompt指令 ---")
        if prompt_content: preview_lines.append(prompt_content)
        else: preview_lines.append("(无)")
        self.prompt_preview_edit.setPlainText("\n".join(preview_lines))

    def delete_selected_records(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items: return

        reply = QMessageBox.question(self, "确认删除",
                                     f"确定要删除选中的 {len(selected_items)} 条历史记录吗？此操作不可恢复。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.No: return
        original_indices_to_delete = sorted([item.data(Qt.UserRole) for item in selected_items], reverse=True)
        for index in original_indices_to_delete:
            if 0 <= index < len(self.history_data):
                del self.history_data[index]
        if self._save_history_to_file_internal():
            print(f"已成功删除 {len(selected_items)} 条记录。")
            pass

        current_row_before_delete = self.list_widget.currentRow()
        self._populate_list_widget()
        if self.list_widget.count() > 0:
            new_row = min(current_row_before_delete, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(new_row if new_row >=0 else 0)
            if not self.list_widget.currentItem() and self.list_widget.count() > 0 : self.list_widget.setCurrentRow(0)
        else:
            self.prompt_preview_edit.clear()
            self.prompt_preview_edit.setPlaceholderText("没有历史记录可供预览。")
        self._update_button_states()

    def load_selected_record(self):
        selected_items = self.list_widget.selectedItems()
        if len(selected_items) == 1:
            current_item = selected_items[0]
            original_index = current_item.data(Qt.UserRole)
            if 0 <= original_index < len(self.history_data):
                selected_record_data = self.history_data[original_index]
                self.record_selected.emit(selected_record_data)
                self.accept()
            else: QMessageBox.warning(self, "错误", "无法加载选中的记录，索引无效。")
        elif len(selected_items) > 1:
             QMessageBox.information(self, "提示", "请只选择一条记录进行加载。")

# --- 主窗口 ---
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.file_blocks = []
        self.project_desc_button_group = QButtonGroup(self)
        self.project_desc_options = [
            "我有一个Xcode开发的iPhone手机应用程序.",
            "我有一个JavaScript和html发的chrome插件程序",
            "我有一个AppleScript开发的自动化脚本",
            "我有一个Android开发的程序"
        ]
        self.project_desc_radio_buttons_map = {}
        self.custom_desc_radio_button = None
        self.custom_desc_input = None

        self.init_ui()
        self._restore_settings() # 修改：在UI初始化后恢复设置
        self._ensure_history_file_exists()

    def _ensure_history_file_exists(self):
        if not os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
            except IOError as e: QMessageBox.critical(self, "文件错误", f"无法创建历史文件: {HISTORY_FILE}\n{e}")

    def _load_history_from_file(self):
        if not os.path.exists(HISTORY_FILE): return []
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f: history = json.load(f)
            return history if isinstance(history, list) else []
        except (json.JSONDecodeError, IOError) as e:
            QMessageBox.warning(self, "加载历史失败", f"无法读取历史文件: {e}")
            return []

    def _save_record_to_file(self, record_data):
        history = self._load_history_from_file()
        history.append(record_data)
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history, f, ensure_ascii=False, indent=4)
            print("记录已自动保存到历史。")
        except Exception as e: QMessageBox.warning(self, "保存失败", f"无法保存历史记录: {e}")

    def _handle_project_desc_selection_changed(self, button_id):
        selected_button = self.project_desc_button_group.button(button_id)
        is_custom_selected = (selected_button == self.custom_desc_radio_button)
        
        self.custom_desc_input.setEnabled(is_custom_selected)

        if is_custom_selected:
            self.custom_desc_input.setFocus()
        else:
            if selected_button in self.project_desc_radio_buttons_map:
                preset_text = self.project_desc_radio_buttons_map[selected_button]
                self.custom_desc_input.setText(preset_text)

    def init_ui(self):
        self.setWindowTitle("代码与Prompt整合工具")
        self.setGeometry(100, 100, 1600, 900)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # 修改：将分割器设为实例属性，以便保存和恢复状态
        self.main_splitter = QSplitter(Qt.Vertical)
        self.top_splitter = QSplitter(Qt.Horizontal)

        # --- 上部区域 (项目介绍和项目名称) ---
        project_desc_groupbox = QGroupBox("项目介绍:")
        project_desc_main_layout = QVBoxLayout()
        if self.project_desc_options:
            for i, option_text in enumerate(self.project_desc_options):
                option_item_layout = QHBoxLayout()
                radio_button = QRadioButton()
                label = QLabel(option_text)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                label.setWordWrap(True)
                option_item_layout.addWidget(radio_button)
                option_item_layout.addWidget(label, 1)
                project_desc_main_layout.addLayout(option_item_layout)
                self.project_desc_button_group.addButton(radio_button, i)
                self.project_desc_radio_buttons_map[radio_button] = option_text
        custom_option_layout = QHBoxLayout()
        self.custom_desc_radio_button = QRadioButton("自定义:")
        custom_option_layout.addWidget(self.custom_desc_radio_button)
        self.custom_desc_input = QLineEdit()
        self.custom_desc_input.setPlaceholderText("在此输入自定义项目介绍...")
        custom_option_layout.addWidget(self.custom_desc_input, 1)
        project_desc_main_layout.addLayout(custom_option_layout)
        custom_radio_id = len(self.project_desc_options)
        self.project_desc_button_group.addButton(self.custom_desc_radio_button, custom_radio_id)
        project_desc_groupbox.setLayout(project_desc_main_layout)
        self.project_desc_button_group.buttonClicked[int].connect(self._handle_project_desc_selection_changed)
        
        project_name_widget = QWidget()
        project_name_group_layout = QVBoxLayout(project_name_widget)
        project_name_group_layout.addWidget(QLabel("项目名称:"))
        self.project_name_input = QLineEdit()
        self.project_name_input.setObjectName("project_name_input") # 修改：设置对象名
        self.project_name_input.setPlaceholderText("例如：Finance")
        project_name_group_layout.addWidget(self.project_name_input)

        self.top_splitter.addWidget(project_desc_groupbox)
        self.top_splitter.addWidget(project_name_widget)

        # --- 中部区域 (文件块) ---
        middle_section_widget = QWidget()
        second_section_wrapper_layout = QHBoxLayout(middle_section_widget)
        second_section_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        second_section_wrapper_layout.setSpacing(5)

        self.file_blocks_splitter = QSplitter(Qt.Horizontal) # 修改：设为实例属性
        second_section_wrapper_layout.addWidget(self.file_blocks_splitter, 1)

        self.add_file_block_button = QPushButton("+")
        self.add_file_block_button.setObjectName("addButton") # 修改：设置对象名
        self.add_file_block_button.setToolTip("增加文件引入块")
        self.add_file_block_button.setFixedSize(30, 30)
        self.add_file_block_button.clicked.connect(lambda: self._add_file_block_widget(add_to_list_ref=True))
        add_button_layout = QVBoxLayout()
        add_button_layout.addWidget(self.add_file_block_button)
        add_button_layout.addStretch()
        second_section_wrapper_layout.addLayout(add_button_layout)

        for _ in range(3): self._add_file_block_widget(add_to_list_ref=True)

        # --- 下部区域 (Prompt指令和按钮) ---
        bottom_section_widget = QWidget()
        bottom_section_layout = QVBoxLayout(bottom_section_widget)
        bottom_section_layout.addWidget(QLabel("最终Prompt指令:"))
        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("prompt_input") # 修改：设置对象名
        self.prompt_input.setPlaceholderText("例如：我现在需要制作底部tab里的“资产”页面...")
        self.prompt_input.setMinimumHeight(100)
        self.prompt_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bottom_section_layout.addWidget(self.prompt_input)

        self.load_history_button = QPushButton("加载历史记录")
        self.load_history_button.clicked.connect(self.show_history_dialog)
        self.generate_button = QPushButton("生成最终文本并保存记录")
        self.generate_button.setObjectName("generateButton") # 修改：设置对象名
        self.generate_button.setFixedHeight(40)
        self.generate_button.clicked.connect(self.generate_and_save_output)

        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.addWidget(self.load_history_button)
        bottom_buttons_layout.addStretch()
        bottom_buttons_layout.addWidget(self.generate_button)
        bottom_section_layout.addLayout(bottom_buttons_layout)

        # --- 组合所有区域 ---
        self.main_splitter.addWidget(self.top_splitter)
        self.main_splitter.addWidget(middle_section_widget)
        self.main_splitter.addWidget(bottom_section_widget)
        
        main_layout.addWidget(self.main_splitter)

        # --- 初始化默认值 ---
        if self.project_desc_options:
            first_preset_button = self.project_desc_button_group.button(0)
            if first_preset_button:
                first_preset_button.setChecked(True)
                self._handle_project_desc_selection_changed(0) 
        else:
            self.custom_desc_radio_button.setChecked(True)
            self._handle_project_desc_selection_changed(custom_radio_id)

    # ==================== 新增：恢复设置的方法 ====================
    def _restore_settings(self):
        """在程序启动时恢复窗口和分割器的状态。"""
        global LAST_FILE_SELECTION_PATH
        settings = QSettings("MyCustomTools", "PromptGeneratorApp")

        # 恢复上次使用的路径
        saved_path = settings.value("last_path", DEFAULT_FILE_SELECTION_PATH)
        if os.path.isdir(saved_path):
            LAST_FILE_SELECTION_PATH = saved_path
        else:
            LAST_FILE_SELECTION_PATH = DEFAULT_FILE_SELECTION_PATH

        # 恢复窗口几何信息
        geometry = settings.value("main_window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

        # 恢复分割器状态
        main_splitter_state = settings.value("main_splitter_state")
        if main_splitter_state:
            self.main_splitter.restoreState(main_splitter_state)

        top_splitter_state = settings.value("top_splitter_state")
        if top_splitter_state:
            self.top_splitter.restoreState(top_splitter_state)

        file_blocks_splitter_state = settings.value("file_blocks_splitter_state")
        if file_blocks_splitter_state:
            self.file_blocks_splitter.restoreState(file_blocks_splitter_state)
    # ==================== 代码修改结束 ====================

    # ==================== 新增：窗口关闭事件处理 ====================
    def closeEvent(self, event):
        """在窗口关闭时保存其状态。"""
        settings = QSettings("MyCustomTools", "PromptGeneratorApp")
        settings.setValue("main_window_geometry", self.saveGeometry())
        settings.setValue("main_splitter_state", self.main_splitter.saveState())
        settings.setValue("top_splitter_state", self.top_splitter.saveState())
        settings.setValue("file_blocks_splitter_state", self.file_blocks_splitter.saveState())
        super().closeEvent(event)
    # ==================== 代码修改结束 ====================

    def _clear_all_file_blocks_ui(self):
        """安全地清除文件块分割器中的所有控件。"""
        for i in reversed(range(self.file_blocks_splitter.count())):
            widget = self.file_blocks_splitter.widget(i)
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _add_file_block_widget(self, add_to_list_ref=False, file_data=None):
        file_block = FileBlockWidget()
        file_block.delete_requested.connect(self._handle_delete_file_block)
        file_block.files_selected.connect(self.handle_multiple_files_selected)

        if file_data: file_block.load_data(file_data.get("path"), file_data.get("content"))
        
        self.file_blocks_splitter.addWidget(file_block)
        
        if add_to_list_ref: self.file_blocks.append(file_block)
        return file_block

    def handle_multiple_files_selected(self, file_paths):
        """接收一个文件路径列表，并为每个文件路径填充或创建一个新的文件块。"""
        empty_blocks = [w for w in self.file_blocks if w.file_path is None]
        
        for i, f_path in enumerate(file_paths):
            block_to_populate = None
            if i < len(empty_blocks):
                block_to_populate = empty_blocks[i]
            else:
                block_to_populate = self._add_file_block_widget(add_to_list_ref=True)
            
            if block_to_populate:
                block_to_populate.populate_with_file(f_path)

    def _handle_delete_file_block(self, block_to_delete):
        """处理删除文件块的请求。"""
        if block_to_delete in self.file_blocks: self.file_blocks.remove(block_to_delete)
        block_to_delete.deleteLater()

    def show_history_dialog(self):
        history_data = self._load_history_from_file()
        if not history_data:
            QMessageBox.information(self, "无历史记录", "目前没有已保存的历史记录。")
            return
        dialog = HistoryDialog(history_data, self)
        dialog.record_selected.connect(self.load_record_into_ui)
        dialog.exec_()

    def load_record_into_ui(self, record_data):
        self.project_name_input.setText(record_data.get("project_name", ""))
        
        saved_desc = record_data.get("project_desc", "").strip()
        found_preset = False
        
        for radio_button, preset_text in self.project_desc_radio_buttons_map.items():
            if preset_text == saved_desc:
                radio_button.setChecked(True)
                found_preset = True
                break
        
        if not found_preset:
            if saved_desc:
                self.custom_desc_radio_button.setChecked(True)
                self.custom_desc_input.setText(saved_desc) 
            else:
                if self.project_desc_options:
                    first_preset_button = self.project_desc_button_group.button(0)
                    if first_preset_button: first_preset_button.setChecked(True)
                else:
                    self.custom_desc_radio_button.setChecked(True)
                self.custom_desc_input.clear()

        current_checked_button = self.project_desc_button_group.checkedButton()
        if current_checked_button:
            button_id = self.project_desc_button_group.id(current_checked_button)
            self._handle_project_desc_selection_changed(button_id)

        self.prompt_input.setPlainText(record_data.get("final_prompt", ""))
        self._clear_all_file_blocks_ui()
        self.file_blocks.clear()
        loaded_files_data = record_data.get("files", [])
        if loaded_files_data:
            for file_info in loaded_files_data:
                new_block = self._add_file_block_widget(add_to_list_ref=False, file_data=file_info)
                self.file_blocks.append(new_block)
        num_to_add = 3 - len(self.file_blocks)
        if num_to_add > 0:
            for _ in range(num_to_add): self._add_file_block_widget(add_to_list_ref=True)
        
        # 恢复分割器比例
        self.file_blocks_splitter.setSizes([1] * len(self.file_blocks))


    def keyPressEvent(self, event):
        """重写 keyPressEvent 方法以捕获键盘事件。"""
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def generate_and_save_output(self):
        project_name = self.project_name_input.text().strip()
        
        project_desc = ""
        checked_radio_button = self.project_desc_button_group.checkedButton()
        if checked_radio_button == self.custom_desc_radio_button:
            project_desc = self.custom_desc_input.text().strip()
            if not project_desc:
                QMessageBox.warning(self, "信息不完整", "自定义项目介绍不能为空。")
                return
        elif checked_radio_button in self.project_desc_radio_buttons_map:
            project_desc = self.project_desc_radio_buttons_map[checked_radio_button]
        else:
            if self.project_desc_options:
                 project_desc = self.project_desc_options[0]

        final_prompt = self.prompt_input.toPlainText().strip()

        if not project_name:
            QMessageBox.warning(self, "信息不完整", "请输入项目名称。")
            return
        if not project_desc:
            QMessageBox.warning(self, "信息不完整", "请选择或输入项目介绍。")
            return

        current_record = {
            "id": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_name": project_name,
            "project_desc": project_desc,
            "files": [],
            "final_prompt": final_prompt
        }
        file_tree_lines = []
        valid_file_infos_for_output = []
        
        current_ui_file_blocks = [self.file_blocks_splitter.widget(i) for i in range(self.file_blocks_splitter.count()) if isinstance(self.file_blocks_splitter.widget(i), FileBlockWidget)]
        
        for block_widget in current_ui_file_blocks:
            path, filename, content = block_widget.get_file_info()
            if path or content.strip():
                current_record["files"].append({"path": path, "filename": filename, "content": content})
                if path:
                    file_tree_lines.append(f"  ├── {filename}")
                    valid_file_infos_for_output.append({"path": path, "content": content})
                elif content.strip():
                    temp_filename = "临时内容块" 
                    file_tree_lines.append(f"  ├── {temp_filename} (仅内容)")
                    valid_file_infos_for_output.append({"path": f"{temp_filename} (内容)", "content": content})
        
        self._save_record_to_file(current_record)
        final_builder = [project_desc]
        tree_string = "\n".join(file_tree_lines) if file_tree_lines else ""
        final_builder.append(f'\n"{project_name}"' + (f'\n{tree_string}' if tree_string else ""))
        for info in valid_file_infos_for_output:
            if info["path"].strip() or info["content"].strip():
                 final_builder.append(f'\n\n{info["path"]}\n“{info["content"]}”；')
        if final_prompt: final_builder.append(f'\n\n{final_prompt}')
        final_text = "".join(final_builder)
        output_dialog = OutputDialog(final_text, self)
        output_dialog.exec_()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # ==================== 修改：应用全局 QSS 主题 ====================
    app.setStyleSheet(NORD_QSS)
    # ==================== 代码修改结束 ====================

    history_dir = os.path.dirname(HISTORY_FILE)
    if history_dir and not os.path.exists(history_dir):
        try: os.makedirs(history_dir)
        except OSError as e: print(f"警告: 无法创建历史记录目录 {history_dir}: {e}")
    
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())