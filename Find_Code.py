import os
import sys
import pyperclip
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QTextBrowser, QMainWindow, QAction
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# 保持原有的搜索目录列表
searchFolders = [
    "/Users/yanzhang/Documents/ScriptEditor/",
    "/Users/yanzhang/Library/Services/",
    "/Users/yanzhang/Documents/Financial_System",
    "/Users/yanzhang/Documents/python_code",
    "/Users/yanzhang/Documents/News/backup",
    "/Users/yanzhang/Documents/sskeysskey.github.io",
    # "/Users/yanzhang/Documents/LuxuryBox",
    "/Users/yanzhang/Downloads/backup/TXT",
    "/Users/yanzhang/Documents/Books",
    "/Users/yanzhang/Documents/News/done",
    "/Users/yanzhang/Documents/Xcode/Indices/Finance",
    "/Users/yanzhang/Documents/sh"
]

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
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setFont(QFont("Arial", 14))
        self.loading_label.hide()
        self.layout.addWidget(self.loading_label)

        self.result_area = CustomTextBrowser()
        self.result_area.anchorClicked.connect(self.open_file)
        self.result_area.setFont(QFont("Arial", 12))
        self.layout.addWidget(self.result_area)

        self.search_button.clicked.connect(self.start_search)
        self.input_field.returnPressed.connect(self.start_search)

        # 添加 ESC 键关闭窗口的功能
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
                html_content += f"<h2 style='color: yellow; font-size: 18px;'>{directory}</h2>"
                for file in files:
                    # 确保使用绝对路径
                    file_path = os.path.abspath(os.path.join(directory, file))
                    # 确保路径格式正确
                    file_path = file_path.replace('\\', '/')
                    # 对路径进行编码
                    from urllib.parse import quote
                    encoded_path = quote(file_path)
                    file_url = f"file://{encoded_path}"
                    display_name = os.path.basename(file)
                    html_content += f"<p><a href='{file_url}' style='color: orange; text-decoration: underline; font-size: 18px;'>{display_name}</a></p>"

        self.result_area.setHtml(html_content)
        self.result_area.verticalScrollBar().setValue(0)

    def open_file(self, url):
        try:
            # 获取文件路径并处理可能的编码问题
            file_path = url.toLocalFile()
            if not file_path:
                file_path = url.toString().replace('file://', '')
                
            # URL解码处理
            from urllib.parse import unquote
            file_path = unquote(file_path).strip()
            
            # 确保路径是绝对路径
            abs_path = os.path.abspath(os.path.expanduser(file_path))
            
            print(f"调试信息:")
            print(f"原始URL: {url.toString()}")
            print(f"处理后路径: {abs_path}")
            print(f"文件是否存在: {os.path.exists(abs_path)}")
            
            if not os.path.exists(abs_path):
                raise Exception(f"文件不存在: {abs_path}")
                
            # 阻止事件进一步传播
            url.setUrl("")
            
            if abs_path.endswith('.workflow'):
                print("检测到workflow文件，尝试打开...")
                subprocess.run(['open', '-a', 'Automator', abs_path], 
                            check=True,
                            capture_output=True,
                            text=True)
            else:
                # macOS 系统使用 open 命令
                if sys.platform == 'darwin':  # macOS
                    subprocess.run(['open', abs_path], 
                                check=True,
                                capture_output=True,
                                text=True)
                elif sys.platform == 'win32':  # Windows
                    os.startfile(abs_path)
                else:  # Linux 和其他系统
                    subprocess.run(['xdg-open', abs_path], 
                                check=True,
                                capture_output=True,
                                text=True)
                        
        except Exception as e:
            error_msg = f"无法打开文件\n路径: {abs_path}\n错误: {str(e)}"
            print(error_msg)
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "错误", error_msg)

