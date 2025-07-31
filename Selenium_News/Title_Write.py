import os
import time
import pyautogui
import pyperclip
import webbrowser
import subprocess
import tkinter as tk
from datetime import datetime
from bs4 import BeautifulSoup
from html.parser import HTMLParser

def add_css_to_soup(soup, css_string):
    """将CSS字符串添加到BeautifulSoup对象的<head>中"""
    if not soup.head:
        head_tag = soup.new_tag("head")
        if soup.html: # 检查是否存在<html>标签
            soup.html.insert(0, head_tag)
        else: # 如果没有<html>标签，直接在soup对象顶部插入<head>
            soup.insert(0, head_tag)
    else:
        head_tag = soup.head
    
    # 可选：检查是否已存在相同的 style 标签以避免重复添加
    # for style in head_tag.find_all("style"):
    #     if style.string and style.string.strip() == css_string.strip():
    #         print("CSS样式已存在，跳过添加。")
    #         return

    style_tag = soup.new_tag("style")
    style_tag.string = css_string
    head_tag.append(style_tag)

# <--- 新增的函数 START --->
def get_unique_filepath(directory, basename, extension):
    """
    生成一个唯一的文件路径。如果基础路径已存在，则在文件名后附加 (1), (2), ...

    :param directory: 文件所在的目录
    :param basename: 不带扩展名的文件名 (例如 "TodayCNH_240617")
    :param extension: 文件扩展名 (例如 ".html")
    :return: 一个唯一的完整文件路径
    """
    # 初始文件路径
    filepath = os.path.join(directory, f"{basename}{extension}")
    counter = 1

    # 循环检查文件是否存在，如果存在则附加计数器
    while os.path.exists(filepath):
        # 创建新的文件名，例如 "TodayCNH_240617(1).html"
        new_basename = f"{basename}({counter})"
        filepath = os.path.join(directory, f"{new_basename}{extension}")
        counter += 1
    
    return filepath
# <--- 新增的函数 END --->

# ==============================================================================
# 请将您的CSS字符串定义移到这里或脚本的其他全局位置
# 例如:
css = """
/* 全局字体和背景 */
body {
    font-size: 18px;
    /* 或者 1.125rem */
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #333;
    background: #f9f9f9;
    margin: 0;
    padding: 1rem;
    line-height: 1.6;
}

/* 容器居中 */
.container {
    max-width: 960px;
    margin: 0 auto;
    background: #fff;
    padding: 1.5rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    border-radius: 4px;
}

/* 美化表格 */
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
}

th,
td {
    padding: .75rem .5rem;
    border: 1px solid #ddd;
    text-align: left;
}

thead th {
    background: #4a90e2;
    color: #fff;
    text-transform: uppercase;
    font-size: .875rem;
}

tbody tr:nth-child(even) {
    background: #f2f2f2;
}

tbody tr:hover {
    background: #e6f7ff;
}

/* 去掉所有链接默认下划线，hover 时加下划线提示 */
a {
    color: #4a90e2;
    /* 保持和表头一样的主题色，也可根据需要改色 */
    text-decoration: none;
    /* 取消下划线 */
}

a:hover,
a:focus {
    text-decoration: none;
    /* 取消下划线 */
}
"""
# ==============================================================================

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
        
        # 使用BeautifulSoup修改HTML结构，添加<head>内容
        soup = BeautifulSoup(parser.result_html, 'html.parser')
        
        try:
            with open(original_file_path, 'w', encoding='utf-8') as file:
                file.write(str(soup))
            print("文件已成功更新。")
            for file_to_delete in [file_path, process_eng_txt, process_jpn_txt, result_eng_html, result_jpn_html]:
                try:
                    os.remove(file_to_delete)
                except FileNotFoundError:
                    print(f"{file_to_delete} 文件不存在，跳过删除。")
            print("文件已成功删除。")
        except IOError as e:
            print(f"文件操作失败: {e}")

        # <--- 修改的部分 START --->
        # 设置文件的保存路径和名称
        now = datetime.now()
        time_str = now.strftime("%y%m%d")
        # 基础文件名，不含扩展名
        base_filename = f"TodayCNH_{time_str}"
        # 文件扩展名
        file_extension = ".html"
        # 目标目录
        txt_directory = '/Users/yanzhang/Coding/News'

        # 调用新函数来获取一个唯一的文件路径
        txt_file_path = get_unique_filepath(txt_directory, base_filename, file_extension)

        # 重命名文件
        os.rename(original_file_path, txt_file_path)
        print(f"文件已重命名为：{txt_file_path}")
        # <--- 修改的部分 END --->

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

