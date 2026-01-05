import sys
import os
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTextEdit, QPushButton, QLabel, QFileDialog,
    QSizePolicy, QDialog, QMessageBox, QGroupBox,
    QCheckBox, QDialogButtonBox, QListWidget, QListWidgetItem,
    QSplitter, QAbstractItemView, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSettings
from PyQt5.QtGui import QTextDocument, QTextCursor, QKeySequence, QPainter

# ==================== 优化后的 Nord 主题 QSS ====================
NORD_QSS = """
QWidget {
    background-color: #2E3440;
    color: #D8DEE9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px; /* 稍微调小全局字体 */
    border: none;
}

QLineEdit, QTextEdit, QListWidget {
    background-color: #3B4252;
    color: #E5E9F0;
    border: 1px solid #434C5E;
    border-radius: 4px;
    padding: 4px;
    selection-background-color: #4C566A;
}

QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #5E81AC;
}

QPushButton {
    background-color: #434C5E;
    color: #ECEFF4;
    border: 1px solid #4C566A;
    padding: 6px 10px;
    border-radius: 4px;
}

QPushButton:hover { background-color: #4C566A; }
QPushButton:pressed { background-color: #5E81AC; }

QPushButton#generateButton {
    background-color: #A3BE8C;
    color: #2E3440;
    font-weight: bold;
}

QPushButton#deleteButton {
    color: #BF616A;
    font-weight: bold;
}

/* 优化：减小项目名称输入框的尺寸 */
#project_name_input {
    font-size: 14px; 
    font-weight: bold;
    padding: 4px;
    height: 25px;
}

QSplitter::handle { background-color: #2E3440; }
QSplitter::handle:hover { background-color: #5E81AC; }
"""

# --- 辅助组件 ---
class ElidedLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._full_text = ""
    def setText(self, text: str):
        self._full_text = text
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        fm = painter.fontMetrics()
        elided = fm.elidedText(self._full_text, Qt.ElideLeft, self.width())
        painter.drawText(self.rect(), self.alignment(), elided)

HISTORY_FILE = "/Users/yanzhang/Coding/python_code/Modules/Prompt_history.json"
DEFAULT_FILE_SELECTION_PATH = "/Users/yanzhang/Coding"
LAST_FILE_SELECTION_PATH = DEFAULT_FILE_SELECTION_PATH

# --- 查找替换对话框 ---
class SearchReplaceDialog(QDialog):
    def __init__(self, target_text_edit, parent=None):
        super().__init__(parent)
        self.target_text_edit = target_text_edit
        self.setWindowTitle("查找/替换")
        layout = QVBoxLayout(self)
        
        f_lay = QHBoxLayout(); f_lay.addWidget(QLabel("查找:")); self.find_input = QLineEdit(); f_lay.addWidget(self.find_input); layout.addLayout(f_lay)
        r_lay = QHBoxLayout(); r_lay.addWidget(QLabel("替换:")); self.replace_input = QLineEdit(); r_lay.addWidget(self.replace_input); layout.addLayout(r_lay)
        
        self.case_cb = QCheckBox("区分大小写"); self.word_cb = QCheckBox("全字匹配")
        opt_lay = QHBoxLayout(); opt_lay.addWidget(self.case_cb); opt_lay.addWidget(self.word_cb); layout.addLayout(opt_lay)
        
        btns = QHBoxLayout()
        self.f_btn = QPushButton("查找下一个"); self.r_btn = QPushButton("替换"); self.ra_btn = QPushButton("全部替换")
        btns.addWidget(self.f_btn); btns.addWidget(self.r_btn); btns.addWidget(self.ra_btn)
        layout.addLayout(btns)
        
        self.f_btn.clicked.connect(self.find_next)
        self.r_btn.clicked.connect(self.replace_current)
        self.ra_btn.clicked.connect(self.replace_all)
        self.find_input.textChanged.connect(self._update_btns)
        self._update_btns()

    def _update_btns(self):
        has_txt = bool(self.find_input.text())
        self.f_btn.setEnabled(has_txt); self.ra_btn.setEnabled(has_txt)
        self.r_btn.setEnabled(has_txt and self.target_text_edit.textCursor().hasSelection())

    def find_next(self):
        flags = QTextDocument.FindFlags()
        if self.case_cb.isChecked(): flags |= QTextDocument.FindCaseSensitively
        if self.word_cb.isChecked(): flags |= QTextDocument.FindWholeWords
        res = self.target_text_edit.find(self.find_input.text(), flags)
        if not res:
            self.target_text_edit.moveCursor(QTextCursor.Start)
            res = self.target_text_edit.find(self.find_input.text(), flags)
        self._update_btns()
        return res

    def replace_current(self):
        if self.target_text_edit.textCursor().hasSelection():
            self.target_text_edit.textCursor().insertText(self.replace_input.text())
            self.find_next()

    def replace_all(self):
        self.target_text_edit.moveCursor(QTextCursor.Start)
        count = 0
        while self.find_next():
            self.target_text_edit.textCursor().insertText(self.replace_input.text())
            count += 1
        QMessageBox.information(self, "完成", f"替换了 {count} 处")

class FileContentTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_dialog = None
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Find):
            if not self.search_dialog: self.search_dialog = SearchReplaceDialog(self, self.window())
            self.search_dialog.show()
            self.search_dialog.find_input.setFocus()
        else: super().keyPressEvent(event)

class FileBlockWidget(QWidget):
    delete_requested = pyqtSignal(QWidget)
    files_selected = pyqtSignal(list)
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2) # 紧凑内边距
        path_layout = QHBoxLayout()
        self.path_btn = QPushButton("☜"); self.path_btn.setFixedWidth(30)
        self.path_btn.clicked.connect(self.select_file)
        self.path_input = QLineEdit(); self.path_input.setPlaceholderText("路径...")
        self.del_btn = QPushButton("X"); self.del_btn.setObjectName("deleteButton"); self.del_btn.setFixedSize(24, 24)
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self))
        path_layout.addWidget(self.path_btn); path_layout.addWidget(self.path_input); path_layout.addWidget(self.del_btn)
        layout.addLayout(path_layout)
        self.content_edit = FileContentTextEdit()
        layout.addWidget(self.content_edit)

    def select_file(self):
        global LAST_FILE_SELECTION_PATH
        f_paths, _ = QFileDialog.getOpenFileNames(self, "选择文件", LAST_FILE_SELECTION_PATH)
        if f_paths:
            LAST_FILE_SELECTION_PATH = os.path.dirname(f_paths[0])
            self.files_selected.emit(f_paths)

    def populate_with_file(self, f_path):
        self.path_input.setText(f_path)
        try:
            with open(f_path, 'r', encoding='utf-8') as f: self.content_edit.setPlainText(f.read())
        except: self.content_edit.setPlaceholderText("无法读取或二进制文件")

    def get_file_info(self):
        p = self.path_input.text().strip()
        return p, os.path.basename(p), self.content_edit.toPlainText()

    def load_data(self, path, content):
        self.path_input.setText(path); self.content_edit.setPlainText(content)

