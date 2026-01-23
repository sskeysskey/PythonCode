import os
import sys
import pyperclip
import subprocess
from urllib.parse import quote, unquote

# 1. 导入路径修改
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLineEdit, QLabel, QTextBrowser, 
                             QMainWindow, QMessageBox)
from PyQt6.QtGui import QFont, QKeySequence, QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础 Coding 目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 动态构建搜索目录列表
# 注意：以下路径是根据你的原列表迁移的。
# 如果某些路径在 Windows 上不存在（例如 Library/Services），脚本会自动跳过，或者你可以手动建立对应文件夹。
potential_folders = [
    os.path.join(BASE_CODING_DIR, "ScriptEditor"),
    os.path.join(USER_HOME, "Library", "Services"), # Windows 上可能不存在
    os.path.join(BASE_CODING_DIR, "Financial_System"),
    os.path.join(BASE_CODING_DIR, "python_code"),
    os.path.join(BASE_CODING_DIR, "News", "backup"),
    os.path.join(BASE_CODING_DIR, "Website"),
    os.path.join(USER_HOME, "Downloads", "backup", "TXT"),
    os.path.join(BASE_CODING_DIR, "Books"),
    os.path.join(BASE_CODING_DIR, "News", "done"),
    os.path.join(BASE_CODING_DIR, "Xcode", "Indices", "Finance"),
    os.path.join(BASE_CODING_DIR, "Xcode", "ONews", "ONews"),
    os.path.join(USER_HOME, ".hammerspoon"), # Mac 特有
    os.path.join(BASE_CODING_DIR, "sh"),
    os.path.join(BASE_CODING_DIR, "LocalServer")
]

# 过滤掉不存在的目录，防止报错
searchFolders = [f for f in potential_folders if os.path.exists(f)]

# ========================================================

class CustomTextBrowser(QTextBrowser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setOpenLinks(False)  # 禁止自动打开链接

class SearchWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, directories, keywords):
        super().__init__()
        self.directories = directories
        self.keywords = keywords

    def run(self):
        keywords_processed = process_keywords(self.keywords)
        results = search_files(self.directories, keywords_processed)
        self.finished.emit(results)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("代码和文件搜索")
        self.setGeometry(350, 200, 800, 600)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setFixedHeight(30)
        self.input_field.setFont(QFont("Arial", 18))
        
        self.search_button = QPushButton("搜索")
        self.search_button.setFixedSize(60, 30)
        
        self.input_layout.addWidget(self.input_field, 7)
        self.input_layout.addWidget(self.search_button, 1)
        self.layout.addLayout(self.input_layout)
        
        self.loading_label = QLabel("正在搜索...", self)
        # 2. 修改对齐方式枚举
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setFont(QFont("Arial", 14))
        self.loading_label.hide()
        self.layout.addWidget(self.loading_label)
        
        self.result_area = CustomTextBrowser()
        self.result_area.anchorClicked.connect(self.open_file)
        # 跨平台字体优化
        self.result_area.setFont(QFont("Segoe UI" if os.name == 'nt' else "Arial", 12))
        self.layout.addWidget(self.result_area)
        
        self.search_button.clicked.connect(self.start_search)
        self.input_field.returnPressed.connect(self.start_search)
        
        # 3. QAction 在 PyQt6 中属于 QtGui
        self.shortcut_close = QKeySequence("Esc")
        self.quit_action = QAction("Quit", self)
        self.quit_action.setShortcut(self.shortcut_close)
        self.quit_action.triggered.connect(self.close)
        self.addAction(self.quit_action)

    def start_search(self):
        keywords = self.input_field.text()
        self.loading_label.show()
        self.result_area.clear()
        self.result_area.setEnabled(False)
        self.search_button.setEnabled(False)
        self.input_field.setEnabled(False)
        
        self.worker = SearchWorker(searchFolders, keywords)
        self.worker.finished.connect(self.show_results)
        self.worker.start()

    def show_results(self, results):
        self.loading_label.hide()
        self.result_area.setEnabled(True)
        self.search_button.setEnabled(True)
        self.input_field.setEnabled(True)
        
        html_content = ""
        for directory, files in results.items():
            if files:
                # 显示大目录分组
                html_content += f"<h2 style='color: yellow; font-size: 18px;'>{directory}</h2>"
                for file in files:
                    # 确保使用绝对路径用于点击打开
                    file_path = os.path.abspath(os.path.join(directory, file))
                    
                    # <--- 跨平台修改：处理 Windows 路径的反斜杠 --->
                    # 浏览器无法识别 C:\Path，需要转为 C:/Path
                    file_path_for_url = file_path.replace('\\', '/')
                    if not file_path_for_url.startswith('/'):
                        # Windows 路径如果是 C:/... 需要在前面再加一个 / 变成 /C:/... 才能被 file:// 正确识别
                        file_path_for_url = '/' + file_path_for_url
                    
                    # 对路径进行编码
                    from urllib.parse import quote
                    encoded_path = quote(file_path_for_url)
                    file_url = f"file://{encoded_path}"
                    
                    # 直接使用包含相对路径的文件名用于显示
                    display_name = file 
                    
                    html_content += f"<p><a href='{file_url}' style='color: orange; text-decoration: underline; font-size: 18px;'>{display_name}</a></p>"
        
        self.result_area.setHtml(html_content)
        # 4. 修改滚动条获取方式
        self.result_area.verticalScrollBar().setValue(0)

    def open_file(self, url):
        abs_path = ""
        try:
            # 5. PyQt6 中 url 是 QUrl 对象
            file_path = url.toLocalFile()
            if not file_path:
                file_path = url.toString().replace('file://', '')
                # <--- 跨平台修改：处理 Windows file:// url 留下的前导 / --->
                if os.name == 'nt' and file_path.startswith('/') and ':' in file_path:
                    file_path = file_path.lstrip('/')
            
            file_path = unquote(file_path).strip()
            abs_path = os.path.abspath(os.path.expanduser(file_path))
            
            if not os.path.exists(abs_path):
                raise Exception(f"文件不存在: {abs_path}")
                
            # <--- 跨平台修改：区分平台执行打开操作 --->
            if sys.platform == 'darwin' and abs_path.endswith('.workflow'):
                subprocess.run(['open', '-a', 'Automator', abs_path], 
                            check=True, capture_output=True, text=True)
            else:
                if sys.platform == 'darwin':
                    subprocess.run(['open', abs_path], check=True, capture_output=True, text=True)
                elif sys.platform == 'win32':
                    os.startfile(abs_path)
                else: # Linux
                    subprocess.run(['xdg-open', abs_path], check=True, capture_output=True, text=True)
                        
        except Exception as e:
            error_msg = f"无法打开文件\n路径: {abs_path}\n错误: {str(e)}"
            QMessageBox.warning(self, "错误", error_msg)

