import sys
import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTextEdit, QPushButton, QLabel, QFileDialog,
    QDialog, QMessageBox,
    QCheckBox, QListWidget, QListWidgetItem,
    QSplitter, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextDocument, QTextCursor, QKeySequence

# ==================== 配置区域 (跨平台修改) ====================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础编码目录 (假设结构一致，如果不同请手动调整)
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 具体文件路径
HISTORY_FILE = os.path.join(BASE_CODING_DIR, "python_code", "Modules", "Prompt_history.json")
DEFAULT_FILE_SELECTION_PATH = BASE_CODING_DIR
LAST_FILE_SELECTION_PATH = DEFAULT_FILE_SELECTION_PATH

# ==================== Nord 主题 QSS (跨平台优化) ====================

NORD_QSS = """
QWidget {
    background-color: #2E3440;
    color: #D8DEE9;
    /* 跨平台字体适配: Segoe UI (Win), San Francisco (Mac), Roboto (Android/Linux), YaHei (Fallback) */
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, "Microsoft YaHei", sans-serif;
    font-size: 13px;
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
/* 针对 Prompt 指令输入框的特殊样式 - 字体调大 */
#prompt_input_field {
    font-size: 16px;
    line-height: 1.5;
    padding: 8px;
}
QListWidget {
    border: 1px solid #434C5E;
    outline: none;
}
QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #2E3440;
}
QListWidget::item:selected {
    background-color: #4C566A;
    color: #ECEFF4;
    border-radius: 2px;
}
QLineEdit:focus, QTextEdit:focus, QListWidget:focus {
    border: 1px solid #5E81AC;
}
QPushButton {
    background-color: #434C5E;
    color: #ECEFF4;
    border: 1px solid #4C566A;
    padding: 6px 12px;
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
    background-color: transparent;
}
QPushButton#deleteButton:hover { color: #D08770; }
/* 优化：减小项目名称输入框的尺寸 */
#project_name_input {
    font-size: 14px; 
    font-weight: bold;
    padding: 4px;
    height: 25px;
}
/* 分割线设为极细且与背景同色 */
QSplitter::handle { 
    background-color: #2E3440; 
}
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
/* 滚动条美化 */
QScrollBar:vertical {
    border: none;
    background: #2E3440;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #4C566A;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""

# --- 查找替换对话框 (PyQt6 适配版) ---
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
        # PyQt6: 使用完整的枚举路径
        flags = QTextDocument.FindFlag(0)
        if self.case_cb.isChecked(): flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.word_cb.isChecked(): flags |= QTextDocument.FindFlag.FindWholeWords
        
        res = self.target_text_edit.find(self.find_input.text(), flags)
        if not res:
            self.target_text_edit.moveCursor(QTextCursor.MoveOperation.Start)
            res = self.target_text_edit.find(self.find_input.text(), flags)
        self._update_btns()
        return res

    def replace_current(self):
        if self.target_text_edit.textCursor().hasSelection():
            self.target_text_edit.textCursor().insertText(self.replace_input.text())
            self.find_next()

    def replace_all(self):
        self.target_text_edit.moveCursor(QTextCursor.MoveOperation.Start)
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
        if event.matches(QKeySequence.StandardKey.Find):
            if not self.search_dialog: self.search_dialog = SearchReplaceDialog(self, self.window())
            self.search_dialog.show(); self.search_dialog.find_input.setFocus()
        else: super().keyPressEvent(event)

class FileBlockWidget(QWidget):
    delete_requested = pyqtSignal(QWidget)
    files_selected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        path_layout = QHBoxLayout()
        self.path_btn = QPushButton("☜"); self.path_btn.setFixedWidth(30)
        self.path_btn.clicked.connect(self.select_file)
        
        self.path_input = QLineEdit(); self.path_input.setPlaceholderText("路径...")
        
        # =========== 【恢复的功能：绑定编辑完成信号】 ============
        # 当输入框失去焦点（例如点击了下方内容框）或按回车时，触发加载
        self.path_input.editingFinished.connect(self.load_from_input)
        # ======================================================
        self.del_btn = QPushButton("X"); self.del_btn.setObjectName("deleteButton"); self.del_btn.setFixedSize(24, 24)
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self))
        
        path_layout.addWidget(self.path_btn); path_layout.addWidget(self.path_input); path_layout.addWidget(self.del_btn)
        layout.addLayout(path_layout)
        
        self.content_edit = FileContentTextEdit()
        layout.addWidget(self.content_edit)

    def select_file(self):
        global LAST_FILE_SELECTION_PATH
        # 确保路径存在，否则回退到主目录
        if not os.path.exists(LAST_FILE_SELECTION_PATH):
            LAST_FILE_SELECTION_PATH = USER_HOME

        f_paths, _ = QFileDialog.getOpenFileNames(self, "选择文件", LAST_FILE_SELECTION_PATH)
        if f_paths:
            LAST_FILE_SELECTION_PATH = os.path.dirname(f_paths[0])
            self.files_selected.emit(f_paths)

    def populate_with_file(self, f_path):
        # <--- 跨平台：标准化路径分隔符 (Windows上将 / 变为 \)
        f_path = os.path.normpath(f_path)
        
        self.path_input.setText(f_path)
        try:
            with open(f_path, 'r', encoding='utf-8') as f: 
                self.content_edit.setPlainText(f.read())
        except UnicodeDecodeError:
            # 尝试 GBK 兼容 Windows 旧文件
            try:
                with open(f_path, 'r', encoding='gbk') as f:
                    self.content_edit.setPlainText(f.read())
            except:
                self.content_edit.setPlaceholderText("无法读取或二进制文件")
        except: 
            self.content_edit.setPlaceholderText("无法读取文件")

    def get_file_info(self):
        p = self.path_input.text().strip()
        return p, os.path.basename(p), self.content_edit.toPlainText()

    def load_data(self, path, content):
        if path:
            self.path_input.setText(os.path.normpath(path))
        self.content_edit.setPlainText(content)

    # =========== 【恢复的功能：手动输入加载逻辑】 ============
    def load_from_input(self):
        p = self.path_input.text().strip()
        # 处理某些系统复制路径可能带有的 file:// 前缀
        if p.startswith("file://"):
            p = p[7:]
        
        # <--- 跨平台：处理 Windows 路径引号问题 (e.g. "C:\Path\To\File")
        p = p.strip('"').strip("'")
        
        if p and os.path.exists(p) and os.path.isfile(p):
            self.populate_with_file(p)

# ==================== 恢复：带快捷键和自动关闭的输出对话框 ====================
class OutputDialog(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成结果")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.edit = QTextEdit(); self.edit.setPlainText(text); self.edit.setReadOnly(True)
        layout.addWidget(self.edit)
        
        btns = QHBoxLayout()
        # 快捷键 C 复制并关闭
        self.copy_btn = QPushButton("复制到剪贴板 (C)")
        self.copy_btn.setShortcut(QKeySequence("C"))
        self.copy_btn.clicked.connect(self.do_copy)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        
        btns.addWidget(self.copy_btn); btns.addStretch(); btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def do_copy(self):
        QApplication.clipboard().setText(self.edit.toPlainText())
        # 恢复：复制后自动关闭窗口
        self.accept()

# ==================== 历史记录对话框 (PyQt6 适配版) ====================
class HistoryDialog(QDialog):
    record_selected = pyqtSignal(dict)

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.resize(900, 600)
        self.data = data 
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15) # 增加外边距
        layout.setSpacing(10) # 增加组件间距
        # PyQt6: Qt.Orientation.Horizontal
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)
        
        self.list = QListWidget()
        # PyQt6: QAbstractItemView.SelectionMode.ExtendedSelection
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._refresh_list()
        
        self.prev = QTextEdit()
        self.prev.setReadOnly(True)
        self.prev.setPlaceholderText("选择左侧记录以预览内容...")
        
        split.addWidget(self.list)
        split.addWidget(self.prev)
        split.setSizes([300, 600])
        
        layout.addWidget(split, 1) # 分割器占据主要空间
        # 底部按钮区域
        btn_layout = QHBoxLayout()
        self.del_btn = QPushButton("删除选中记录")
        self.del_btn.setObjectName("deleteButton")
        self.del_btn.setFixedWidth(120)
        
        self.load_btn = QPushButton("加载选中记录")
        self.load_btn.setFixedHeight(35)
        self.load_btn.setFixedWidth(150)
        
        btn_layout.addWidget(self.del_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.load_btn)
        
        layout.addLayout(btn_layout)
        # 信号连接
        self.list.currentItemChanged.connect(self.show_prev)
        self.list.itemDoubleClicked.connect(self.load)
        self.load_btn.clicked.connect(self.load)
        self.del_btn.clicked.connect(self.delete_records)

    def _refresh_list(self):
        self.list.clear()
        for i, r in enumerate(reversed(self.data)):
            item = QListWidgetItem(f"{r.get('id')} - {r.get('project_name')}")
            # PyQt6: Qt.ItemDataRole.UserRole
            item.setData(Qt.ItemDataRole.UserRole, len(self.data)-1-i)
            self.list.addItem(item)

    def show_prev(self, curr, prev_item):
        if curr:
            r = self.data[curr.data(Qt.ItemDataRole.UserRole)]
            files_str = "\n".join([f"• {f.get('filename')}" for f in r.get('files', [])])
            self.prev.setPlainText(f"项目: {r.get('project_name')}\n\n文件列表:\n{files_str}\n\nPrompt:\n{r.get('final_prompt')}")

    def delete_records(self):
        items = self.list.selectedItems()
        if not items: return
        if QMessageBox.question(self, "确认", f"确定删除这 {len(items)} 条历史记录吗？") == QMessageBox.StandardButton.Yes:
            indices = sorted([it.data(Qt.ItemDataRole.UserRole) for it in items], reverse=True)
            for idx in indices:
                if 0 <= idx < len(self.data): del self.data[idx]
            # 同步到文件
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(self.data, f, indent=4, ensure_ascii=False)
            except: pass
            self._refresh_list()
            self.prev.clear()

    def load(self):
        if self.list.currentItem():
            self.record_selected.emit(self.data[self.list.currentItem().data(Qt.ItemDataRole.UserRole)])
            self.accept()

# ==================== 主窗口 ====================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.file_blocks = []
        self.file_block_splitters = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("代码与Prompt整合工具 (PyQt6)")
        
        self.resize(1600, 1000)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5) # 减小窗口边距
        # PyQt6: Qt.Orientation.Vertical
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setHandleWidth(1)
        # --- 1. 顶部区域 ---
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(10, 5, 10, 5)
        fixed_label = QLabel("以下是这次要处理的内容.")
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

        # --- 2. 中部：文件块区域 ---
        mid_widget = QWidget()
        mid_layout = QHBoxLayout(mid_widget)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout = QVBoxLayout()
        self.container_layout.setSpacing(2)
        container_widget = QWidget(); container_widget.setLayout(self.container_layout)
        mid_layout.addWidget(container_widget, 1)
        
        self.add_btn = QPushButton("+"); self.add_btn.setFixedSize(30, 30)
        self.add_btn.clicked.connect(self._add_block_and_select_file)
        # PyQt6: Qt.AlignmentFlag.AlignTop
        mid_layout.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignTop)
        
        for _ in range(3): self._add_file_block_widget(True)
        self.main_splitter.addWidget(mid_widget)
        
        # --- 3. 底部：Prompt 指令输入区域 (修正：已添加到 splitter) ---
        bot_widget = QWidget()
        bot_layout = QVBoxLayout(bot_widget)
        bot_layout.setContentsMargins(5, 5, 5, 5)
        bot_layout.addWidget(QLabel("最终Prompt指令:"))
        
        # --- 修改点：将 prompt_input 替换为 FileContentTextEdit ---
        self.prompt_input = FileContentTextEdit()
        self.prompt_input.setObjectName("prompt_input_field")
        self.prompt_input.setPlaceholderText("在这里输入你的指令 (按 Ctrl+F 查找/替换)...")
        bot_layout.addWidget(self.prompt_input)
        
        btns = QHBoxLayout()
        self.hist_btn = QPushButton("历史记录"); self.hist_btn.clicked.connect(self.show_history)
        self.gen_btn = QPushButton("生成最终文本并保存记录"); self.gen_btn.setObjectName("generateButton")
        self.gen_btn.setFixedHeight(35); self.gen_btn.clicked.connect(self.generate)
        btns.addWidget(self.hist_btn); btns.addStretch(); btns.addWidget(self.gen_btn)
        bot_layout.addLayout(btns)
        
        # 将底部挂件添加到分割器
        self.main_splitter.addWidget(bot_widget)
        
        # 强制设置初始分配比例：顶部固定，中部占70%，底部占30%
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 4)
        self.main_splitter.setStretchFactor(2, 6)
        
        layout.addWidget(self.main_splitter)
        self.project_name_input.setFocus()

    def keyPressEvent(self, event):
        # PyQt6: Qt.Key.Key_Escape
        if event.key() == Qt.Key.Key_Escape: self.close()
        else: super().keyPressEvent(event)

    def _add_file_block_widget(self, add_ref=False, data=None):
        if not self.file_block_splitters or self.file_block_splitters[-1].count() >= 5:
            s = QSplitter(Qt.Orientation.Horizontal); self.container_layout.addWidget(s)
            s.setHandleWidth(1)
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
            if p in self.file_block_splitters: self.file_block_splitters.remove(p)
            p.deleteLater()

    def _add_block_and_select_file(self): self._add_file_block_widget(True).select_file()

    def generate(self):
        p_name = self.project_name_input.text().strip()
        if not p_name: return QMessageBox.warning(self, "错误", "请输入项目名称")
        
        fixed_desc = "我有一个新开发的应用程序."
        tree, contents, rec_files = [], [], []
        
        for b in self.file_blocks:
            path, fname, content = b.get_file_info()
            if path or content.strip():
                # <--- 跨平台：标准化路径用于存储
                path = os.path.normpath(path) if path else ""
                
                rec_files.append({"path": path, "filename": fname, "content": content})
                tree.append(f"├── {fname}")
                contents.append(f'\n\n{path if path else "临时内容"}\n“{content}”；')
        
        # 保存历史
        try:
            if not os.path.exists(HISTORY_FILE): os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            try: 
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f: history = json.load(f)
            except: history = []
            
            history.append({
                "id": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                "project_name": p_name, 
                "files": rec_files, 
                "final_prompt": self.prompt_input.toPlainText()
            })
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"保存历史失败: {e}")

        output = [fixed_desc, f'\n\n"{p_name}"', "\n" + "\n".join(tree)] + contents + [f"\n\n{self.prompt_input.toPlainText()}"]
        # PyQt6: exec()
        OutputDialog("".join(output), self).exec()

    def show_history(self):
        try:
            if not os.path.exists(HISTORY_FILE): return
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            if data:
                d = HistoryDialog(data, self)
                d.record_selected.connect(self.load_record)
                d.exec()
            else: QMessageBox.information(self, "提示", "暂无历史记录")
        except: pass

    def load_record(self, data):
        self.project_name_input.setText(data.get("project_name", ""))
        self.prompt_input.setPlainText(data.get("final_prompt", ""))
        # 清除现有块并重新加载
        for s in self.file_block_splitters: s.deleteLater()
        self.file_block_splitters.clear(); self.file_blocks.clear()
        
        for f in data.get("files", []): self._add_file_block_widget(True, f)
        while len(self.file_blocks) < 3: self._add_file_block_widget(True)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(NORD_QSS)
    win = MainWindow()
    win.show()
    # PyQt6: exec()
    sys.exit(app.exec())