def process_keywords(keywords):
    """
    智能关键词处理函数:
    1. 如果有成对引号，提取引号中的内容作为完整短语
    2. 如果是不成对的引号，保留原始输入（包含引号）
    3. 否则按空格分割所有内容
    """
    keywords = keywords.strip()
    
    # 处理空输入
    if not keywords:
        return []

    # 计算引号数量    
    quote_count = keywords.count('"')
    
    # 如果引号不成对，将整个字符串（包含引号）作为一个关键词
    if quote_count % 2 != 0:
        return [keywords.lower()]
        
    # 如果有成对引号
    if quote_count > 0:
        phrases = []
        in_quotes = False
        current_phrase = []
        
        # 逐字符处理
        for char in keywords:
            if char == '"':
                if in_quotes:
                    # 引号结束，保存当前短语
                    if current_phrase:
                        phrases.append(''.join(current_phrase).strip().lower())
                    current_phrase = []
                in_quotes = not in_quotes
            else:
                if in_quotes:
                    current_phrase.append(char)
                else:
                    if char.isspace():
                        if current_phrase:
                            phrases.append(''.join(current_phrase).strip().lower())
                            current_phrase = []
                    else:
                        current_phrase.append(char)
        
        # 处理最后一个短语
        if current_phrase:
            phrases.append(''.join(current_phrase).strip().lower())
            
        return [phrase for phrase in phrases if phrase]

        # # 特殊字符列表
        # special_chars = '=<>+-*/()[]{}!@#$%^&'
        
        # # 如果以特殊字符开头
        # if keywords and keywords[0] in special_chars:
        #     special_char = keywords[0]
        #     remaining = keywords[1:].strip()
        #     # 将特殊字符后的内容按空格分割
        #     return [special_char] + [k.lower() for k in remaining.split() if k.strip()]
    
    # 默认按空格分割
    return [k.lower() for k in keywords.split() if k.strip()]

# 保持原有的搜索相关函数不变
def search_files(directories, keywords):
    if not keywords:  # 添加空关键词检查
        return {directory: [] for directory in directories}
        
    matched_files = {}
    
    for directory in directories:
        matched_files[directory] = []
        for root, dirs, files in os.walk(directory):
            for dir_name in dirs:
                if dir_name.endswith('.workflow'):
                    handle_workflow_dir(root, dir_name, directory, keywords, matched_files)
            for name in files:
                handle_file(root, name, directory, keywords, matched_files)
    return matched_files

def handle_workflow_dir(root, dir_name, directory, keywords, matched_files):  # 改为 keywords
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
    except Exception as e:
        print(f"Error reading {wflow_path}: {e}")

def handle_file(root, name, directory, keywords, matched_files):  # 改为 keywords
    item_path = os.path.join(root, name)
    
    # 检查文件名
    name_lower = name.lower()
    if all(keyword in name_lower for keyword in keywords):
        matched_files[directory].append(os.path.relpath(item_path, directory))
        return
        
    # 检查文件内容
    if item_path.endswith(('.txt', '.py', '.json', '.js', '.css', '.html', '.csv', '.md', '.swift', '.sh')):  # 添加 .swift
        try:
            with open(item_path, 'r', encoding='utf-8') as file:
                content = file.read().lower()
            if all(keyword in content for keyword in keywords):
                matched_files[directory].append(os.path.relpath(item_path, directory))
        except Exception as e:
            print(f"Error reading {item_path}: {e}")
    elif item_path.endswith('.scpt'):
        try:
            content = subprocess.check_output(['osadecompile', item_path], text=True).lower()
            if all(keyword in content for keyword in keywords):
                matched_files[directory].append(os.path.relpath(item_path, directory))
        except Exception as e:
            print(f"Error decompiling {item_path}: {e}")

def read_file_content(path):
    if path.endswith('.scpt'):
        return subprocess.check_output(['osadecompile', path], text=True).lower()
    with open(path, 'r') as file:
        return file.read().lower()

if __name__ == "__main__":
    # 处理剪贴板警告
    try:
        from PyQt5.QtWidgets import QApplication
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass  # 较旧的 PyQt 版本可能没有这些属性

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "input":
            # 显示窗口，让用户输入
            pass
        elif arg == "paste":
            # 使用剪贴板内容进行搜索
            clipboard_content = pyperclip.paste()
            if clipboard_content:
                window.input_field.setText(clipboard_content)
                window.start_search()
            else:
                print("剪贴板为空，请复制一些文本后再试。")
    else:
        print("请提供参数 input 或 paste")

    sys.exit(app.exec_())