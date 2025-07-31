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
    # --- 修改点 1: 新增信号，用于在选择文件后，将文件路径列表发送给主窗口 ---
    files_selected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.original_content_on_load = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        path_layout = QHBoxLayout()
        self.path_button = QPushButton("选择文件")
        self.path_button.clicked.connect(self.select_file)

        # --- 修改开始: 将 ElidedLabel 替换为 QLineEdit ---
        # 原来的 ElidedLabel 只能显示文本，无法编辑。
        # 新的 QLineEdit 允许用户直接输入或粘贴文件路径。
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("输入/粘贴路径后按Enter加载, 或直接编辑下方内容")
        # 当用户在 QLineEdit 中完成编辑（按Enter或失去焦点）时，会触发 editingFinished 信号。
        # 我们将这个信号连接到一个新的处理函数 _on_path_manually_entered。
        self.path_input.editingFinished.connect(self._on_path_manually_entered)
        # --- 修改结束 ---

        self.delete_button = QPushButton("X")
        self.delete_button.setFixedSize(32, 22)
        self.delete_button.setToolTip("删除此文件块")
        self.delete_button.clicked.connect(self._request_delete_self)
        path_layout.addWidget(self.path_button)
        
        # --- 修改开始: 将新的 path_input 添加到布局中 ---
        path_layout.addWidget(self.path_input, 1) # 使用 self.path_input 替代 self.path_label
        # --- 修改结束 ---

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

    # --- 修改开始: 新增方法，处理手动输入的路径 ---
    def _on_path_manually_entered(self):
        """
        当用户在路径输入框中完成编辑时（例如按回车），此方法被调用。
        """
        path = self.path_input.text().strip()
        # 移除可能存在于macOS路径粘贴中的 "file://" 前缀
        if path.startswith("file://"):
            path = path[7:]
            
        # 检查路径是否为一个有效的文件
        if path and os.path.isfile(path):
            # 如果是有效文件，则调用现有的 populate_with_file 方法加载其内容
            self.populate_with_file(path)
        elif not path:
            # 如果用户清空了路径，我们也清空文件路径和内容
            self.file_path = None
            self.content_edit.clear()
            self.original_content_on_load = ""
    # --- 修改结束 ---

    def select_file(self):
        global LAST_FILE_SELECTION_PATH
        start_path = LAST_FILE_SELECTION_PATH
        if not os.path.exists(start_path):
            start_path = os.path.expanduser("~")
        
        formats = "*.swift *.py *.html *.css *.js *.scpt *.txt *.json *.csv *.db"
        f_paths, _ = QFileDialog.getOpenFileNames(self, "选择一个或多个文件", start_path, f"支持的文件 ({formats});;所有文件 (*)")
        
        if f_paths:
            # 更新全局变量
            LAST_FILE_SELECTION_PATH = os.path.dirname(f_paths[0])
            
            # --- 新增代码：保存新路径到设置 ---
            # 同样使用之前定义的名字来获取同一个 QSettings 对象
            settings = QSettings("MyCustomTools", "PromptGeneratorApp")
            settings.setValue("last_path", LAST_FILE_SELECTION_PATH)
            # --- 新增代码结束 ---

            # 发射信号
            self.files_selected.emit(f_paths)

    # --- 修改点 3: 新增方法，用于根据单个文件路径填充本控件的内容 ---
    def populate_with_file(self, f_path):
        """
        用给定的文件路径 f_path 来加载和显示文件信息。
        """
        global LAST_FILE_SELECTION_PATH
        if not f_path: return

        # 注意：这里的更新是可选的了，因为 select_file 已经更新了。
        # 但保留它也无害，当从历史记录加载文件时，它能确保路径正确更新。
        LAST_FILE_SELECTION_PATH = os.path.dirname(f_path)
        self.file_path = f_path
        
        # --- 修改开始: 更新 QLineEdit 的文本而不是 ElidedLabel ---
        self.path_input.setText(f_path)
        self.path_input.setToolTip(f_path)
        # --- 修改结束 ---
        
        _, file_extension = os.path.splitext(f_path)
        
        # 对于特定二进制文件，只显示占位符
        if file_extension.lower() in (".db", ".scpt"):
            self.content_edit.clear()
            self.content_edit.setPlaceholderText(f"这是一个 {file_extension} 二进制文件，内容未加载。\n您可以在此手动输入或编辑与该数据库文件相关的信息或说明。")
            self.original_content_on_load = ""
        else:
            # 尝试读取和显示文本文件内容
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
        # --- 修改开始: 从 QLineEdit 获取路径文本 ---
        current_path_text = self.path_input.text().strip()
        # --- 修改结束 ---

        if self.file_path:
            filename = os.path.basename(self.file_path)
        # --- 修改开始: 调整逻辑以适应 QLineEdit ---
        # 如果 self.file_path 未设置（例如，用户手动输入但未加载成功，或直接粘贴内容），
        # 我们尝试从输入框的文本中推断文件名。
        elif current_path_text:
            filename = os.path.basename(current_path_text)
        # --- 修改结束 ---

        content = self.content_edit.toPlainText()
        # --- 修改开始: 确定实际路径 ---
        # actual_path 优先使用 self.file_path (通过成功加载文件设置)
        # 否则，使用用户在输入框中输入的文本
        actual_path = self.file_path if self.file_path else current_path_text
        # --- 修改结束 ---
        return actual_path, filename, content

    def load_data(self, path_text, content_text):
        self.file_path = path_text
        # --- 修改开始: 加载历史记录时，填充 QLineEdit ---
        self.path_input.setText(path_text if path_text else "")
        self.path_input.setToolTip(path_text if path_text else "")
        # --- 修改结束 ---
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

        # 修改部分开始
        self.text_edit = QTextEdit()  # 先创建一个空的 QTextEdit
        self.text_edit.setPlainText(text_content) # 然后显式地将内容设置为纯文本
        # 修改部分结束

        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        self.button_box = QDialogButtonBox()
        self.ok_button = self.button_box.addButton(QDialogButtonBox.Ok)
        self.ok_button.setText("确定")
        self.button_box.accepted.connect(self.accept)

        self.copy_btn = QPushButton("复制到剪贴板")
        # --- 修改点 1: 为“复制”按钮添加'C'快捷键 ---
        self.copy_btn.setShortcut("C")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.button_box.addButton(self.copy_btn, QDialogButtonBox.ActionRole)

        layout.addWidget(self.button_box)

    # --- 修改点 2: 重写 copy_to_clipboard 方法 ---
    def copy_to_clipboard(self):
        """复制内容到剪贴板，然后立即关闭对话框。"""
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        self.setWindowTitle("已复制到剪贴板!")
        QTimer.singleShot(2000, self.restore_title)
        self.accept() # 调用accept()来关闭对话框

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
                # --- 修改开始: 预览时优先显示文件名，其次是路径 ---
                filename = file_entry.get("filename")
                if not filename or filename == "未知文件":
                     path = file_entry.get("path")
                     filename = os.path.basename(path) if path else "未知文件"
                
                if filename != "未知文件" or file_entry.get("content","").strip():
                    preview_lines.append(f"  • {filename}")
                # --- 修改结束 ---
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

        # --- 新增代码：程序启动时加载设置 ---
        global LAST_FILE_SELECTION_PATH
        # 创建一个 QSettings 对象。建议提供公司/组织名和应用名，以创建唯一的存储位置。
        settings = QSettings("MyCustomTools", "PromptGeneratorApp") 
        
        # 读取名为 "last_path" 的设置项。如果不存在，则使用 DEFAULT_FILE_SELECTION_PATH 作为默认值。
        saved_path = settings.value("last_path", DEFAULT_FILE_SELECTION_PATH)

        # 检查保存的路径是否仍然有效（例如，文件夹未被删除）
        if os.path.isdir(saved_path):
            LAST_FILE_SELECTION_PATH = saved_path
        else:
            # 如果路径无效，则退回到默认路径
            LAST_FILE_SELECTION_PATH = DEFAULT_FILE_SELECTION_PATH
        # --- 新增代码结束 ---

        self.file_blocks = []
        self.project_desc_button_group = QButtonGroup(self)
        # 预设的项目介绍选项
        self.project_desc_options = [
            "我有一个Xcode开发的iPhone手机应用程序.",
            "我有一个JavaScript和html发的chrome插件程序",
            "我有一个AppleScript开发的自动化脚本",
            "我有一个Python开发的程序"
        ]
        # 用于映射预设 QRadioButton 对象到其对应的文本
        self.project_desc_radio_buttons_map = {}
        # “自定义”选项的 QRadioButton
        self.custom_desc_radio_button = None
        # 自定义项目介绍的输入框
        self.custom_desc_input = None

        self.init_ui()
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
            # 如果选择的是预设选项，将其文本复制到自定义输入框中，方便用户修改
            if selected_button in self.project_desc_radio_buttons_map:
                preset_text = self.project_desc_radio_buttons_map[selected_button]
                self.custom_desc_input.setText(preset_text)

    def init_ui(self):
        self.setWindowTitle("代码与Prompt整合工具")
        self.setGeometry(100, 100, 1600, 900)
        # 1. 创建主垂直布局，并减小默认边距和控件间距
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5) 

        # --- MODIFICATION START ---
        # “加载历史记录”按钮的创建移到这里，但暂时不添加到任何布局
        self.load_history_button = QPushButton("加载历史记录")
        self.load_history_button.clicked.connect(self.show_history_dialog)
        # 原 top_buttons_layout 已被移除
        # --- MODIFICATION END ---

        top_section_layout = QHBoxLayout()
        project_name_group_layout = QVBoxLayout()
        project_name_group_layout.addWidget(QLabel("项目名称:"))
        self.project_name_input = QLineEdit()
        self.project_name_input.setStyleSheet("font-size:20pt;")
        self.project_name_input.setPlaceholderText("例如：Finance")
        project_name_group_layout.addWidget(self.project_name_input)
        top_section_layout.addLayout(project_name_group_layout, 1)

        # --- 项目介绍部分修改 ---
        project_desc_groupbox = QGroupBox("项目介绍:")
        project_desc_main_layout = QVBoxLayout() # GroupBox内部的主布局

        # 添加预设选项 (RadioButton + 可复制的Label)
        if self.project_desc_options:
            for i, option_text in enumerate(self.project_desc_options):
                option_item_layout = QHBoxLayout() # 用于放置单选按钮和标签
                
                radio_button = QRadioButton() # 单选按钮本身可以没有文本
                
                label = QLabel(option_text) # 标签显示文本，并允许选择复制
                label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                label.setWordWrap(True) # 长文本自动换行

                option_item_layout.addWidget(radio_button)
                option_item_layout.addWidget(label, 1) # 标签占据更多空间
                project_desc_main_layout.addLayout(option_item_layout)

                self.project_desc_button_group.addButton(radio_button, i) # ID为索引
                self.project_desc_radio_buttons_map[radio_button] = option_text # 映射按钮到文本
            
        # 添加“自定义”选项
        custom_option_layout = QHBoxLayout() # 用于自定义单选按钮和输入框
        self.custom_desc_radio_button = QRadioButton("自定义:")
        custom_option_layout.addWidget(self.custom_desc_radio_button)

        self.custom_desc_input = QLineEdit() # 自定义输入框
        self.custom_desc_input.setPlaceholderText("在此输入自定义项目介绍...")
        custom_option_layout.addWidget(self.custom_desc_input, 1)
        
        project_desc_main_layout.addLayout(custom_option_layout)
        
        # 为自定义单选按钮分配一个唯一的ID
        # ID = 预设选项的数量 (如果预设选项从0开始编号，这个ID就是下一个可用的)
        custom_radio_id = len(self.project_desc_options)
        self.project_desc_button_group.addButton(self.custom_desc_radio_button, custom_radio_id)
        
        project_desc_groupbox.setLayout(project_desc_main_layout)
        top_section_layout.addWidget(project_desc_groupbox, 2)
        
        # 连接按钮组的信号，以处理自定义输入框的启用/禁用和文本填充
        self.project_desc_button_group.buttonClicked[int].connect(self._handle_project_desc_selection_changed)
        # --- 结束项目介绍部分修改 ---
        
        main_layout.addLayout(top_section_layout)

        # 文件块区域
        self.file_blocks_container_widget = QWidget()
        self.file_blocks_layout = QHBoxLayout(self.file_blocks_container_widget)
        self.file_blocks_layout.setContentsMargins(0,0,0,0)
        self.file_blocks_layout.setSpacing(5)
        second_section_wrapper_layout = QHBoxLayout()
        second_section_wrapper_layout.addWidget(self.file_blocks_container_widget, 1)
        self.add_file_block_button = QPushButton("+")
        self.add_file_block_button.setToolTip("增加文件引入块")
        self.add_file_block_button.setFixedSize(30, 30)
        self.add_file_block_button.clicked.connect(lambda: self._add_file_block_widget(add_to_list_ref=True))
        add_button_layout = QVBoxLayout()
        add_button_layout.addWidget(self.add_file_block_button)
        add_button_layout.addStretch()
        second_section_wrapper_layout.addLayout(add_button_layout)
        main_layout.addLayout(second_section_wrapper_layout)

        for _ in range(3): self._add_file_block_widget(add_to_list_ref=True)

        # Prompt指令区域
        bottom_section_layout = QVBoxLayout()
        bottom_section_layout.addWidget(QLabel("最终Prompt指令:"))
        self.prompt_input = QTextEdit()
        self.prompt_input.setStyleSheet("font-size:18pt;")
        self.prompt_input.setPlaceholderText("例如：我现在需要制作底部tab里的“资产”页面...")
        self.prompt_input.setMinimumHeight(100)
        self.prompt_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bottom_section_layout.addWidget(self.prompt_input)
        
        # --- MODIFICATION START ---
        # “生成最终文本并保存记录”按钮的创建
        self.generate_button = QPushButton("生成最终文本并保存记录")
        self.generate_button.setFixedHeight(40)
        self.generate_button.clicked.connect(self.generate_and_save_output)

        # 创建一个新的 QHBoxLayout 用于底部的两个按钮
        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.addWidget(self.load_history_button) # 添加“加载历史记录”按钮
        bottom_buttons_layout.addStretch() # 添加伸缩项
        bottom_buttons_layout.addWidget(self.generate_button) # 添加“生成”按钮
        
        bottom_section_layout.addLayout(bottom_buttons_layout) # 将此新布局添加到 bottom_section_layout
        # --- MODIFICATION END ---
        
        main_layout.addLayout(bottom_section_layout)

        # --- MODIFICATION START ---
        # 更新 StretchFactor 设置
        # main_layout.setStretchFactor(top_buttons_layout, 0) # 此行移除，因为 top_buttons_layout 不再存在
        main_layout.setStretchFactor(top_section_layout, 0)
        main_layout.setStretchFactor(second_section_wrapper_layout, 1) # 文件块区域将扩展
        main_layout.setStretchFactor(bottom_section_layout, 0)
        # --- MODIFICATION END ---

        # 初始化项目介绍部分的状态
        if self.project_desc_options: # 如果有预设选项，默认选中第一个
            first_preset_button = self.project_desc_button_group.button(0)
            if first_preset_button:
                first_preset_button.setChecked(True)
                # 触发一次处理函数，以设置自定义输入框的初始状态和文本
                self._handle_project_desc_selection_changed(0) 
        else: # 没有预设选项，默认选中自定义
            self.custom_desc_radio_button.setChecked(True)
            self._handle_project_desc_selection_changed(custom_radio_id)


    def _clear_all_file_blocks_ui(self):
        while self.file_blocks_layout.count():
            child = self.file_blocks_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

    def _add_file_block_widget(self, add_to_list_ref=False, file_data=None):
        file_block = FileBlockWidget()
        file_block.delete_requested.connect(self._handle_delete_file_block)
        # --- 修改点 4: 连接新信号到主窗口的新槽函数 ---
        file_block.files_selected.connect(self.handle_multiple_files_selected)

        if file_data: file_block.load_data(file_data.get("path"), file_data.get("content"))
        
        self.file_blocks_layout.addWidget(file_block)
        if add_to_list_ref: self.file_blocks.append(file_block)
        return file_block

    # --- 修改点 5: 新增的槽函数，用于处理批量文件选择 ---
    def handle_multiple_files_selected(self, file_paths):
        """
        接收一个文件路径列表，并为每个文件路径填充或创建一个新的文件块。
        """
        # 查找当前所有未加载文件的空文件块
        empty_blocks = [
            w for w in self.file_blocks if w.file_path is None
        ]
        
        for i, f_path in enumerate(file_paths):
            block_to_populate = None
            if i < len(empty_blocks):
                # 如果有可用的空文件块，则使用它
                block_to_populate = empty_blocks[i]
            else:
                # 如果空文件块用完了，就创建一个新的
                block_to_populate = self._add_file_block_widget(add_to_list_ref=True)
            
            # 使用文件路径填充该块
            if block_to_populate:
                block_to_populate.populate_with_file(f_path)

    def _handle_delete_file_block(self, block_to_delete):
        if block_to_delete in self.file_blocks: self.file_blocks.remove(block_to_delete)
        self.file_blocks_layout.removeWidget(block_to_delete)
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
        
        # 尝试匹配预设选项
        for radio_button, preset_text in self.project_desc_radio_buttons_map.items():
            if preset_text == saved_desc:
                radio_button.setChecked(True)
                # self._handle_project_desc_selection_changed 将处理 custom_desc_input
                found_preset = True
                break
        
        if not found_preset:
            # 如果描述不为空且不匹配任何预设，则认为是自定义的
            if saved_desc:
                self.custom_desc_radio_button.setChecked(True)
                self.custom_desc_input.setText(saved_desc) 
                # self._handle_project_desc_selection_changed 将处理 custom_desc_input.setEnabled
            else: # 描述为空，默认选中第一个预设（如果存在）或自定义（如果无预设）
                if self.project_desc_options:
                    first_preset_button = self.project_desc_button_group.button(0)
                    if first_preset_button: first_preset_button.setChecked(True)
                else:
                    self.custom_desc_radio_button.setChecked(True)
                self.custom_desc_input.clear() # 清空自定义输入

        # 触发一次处理函数以确保UI状态（如custom_input的enable/disable和文本）正确同步
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

    def generate_and_save_output(self):
        project_name = self.project_name_input.text().strip()
        
        # 获取项目介绍
        project_desc = ""
        checked_radio_button = self.project_desc_button_group.checkedButton()
        if checked_radio_button == self.custom_desc_radio_button:
            project_desc = self.custom_desc_input.text().strip()
            if not project_desc: # 如果自定义选项被选中但内容为空
                QMessageBox.warning(self, "信息不完整", "自定义项目介绍不能为空。")
                return
        elif checked_radio_button in self.project_desc_radio_buttons_map:
            project_desc = self.project_desc_radio_buttons_map[checked_radio_button]
        else: # Fallback, 理论上QButtonGroup保证有选中，但以防万一
            if self.project_desc_options: # 尝试默认第一个预设
                 project_desc = self.project_desc_options[0]
            # 如果连预设都没有，project_desc会是空字符串，后续检查会捕获

        final_prompt = self.prompt_input.toPlainText().strip()

        if not project_name:
            QMessageBox.warning(self, "信息不完整", "请输入项目名称。")
            return
        if not project_desc: # 确保项目介绍不为空
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
        
        # 确保从UI布局中获取最新的控件列表
        current_ui_file_blocks = [self.file_blocks_layout.itemAt(i).widget() for i in range(self.file_blocks_layout.count()) if isinstance(self.file_blocks_layout.itemAt(i).widget(), FileBlockWidget)]
        
        for block_widget in current_ui_file_blocks:
            path, filename, content = block_widget.get_file_info()
            # --- 修改开始: 调整判断逻辑 ---
            # 只要路径或内容不为空，就视为有效块
            if path or content.strip():
                current_record["files"].append({"path": path, "filename": filename, "content": content})
                if path:
                    file_tree_lines.append(f"  ├── {filename}")
                    valid_file_infos_for_output.append({"path": path, "content": content})
                elif content.strip(): # 仅有内容，没有路径
                    # 使用一个临时的名字，或允许用户在未来版本中指定
                    temp_filename = "临时内容块" 
                    file_tree_lines.append(f"  ├── {temp_filename} (仅内容)")
                    valid_file_infos_for_output.append({"path": f"{temp_filename} (内容)", "content": content})
            # --- 修改结束 ---
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
    history_dir = os.path.dirname(HISTORY_FILE)
    if history_dir and not os.path.exists(history_dir):
        try: os.makedirs(history_dir)
        except OSError as e: print(f"警告: 无法创建历史记录目录 {history_dir}: {e}")
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())