# 确保 txt_file_path 变量已定义并且对应的文件存在
if 'txt_file_path' in locals() and os.path.exists(txt_file_path):
    
    # --- 步骤 1: 处理 WSJ 文件合并 (如果存在) ---
    if os.path.exists(wsj_file):
        try:
            print(f"找到WSJ文件 {wsj_file}，准备合并。")
            with open(wsj_file, 'r', encoding='utf-8') as f_wsj:
                wsj_html_content = f_wsj.read()
            
            # 读取 txt_file_path 的当前内容 (即 TodayCNH_{time_str}.html)
            with open(txt_file_path, 'r', encoding='utf-8') as f_cnh:
                today_cnh_html_content = f_cnh.read()

            # 解析两个HTML内容
            soup_wsj_base = BeautifulSoup(wsj_html_content, 'html.parser')
            soup_today_cnh_to_merge = BeautifulSoup(today_cnh_html_content, 'html.parser')

            # 找到各自的表格
            table_in_wsj = soup_wsj_base.find('table')
            table_in_cnh = soup_today_cnh_to_merge.find('table')

            if table_in_wsj and table_in_cnh:
                # 将 CNH 表格的行 (除了表头) 追加到 WSJ 表格
                # 使用 .extract() 可以确保移动节点而不是复制，如果源soup不再需要这些行
                for row in table_in_cnh.find_all('tr')[1:]: 
                    table_in_wsj.append(row.extract()) 
                print("CNH表格内容已合并到WSJ表格。")
            else:
                missing_tables_info = []
                if not table_in_wsj: missing_tables_info.append("WSJ文件中的表格")
                if not table_in_cnh: missing_tables_info.append("CNH文件中的表格（用于合并）")
                print(f"警告：未能找到 { ' 和 '.join(missing_tables_info) }。表格合并步骤已跳过。")
            
            # 将修改后的 WSJ 内容 (可能已合并 CNH 表格) 写回 txt_file_path，覆盖它
            # 此时还未添加全局CSS
            with open(txt_file_path, 'w', encoding='utf-8') as f_out:
                f_out.write(str(soup_wsj_base))
            print(f"WSJ相关内容已处理并保存到 {txt_file_path}。")
            
            # 删除原始WSJ文件
            try:
                os.remove(wsj_file)
                print(f"已删除原始WSJ文件：{wsj_file}")
            except OSError as e_remove:
                print(f"删除WSJ文件 {wsj_file} 失败: {e_remove}")

        except Exception as e_wsj:
            print(f"处理WSJ文件 {wsj_file} 时发生错误: {e_wsj}")
            print(f"{txt_file_path} 将保留其在WSJ处理前的内容。")
            # 如果WSJ处理失败，txt_file_path 仍然包含原始的CNH内容。
            # CSS将在下一步添加到这个内容中。
    else:
        print(f"WSJ文件 {wsj_file} 未找到。将直接对 {txt_file_path} 的现有内容添加CSS。")

    # --- 步骤 2: 向 txt_file_path 的当前内容添加 CSS ---
    # 此时, txt_file_path 包含:
    #   a) 原始的 CNH 内容 (如果 wsj_file 不存在, 或合并失败且未覆盖 txt_file_path)
    #   b) WSJ 的内容 (可能合并了 CNH 表格) (如果 wsj_file 存在且处理成功覆盖了 txt_file_path)
    try:
        print(f"准备为文件 {txt_file_path} 添加CSS样式。")
        with open(txt_file_path, 'r', encoding='utf-8') as f_current_html:
            html_content_for_css = f_current_html.read()
        
        soup_for_final_css = BeautifulSoup(html_content_for_css, 'html.parser')
        
        # 使用之前定义的 add_css_to_soup 函数和 css 字符串
        add_css_to_soup(soup_for_final_css, css) # 此函数会修改 soup_for_final_css 对象

        # 将添加了CSS的最终HTML写回文件
        with open(txt_file_path, 'w', encoding='utf-8') as f_final_output:
            f_final_output.write(str(soup_for_final_css))
        print(f"CSS样式已成功添加到 {txt_file_path}。")

    except FileNotFoundError:
        # 这个错误理论上不应该发生，因为我们在外部的if条件中已经检查过 txt_file_path 的存在
        print(f"严重错误：在尝试添加CSS之前，文件 {txt_file_path} 未找到。")
    except Exception as e_css_addition:
        print(f"为 {txt_file_path} 添加CSS时发生错误: {e_css_addition}。文件可能未更新CSS。")

else:
    # 如果 txt_file_path 变量未定义，或者定义了但文件在之前的步骤中未能成功创建
    if 'txt_file_path' in locals():
        print(f"错误：主要HTML文件 {txt_file_path} 在处理流程后不存在。无法进行WSJ合并或CSS添加。")
    else:
        print("错误：主要HTML文件路径 (txt_file_path) 未定义。通常表示初始HTML生成步骤失败。无法进行后续处理。")

# --- 后续操作：打开文件和调整大小 ---
if 'txt_file_path' in locals() and os.path.exists(txt_file_path):
    print(f"准备在浏览器中打开文件: {txt_file_path}")
    webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)
    time.sleep(0.5) # 给浏览器一点时间加载
    try:
        # 循环几次模拟按下Command + '='快捷键来放大页面
        for _ in range(4): #原代码是4次
            pyautogui.hotkey('command', '=')
            time.sleep(0.2) 
        print("已尝试放大浏览器页面。")
    except Exception as e_pyautogui:
        print(f"使用pyautogui控制浏览器缩放时出错: {e_pyautogui}")
        print("请确保您的环境允许pyautogui控制应用程序，并且目标浏览器窗口是激活的。")
else:
    print("最终HTML文件不存在或路径未定义，无法在浏览器中打开。")