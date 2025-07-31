import re
import os
import sys
import shutil
import pyperclip
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QFileDialog, QMessageBox
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

# 全局变量
file_moved = False

def show_warning_message():
    # 创建一个临时的顶层窗口
    tmp = QWidget()
    tmp.setWindowFlags(Qt.WindowStaysOnTopHint)
    
    # 显示警告消息
    QMessageBox.warning(tmp, "警告", "目录segments中存在同名的txt文件，请先处理好现有文件。")
    
    # 销毁临时窗口
    tmp.deleteLater()

class TextSplitterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle("分割文本")
        self.setFont(QFont("Helvetica", 14))
        
        layout = QVBoxLayout()

        self.clipboard_size_label = QLabel(f"文本大小：{get_clipboard_size()}")
        layout.addWidget(self.clipboard_size_label)

        self.info_label = QLabel("需要分割成几份？")
        layout.addWidget(self.info_label)

        self.entry = QLineEdit()
        self.entry.setFocus()
        self.entry.returnPressed.connect(self.on_split)
        layout.addWidget(self.entry)

        self.setLayout(layout)
        self.center()

    def center(self):
        qr = self.frameGeometry()
        cp = QApplication.desktop().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.on_escape()

    def on_escape(self):
        global file_moved
        file_moved = False
        self.close()

    def on_split(self):
        global file_moved
        try:
            n = int(self.entry.text())
            if n <= 0:
                raise ValueError("请输入大于0的数字")
            save_segments(n)
            file_moved = True
        except ValueError as ve:
            print(f"错误：{ve}")
        except Exception as e:
            print(f"发生错误：{e}")
        finally:
            self.close()

def move_file_to_backup(file_path, destination_folder):
    try:
        shutil.move(file_path, os.path.join(destination_folder, os.path.basename(file_path)))
        print(f"文件已移动到：{destination_folder}")
    except Exception as e:
        print(f"移动文件时发生错误：{e}")

def get_clipboard_size():
    text = pyperclip.paste()
    size_bytes = len(text.encode('utf-8'))
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"

def find_nearest_sentence_end(text, start, ideal_end):
    positions = [
        text.rfind('.\n', start, ideal_end),
        text.rfind('。\n', start, ideal_end),
        text.find('.\n', ideal_end),
        text.find('。\n', ideal_end)
    ]
    valid_positions = [pos for pos in positions if pos != -1]
    return min(valid_positions, key=lambda pos: abs(pos - ideal_end)) if valid_positions else ideal_end

def split_text(text, n):
    segments, start = [], 0
    ideal_segment_length = len(text) // n

    for _ in range(n - 1):
        ideal_end = min(start + ideal_segment_length, len(text) - 1)
        nearest_end = find_nearest_sentence_end(text, start, ideal_end)
        segments.append(text[start:nearest_end + 1])
        start = nearest_end + 1

    segments.append(text[start:])
    return segments

def save_segments(n, save_path="/Users/yanzhang/Downloads/backup/TXT/Segments/"):
    text = pyperclip.paste()
    segments = split_text(text, n)

    os.makedirs(save_path, exist_ok=True)
    for i, segment in enumerate(segments):
        with open(os.path.join(save_path, f'segment_{i + 1}.txt'), 'w', encoding='utf-8') as file:
            file.write(segment)
        print(f"第{i + 1}部分已保存到: {save_path}")

def contains_segment(filename, segment):
    return segment in filename

def check_for_existing_segments(directory, segment):
    return any(file.endswith('.txt') and contains_segment(file, segment) for file in os.listdir(directory))

url_pattern = re.compile(
    r'(?:\s|^)([^ \n]*http[s]?://[^ \n]*(?=\s|$)|'
    r'[^ \n]*www\.[^ \n]*(?=\s|$)|'
    r'[^ \n]*E-mail[^ \n]*(?=\s|$)|'
    r'[^ \n]*\.(com|gov|org|edu|cn|us|html|htm|shtm|uk|xml|js|css|it)[^ \n]*(?=\s|$)|'
    r'[^ \n]+\.[^ \n]+\.[^ \n]+)(?=\s|$)'
)

save_path = "/Users/yanzhang/Downloads/backup/TXT/Segments/"

# 定义默认打开目录
DEFAULT_OPEN_DIR = "/Users/yanzhang/Downloads/backup/TXT"

if __name__ == '__main__':
    app = QApplication(sys.argv)

    if check_for_existing_segments(save_path, 'segment'):
        show_warning_message()
        sys.exit()

    # 使用新的默认目录打开文件选择对话框
    source_file_path, _ = QFileDialog.getOpenFileName(
        None, 
        '选择要处理的文件', 
        DEFAULT_OPEN_DIR,
        'Text files (*.txt);;All files (*.*)'
    )

    if not source_file_path:
        print('没有选择文件。')
        sys.exit()

    with open(source_file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    clean_content = re.sub(url_pattern, '', content)
    pyperclip.copy(clean_content)

    text_splitter = TextSplitterApp()
    text_splitter.show()

    app.exec_()

    if 'segment' not in os.path.basename(source_file_path):
        new_file_directory = "/Users/yanzhang/Documents/"
        new_file_path = os.path.join(new_file_directory, os.path.basename(source_file_path))

        try:
            os.makedirs(new_file_directory, exist_ok=True)
            with open(new_file_path, 'x', encoding='utf-8'):
                pass
            print(f"在 {new_file_directory} 下创建了同名空txt文件：{os.path.basename(source_file_path)}")
        except FileExistsError:
            print(f"文件已存在：{new_file_path}")
        except Exception as e:
            print(f"创建文件时发生错误：{e}")
    else:
        print('文件名中包含"segment"，不创建空文件。')

    backup_folder = "/Users/yanzhang/Downloads/backup/TXT/Done"

    if file_moved:
        if contains_segment(os.path.basename(source_file_path), 'segment'):
            os.remove(source_file_path)
            print(f"文件包含'segment'，已被删除：{source_file_path}")
        else:
            move_file_to_backup(source_file_path, backup_folder)

    sys.exit()