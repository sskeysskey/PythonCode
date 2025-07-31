import re
import os
import time
import glob
import pyautogui
import pyperclip
import webbrowser
import subprocess
import tkinter as tk
from datetime import datetime
from bs4 import BeautifulSoup
from html.parser import HTMLParser

def delete_done_txt_files(directory):
    # 确保提供的目录路径是存在的
    if not os.path.exists(directory):
        print("提供的目录不存在")
        return
    
    try:
        # 遍历目录下的所有文件
        for filename in os.listdir(directory):
            # 构建完整的文件路径
            filepath = os.path.join(directory, filename)
            # 检查文件名是否符合条件
            if filename.startswith("done_") and filename.endswith(".txt"):
                # 删除文件
                os.remove(filepath)
                print(f"已删除文件：{filename}")
    except Exception as e:
        print(f"在删除文件时发生错误：{e}")

# 从剪贴板读取翻译后的内容
def get_clipboard_data():
    p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
    data, _ = p.communicate()
    return data.decode('utf-8').splitlines()

class MyHTMLParser(HTMLParser):
    def __init__(self, new_texts):
        super().__init__()
        self.new_texts = new_texts
        self.current_index = 0
        self.result_html = ""
        self.inside_a = False
        self.capture = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.inside_a = True
            self.capture = False  # 每次进入<a>标签时重置capture
            for attr in attrs:
                if attr[0] == "target" and attr[1] == "_blank":
                    self.capture = True
        self.result_html += self.get_starttag_text()

    def handle_endtag(self, tag):
        if tag == "a":
            self.inside_a = False
            self.capture = False  # 确保在离开<a>标签后不会错误地捕获文本
            self.current_index += 1  # 只有成功处理完一个<a>标签后，才增加索引
        self.result_html += f"</{tag}>"

    def handle_data(self, data):
        if self.inside_a and self.capture:
            if self.current_index < len(self.new_texts):
                self.result_html += self.new_texts[self.current_index]
            else:
                raise IndexError(f"错误：超出新文本行的数量。当前处理到第 {self.current_index + 1} 个链接，但是新文本只有 {len(self.new_texts)} 行。")
        else:
            self.result_html += data

# 文件路径
file_path = "/Users/yanzhang/Coding/News/today_chn.txt"

# 读取文件内容，并去除空行
with open(file_path, 'r', encoding='utf-8') as file:
    lines = file.readlines()
    non_empty_lines = [line for line in lines if line.strip()]

# 合并非空行，并去除尾部的换行符
content_to_copy = ''.join(non_empty_lines).rstrip('\n')

# 将内容复制到剪贴板
pyperclip.copy(content_to_copy)

# 读取剪贴板中翻译后的内容
translated_texts = get_clipboard_data()

# 过滤掉空行
translated_texts = [line for line in translated_texts if line.strip() != '']

# 读取HTML文件内容
try:
    with open('/Users/yanzhang/Coding/News/today_all.html', 'r', encoding='utf-8') as file:
        html_content = file.read()
except FileNotFoundError:
    try:
        print("未找到 today_all.html，尝试打开 today_eng.html")
        with open('/Users/yanzhang/Coding/News/today_eng.html', 'r', encoding='utf-8') as file:
            html_content = file.read()
    except FileNotFoundError:
        print("未找到 today_eng.html，无法继续处理。")
        exit(1)

# 创建解析器实例并传入翻译后的内容
parser = MyHTMLParser(translated_texts)

try:
    # 解析并替换文本
    parser.feed(html_content)

    # 如果新文本数量与原始链接数量相同，则写回文件
    if parser.current_index == len(translated_texts):
        # 定义原始和目标文件路径
        original_file_path = '/Users/yanzhang/Coding/News/today_all.html'
        process_eng_txt = '/Users/yanzhang/Coding/News/today_eng.txt'
        process_jpn_txt = '/Users/yanzhang/Coding/News/today_jpn.txt'
        result_eng_html = '/Users/yanzhang/Coding/News/today_eng.html'
        result_jpn_html = '/Users/yanzhang/Coding/News/today_jpn.html'
        
        try:
            with open(original_file_path, 'w', encoding='utf-8') as file:
                file.write(parser.result_html)
            print("文件已成功更新。")
            for file_to_delete in [file_path, process_eng_txt, process_jpn_txt, result_eng_html, result_jpn_html]:
                try:
                    os.remove(file_to_delete)
                except FileNotFoundError:
                    print(f"{file_to_delete} 文件不存在，跳过删除。")
            print("文件已成功删除。")
        except IOError as e:
            print(f"文件操作失败: {e}")

        # 设置TXT文件的保存路径
        now = datetime.now()
        time_str = now.strftime("%y%m%d")
        txt_file_name = f"TodayCNH_{time_str}.html"
        txt_directory = '/Users/yanzhang/Coding/News'
        txt_file_path = os.path.join(txt_directory, txt_file_name)

        # 重命名文件
        os.rename(original_file_path, txt_file_path)
        print(f"文件已重命名为：{txt_file_path}")

        # 调用函数，传入路径
        delete_done_txt_files("/tmp/")
    else:
        raise IndexError(f"翻译完的内容行数与原英文链接的数量不匹配，请检查。当前处理到第 {parser.current_index + 1} 个链接，但是新文本有 {len(translated_texts)} 行。")
        
except IndexError as e:
    # 打印错误信息
    print(e)
    # 初始化Tkinter窗口
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    applescript_code = f'display dialog "{str(e)}" buttons {{"OK"}} default button "OK"'
    subprocess.run(['osascript', '-e', applescript_code], check=True)
    root.destroy()

# 定义文件路径
wsj_file = '/Users/yanzhang/Coding/News/today_wsjcn.html'

if os.path.exists(wsj_file):
    try:
        # 读取两个文件的内容
        with open(wsj_file, 'r', encoding='utf-8') as f:
            wsj_html = f.read()

        with open(txt_file_path, 'r', encoding='utf-8') as f:
            today_cnh_html = f.read()

        # 使用BeautifulSoup解析HTML
        soup_wsj = BeautifulSoup(wsj_html, 'html.parser')
        soup_today_cnh = BeautifulSoup(today_cnh_html, 'html.parser')

        # 找到两个文件中的表格
        table_wsj = soup_wsj.find('table')
        table_today_cnh = soup_today_cnh.find('table')

        # 将wsj的表格内容加到today_cnh的表格末尾
        for row in table_wsj.find_all('tr')[1:]:  # 跳过表头
            table_today_cnh.append(row)

        # 将合并后的内容保存到一个新文件中
        with open(txt_file_path, 'w', encoding='utf-8') as f:
            f.write(str(soup_today_cnh))

        print(f"合并后的文件已保存为: {txt_file_path}")
        os.remove(wsj_file)
    except Exception as e:
        print(f"合并文件时发生错误: {e}")
else:
    print("未找到WSJ文件，继续执行其他操作。")

# 打开文件和调整大小
if os.path.exists(txt_file_path):
    webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)
    time.sleep(0.5)
    # 循环5次模拟按下Command + '='快捷键
    for _ in range(5):
        pyautogui.hotkey('command', '=')
        time.sleep(0.2)  # 在连续按键之间添加小延迟，以模拟自然按键速度
else:
    print("文件不存在，无法打开。")

time.sleep(1)  

try:
    # 打开 WSJ 主页
    webbrowser.open('https://www.wsj.com', new=2)
    print("已成功打开华尔街日报网站")
except Exception as e:
    print(f"打开华尔街日报网站时发生错误: {e}")