def process_keywords(keywords):
    """
    智能关键词处理函数
    """
    keywords = keywords.strip()
    if not keywords: return []
    quote_count = keywords.count('"')
    if quote_count % 2 != 0: return [keywords.lower()]
        
    if quote_count > 0:
        phrases = []
        in_quotes = False
        current_phrase = []
        for char in keywords:
            if char == '"':
                if in_quotes:
                    if current_phrase: phrases.append(''.join(current_phrase).strip().lower())
                    current_phrase = []
                in_quotes = not in_quotes
            else:
                if in_quotes: current_phrase.append(char)
                else:
                    if char.isspace():
                        if current_phrase:
                            phrases.append(''.join(current_phrase).strip().lower())
                            current_phrase = []
                    else: current_phrase.append(char)
        if current_phrase: phrases.append(''.join(current_phrase).strip().lower())
        return [phrase for phrase in phrases if phrase]
    return [k.lower() for k in keywords.split() if k.strip()]

def search_files(directories, keywords):
    if not keywords: return {directory: [] for directory in directories}
    matched_files = {}
    for directory in directories:
        matched_files[directory] = []
        for root, dirs, files in os.walk(directory):
            # <--- 跨平台修改：Automator workflow 仅在 Mac 上处理 --->
            if sys.platform == 'darwin':
                for dir_name in dirs:
                    if dir_name.endswith('.workflow'):
                        handle_workflow_dir(root, dir_name, directory, keywords, matched_files)
            
            for name in files:
                handle_file(root, name, directory, keywords, matched_files)
    return matched_files

def handle_workflow_dir(root, dir_name, directory, keywords, matched_files):
    workflow_path = os.path.join(root, dir_name)
    if all(keyword in dir_name.lower() for keyword in keywords):
        matched_files[directory].append(os.path.relpath(workflow_path, directory))
        return
    try:
        wflow_path = os.path.join(workflow_path, 'contents/document.wflow')
        with open(wflow_path, 'r', encoding='utf-8') as file:
            content = file.read().lower()
        if all(keyword in content for keyword in keywords):
            matched_files[directory].append(os.path.relpath(workflow_path, directory))
    except Exception:
        pass

def handle_file(root, name, directory, keywords, matched_files):
    item_path = os.path.join(root, name)
    
    # 检查文件名
    name_lower = name.lower()
    if all(keyword in name_lower for keyword in keywords):
        matched_files[directory].append(os.path.relpath(item_path, directory))
        return
        
    # 检查文件内容
    # <--- 跨平台修改：增加 .bat, .ps1 等 Windows 常见脚本格式 --->
    valid_extensions = ('.txt', '.py', '.json', '.js', '.css', '.html', '.csv', '.md', '.swift', '.sh', '.lua', '.bat', '.ps1')
    
    if item_path.endswith(valid_extensions):
        try:
            with open(item_path, 'r', encoding='utf-8') as file:
                content = file.read().lower()
            if all(keyword in content for keyword in keywords):
                matched_files[directory].append(os.path.relpath(item_path, directory))
        except UnicodeDecodeError:
            # 尝试 GBK 兼容 Windows
            try:
                with open(item_path, 'r', encoding='gbk') as file:
                    content = file.read().lower()
                if all(keyword in content for keyword in keywords):
                    matched_files[directory].append(os.path.relpath(item_path, directory))
            except: pass
        except Exception:
            pass
    elif item_path.endswith('.scpt'):
        # <--- 跨平台修改：仅在 Mac 上尝试 osadecompile --->
        if sys.platform == 'darwin':
            try:
                content = subprocess.check_output(['osadecompile', item_path], text=True).lower()
                if all(keyword in content for keyword in keywords):
                    matched_files[directory].append(os.path.relpath(item_path, directory))
            except Exception:
                pass

if __name__ == "__main__":
    # 6. PyQt6 默认开启高分屏支持
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "input":
            pass
        elif arg == "paste":
            clipboard_content = pyperclip.paste()
            if clipboard_content:
                window.input_field.setText(clipboard_content)
                window.start_search()
            else:
                print("剪贴板为空")
    else:
        print("请提供参数 input 或 paste")
    
    # 7. exec_() 改为 exec()
    sys.exit(app.exec())
