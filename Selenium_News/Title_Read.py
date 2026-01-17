import shutil
from html.parser import HTMLParser
from math import ceil
import subprocess
import sys
import os
import tempfile

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础 Coding 目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 具体文件路径
NEWS_DIR = os.path.join(BASE_CODING_DIR, "News")
BACKUP_SITE_DIR = os.path.join(NEWS_DIR, "backup", "site")

# 4. 临时目录 (混合策略)
# Windows 下使用系统临时目录，Mac 下保持 /tmp 以兼容可能的外部 AppleScript
if os.name == 'nt':
    TEMP_DIR = tempfile.gettempdir()
else:
    TEMP_DIR = "/tmp"

# 具体文件路径定义
FILE_PATH_ENG = os.path.join(NEWS_DIR, 'today_eng.html')
FILE_PATH_WSJCN = os.path.join(NEWS_DIR, 'today_wsjcn.html')
FILE_PATH_DWCN = os.path.join(NEWS_DIR, 'today_dwcn.html')
FILE_PATH_RFICN = os.path.join(NEWS_DIR, 'today_rficn.html')
BACKUP_PATH_ENG = os.path.join(BACKUP_SITE_DIR, 'today_eng.html')

FILE_PATH_JPN = os.path.join(NEWS_DIR, 'today_jpn.html')
BACKUP_PATH_JPN = os.path.join(BACKUP_SITE_DIR, 'today_jpn.html')

TXT_PATH_ENG = os.path.join(NEWS_DIR, 'today_eng.txt')
TXT_PATH_JPN = os.path.join(NEWS_DIR, 'today_jpn.txt')

# 确保备份目录存在
os.makedirs(BACKUP_SITE_DIR, exist_ok=True)

# ========================================================

# 创建一个子类并重写HTMLParser的方法
class MyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles = []
        self.capture = False
        self.current_data = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr in attrs:
                if attr[0] == "target" and attr[1] == "_blank":
                    self.capture = True
                    self.current_data = []

    def handle_endtag(self, tag):
        if tag == "a" and self.capture:
            cleaned_data = ''.join(self.current_data).strip().strip('"').strip("'")
            if cleaned_data: # 确保不添加空标题
                self.titles.append(cleaned_data)
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.current_data.append(data.replace("\n", " ").replace("\r", " ").strip())

def add_line_numbers(text):
    """为文本添加行号"""
    lines = text.split('\n')
    return '\n'.join(f"{i+1}、{line}" for i, line in enumerate(lines) if line.strip())

def show_alert(message):
    """
    跨平台弹窗逻辑：
    - macOS: 保持原样，使用 AppleScript (osascript)
    - Windows/Linux: 使用 Tkinter 作为替补，防止报错
    """
    if sys.platform == 'darwin':
        # --- Mac 原生逻辑 (保持不变) ---
        applescript_code = f'display dialog "{message}" buttons {{"OK"}} default button "OK"'
        subprocess.run(['osascript', '-e', applescript_code], check=True)
    else:
        # --- Windows 替补逻辑 ---
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("提示", message)
        root.destroy()

# --- 主要逻辑开始 ---

# 检查英文主文件是否存在
html_content_eng = ""
try:
    with open(FILE_PATH_ENG, 'r', encoding='utf-8') as file:
        html_content_eng = file.read()

# 如果主文件不存在，则执行新的检查逻辑
except FileNotFoundError:
    # 检查后备文件是否存在 (WSJ, DW, 或 RFI 任意一个存在即可)
    # >>> 修改开始 <<<
    fallback_files = [FILE_PATH_WSJCN, FILE_PATH_DWCN, FILE_PATH_RFICN]
    if any(os.path.exists(f) for f in fallback_files):
        # 如果后备文件存在，打印信号字符串并退出Python脚本
        # AppleScript将会捕获这个字符串并据此行动
        print("USE_FALLBACK_AND_TERMINATE")
        show_alert("没有today_eng，但检测到中文新闻文件(WSJ/DW/RFI)，直接打开即可。")
        sys.exit(0) # 正常退出
    else:
        # 如果主文件和后备文件都不存在，则抛出原始错误
        raise FileNotFoundError(f"[Errno 2] No source files found. Checked: {FILE_PATH_ENG}, WSJ, DW, RFI.")