class OutputDialog(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成结果")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.edit = QTextEdit(); self.edit.setPlainText(text); self.edit.setReadOnly(True)
        layout.addWidget(self.edit)
        btns = QHBoxLayout()
        copy = QPushButton("复制到剪贴板"); copy.clicked.connect(self.do_copy)
        ok = QPushButton("确定"); ok.clicked.connect(self.accept)
        btns.addWidget(copy); btns.addStretch(); btns.addWidget(ok)
        layout.addLayout(btns)
    def do_copy(self):
        QApplication.clipboard().setText(self.edit.toPlainText())
        self.setWindowTitle("已复制！")

class HistoryDialog(QDialog):
    record_selected = pyqtSignal(dict)
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录"); self.resize(800, 500)
        self.data = data
        layout = QHBoxLayout(self)
        self.list = QListWidget()
        for i, r in enumerate(reversed(data)):
            item = QListWidgetItem(f"{r.get('id')} - {r.get('project_name')}")
            item.setData(Qt.UserRole, len(data)-1-i); self.list.addItem(item)
        self.prev = QTextEdit(); self.prev.setReadOnly(True)
        split = QSplitter(Qt.Horizontal); split.addWidget(self.list); split.addWidget(self.prev)
        layout.addWidget(split)
        self.list.currentItemChanged.connect(self.show_prev)
        self.list.itemDoubleClicked.connect(self.load)
    def show_prev(self, curr):
        if curr:
            r = self.data[curr.data(Qt.UserRole)]
            self.prev.setPlainText(f"项目: {r['project_name']}\n\nPrompt:\n{r['final_prompt']}")
    def load(self):
        if self.list.currentItem():
            self.record_selected.emit(self.data[self.list.currentItem().data(Qt.UserRole)])
            self.accept()

# ==================== 主窗口 ====================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.file_blocks = []
        self.file_block_splitters = []
        self.init_ui()
        self._restore_settings()

    def init_ui(self):
        self.setWindowTitle("代码与Prompt整合工具")
        self.resize(1400, 900)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5) # 减小窗口边距

        self.main_splitter = QSplitter(Qt.Vertical)

        # --- 优化：压缩后的顶部区域 ---
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(10, 2, 10, 2) # 极窄的上下边距
        
        fixed_label = QLabel("我有一个新开发的应用程序.")
        fixed_label.setStyleSheet("font-size: 14px; color: #88C0D0; font-weight: bold;")
        top_layout.addWidget(fixed_label)
        
        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("项目名称:"))
        self.project_name_input = QLineEdit()
        self.project_name_input.setObjectName("project_name_input")
        self.project_name_input.setPlaceholderText("例如：Finance")
        top_layout.addWidget(self.project_name_input, 1)
        
        # 核心改动：固定顶部高度，不让它占据多余空间
        top_widget.setFixedHeight(45) 
        self.main_splitter.addWidget(top_widget)

        # --- 中部：文件块 ---
        mid_widget = QWidget()
        mid_layout = QHBoxLayout(mid_widget)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout = QVBoxLayout()
        self.container_layout.setSpacing(2)
        container_widget = QWidget(); container_widget.setLayout(self.container_layout)
        mid_layout.addWidget(container_widget, 1)
        
        self.add_btn = QPushButton("+"); self.add_btn.setFixedSize(30, 30)
        self.add_btn.clicked.connect(self._add_block_and_select_file)
        mid_layout.addWidget(self.add_btn, 0, Qt.AlignTop)
        
        for _ in range(3): self._add_file_block_widget(True)
        self.main_splitter.addWidget(mid_widget)

        # --- 底部：Prompt ---
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(5, 5, 5, 5)
        bot_layout.addWidget(QLabel("最终Prompt指令:"))
        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("prompt_input")
        bot_layout.addWidget(self.prompt_input)
        
        btns = QHBoxLayout()
        self.hist_btn = QPushButton("历史记录"); self.hist_btn.clicked.connect(self.show_history)
        self.gen_btn = QPushButton("生成最终文本"); self.gen_btn.setObjectName("generateButton")
        self.gen_btn.setFixedHeight(35); self.gen_btn.clicked.connect(self.generate)
        btns.addWidget(self.hist_btn); btns.addStretch(); btns.addWidget(self.gen_btn)
        bot_layout.addLayout(btns)
        
        self.main_splitter.addWidget(bot_widget)
        
        # 设置初始分配比例：顶部固定，中部和底部平分
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setStretchFactor(2, 1)
        
        layout.addWidget(self.main_splitter)
        self.project_name_input.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.close()
        else: super().keyPressEvent(event)

    def _add_file_block_widget(self, add_ref=False, data=None):
        if not self.file_block_splitters or self.file_block_splitters[-1].count() >= 5:
            s = QSplitter(Qt.Horizontal); self.container_layout.addWidget(s)
            self.file_block_splitters.append(s)
        block = FileBlockWidget()
        block.delete_requested.connect(self._handle_delete)
        block.files_selected.connect(self.handle_files)
        if data: block.load_data(data.get("path"), data.get("content"))
        self.file_block_splitters[-1].addWidget(block)
        if add_ref: self.file_blocks.append(block)
        return block

    def handle_files(self, paths):
        empty = [b for b in self.file_blocks if not b.path_input.text()]
        for i, p in enumerate(paths):
            target = empty[i] if i < len(empty) else self._add_file_block_widget(True)
            target.populate_with_file(p)

    def _handle_delete(self, block):
        if block in self.file_blocks: self.file_blocks.remove(block)
        p = block.parentWidget(); block.setParent(None); block.deleteLater()
        if isinstance(p, QSplitter) and p.count() == 0:
            self.file_block_splitters.remove(p); p.deleteLater()

    def _add_block_and_select_file(self): self._add_file_block_widget(True).select_file()

    def generate(self):
        p_name = self.project_name_input.text().strip()
        if not p_name: return QMessageBox.warning(self, "错误", "请输入项目名称")
        
        fixed_desc = "我有一个新开发的应用程序."
        tree, contents, rec_files = [], [], []
        
        for b in self.file_blocks:
            path, fname, content = b.get_file_info()
            if path or content.strip():
                rec_files.append({"path": path, "filename": fname, "content": content})
                tree.append(f"├── {fname}")
                contents.append(f'\n\n{path if path else "临时内容"}\n“{content}”；')

        # 保存历史
        try:
            if not os.path.exists(HISTORY_FILE): os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            try: 
                with open(HISTORY_FILE, 'r') as f: history = json.load(f)
            except: history = []
            history.append({"id": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "project_name": p_name, "files": rec_files, "final_prompt": self.prompt_input.toPlainText()})
            with open(HISTORY_FILE, 'w') as f: json.dump(history[-50:], f, indent=4, ensure_ascii=False)
        except: pass

        output = [fixed_desc, f'\n\n"{p_name}"', "\n" + "\n".join(tree)] + contents + [f"\n\n{self.prompt_input.toPlainText()}"]
        OutputDialog("".join(output), self).exec_()

    def show_history(self):
        try:
            with open(HISTORY_FILE, 'r') as f: data = json.load(f)
            if data:
                d = HistoryDialog(data, self)
                d.record_selected.connect(self.load_record)
                d.exec_()
        except: pass

    def load_record(self, data):
        self.project_name_input.setText(data.get("project_name", ""))
        self.prompt_input.setPlainText(data.get("final_prompt", ""))
        for s in self.file_block_splitters: s.deleteLater()
        self.file_block_splitters.clear(); self.file_blocks.clear()
        for f in data.get("files", []): self._add_file_block_widget(True, f)
        while len(self.file_blocks) < 3: self._add_file_block_widget(True)

    def _restore_settings(self):
        s = QSettings("MyTools", "PromptApp")
        if s.value("geo"): self.restoreGeometry(s.value("geo"))
        if s.value("split"): self.main_splitter.restoreState(s.value("split"))

    def closeEvent(self, event):
        s = QSettings("MyTools", "PromptApp")
        s.setValue("geo", self.saveGeometry()); s.setValue("split", self.main_splitter.saveState())
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(NORD_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())