# --- 如果主文件存在，则继续执行以下代码 ---

# 创建解析器实例
parser_eng = MyHTMLParser()
# 喂数据给解析器
parser_eng.feed(html_content_eng)
# 获取提取到的标题
titles_eng = parser_eng.titles

# 添加行号并写入主文件
titles_text_eng = add_line_numbers("\n".join(titles_eng))

with open(TXT_PATH_ENG, 'w', encoding='utf-8') as a_file:
    a_file.write(titles_text_eng)

# 计算分割
total_chars_eng = len(titles_text_eng)
if total_chars_eng == 0:
    num_parts_eng = 1
else:
    num_parts_eng = ceil(total_chars_eng / 3000)

# 分割并写入子文件
titles_lines = titles_text_eng.split('\n')
if num_parts_eng > 0:
    lines_per_file = ceil(len(titles_lines) / num_parts_eng)
else:
    lines_per_file = len(titles_lines)

for i in range(num_parts_eng):
    start_line = i * lines_per_file
    end_line = min((i + 1) * lines_per_file, len(titles_lines))
    
    # 获取当前部分的行，并重新编号
    current_lines = titles_lines[start_line:end_line]
    # 移除旧的行号并添加新的行号
    current_lines = [line.split('、', 1)[1] if '、' in line else line for line in current_lines]
    numbered_lines = [f"{j+1}、{line}" for j, line in enumerate(current_lines) if line.strip()]
    
    # 写入文件 (使用动态路径)
    seg_file_path = os.path.join(TEMP_DIR, f'segment_{i+1}.txt')
    with open(seg_file_path, 'w', encoding='utf-8') as file:
        file.write('\n'.join(numbered_lines))

# 备份HTML源文件到指定目录，如果文件已存在则覆盖
shutil.copyfile(FILE_PATH_ENG, BACKUP_PATH_ENG)

# 处理日文文件
try:
    # 处理日文文件
    # 读取HTML文件内容
    with open(FILE_PATH_JPN, 'r', encoding='utf-8') as file:
        html_content_jpn = file.read()

    # 创建解析器实例
    parser_jpn = MyHTMLParser()
    # 喂数据给解析器
    parser_jpn.feed(html_content_jpn)
    # 获取提取到的标题
    titles_jpn = parser_jpn.titles

    # 添加行号并写入主文件
    titles_text_jpn = add_line_numbers("\n".join(titles_jpn))
    with open(TXT_PATH_JPN, 'w', encoding='utf-8') as a_file:
        a_file.write(titles_text_jpn)

    # 分割日文文件为两部分
    titles_lines_jpn = titles_text_jpn.split('\n')
    mid_point = len(titles_lines_jpn) // 2

    # 处理第一部分
    first_part = titles_lines_jpn[:mid_point]
    first_part = [line.split('、', 1)[1] if '、' in line else line for line in first_part]
    first_part_numbered = [f"{i+1}、{line}" for i, line in enumerate(first_part) if line.strip()]

    # 处理第二部分
    second_part = titles_lines_jpn[mid_point:]
    second_part = [line.split('、', 1)[1] if '、' in line else line for line in second_part]
    second_part_numbered = [f"{i+1}、{line}" for i, line in enumerate(second_part) if line.strip()]

    # 写入分割后的文件
    seg_jpn_1 = os.path.join(TEMP_DIR, f'segment_{num_parts_eng + 1}.txt')
    seg_jpn_2 = os.path.join(TEMP_DIR, f'segment_{num_parts_eng + 2}.txt')

    with open(seg_jpn_1, 'w', encoding='utf-8') as file:
        file.write('\n'.join(first_part_numbered))

    with open(seg_jpn_2, 'w', encoding='utf-8') as file:
        file.write('\n'.join(second_part_numbered))

    # 备份日文HTML文件
    shutil.copyfile(FILE_PATH_JPN, BACKUP_PATH_JPN)

except FileNotFoundError:
    print(f"Warning: {FILE_PATH_JPN} 文件不存在，已跳过日文文件的处理。", file=sys.stderr)
