import os
import re
import time
import pyautogui
import pyperclip
import webbrowser
import subprocess
import tkinter as tk
from tkinter import messagebox # Windows 下需要用到
from datetime import datetime
from bs4 import BeautifulSoup
import sys
import tempfile 

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础 Coding 目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 具体文件路径
NEWS_DIR = os.path.join(BASE_CODING_DIR, "News")
WEBSITE_NEWS_DIR = os.path.join(BASE_CODING_DIR, "Website", "news")

# 4. 临时目录
if os.name == 'nt':
    TEMP_DIR = tempfile.gettempdir()
else:
    TEMP_DIR = "/tmp"

# 具体文件路径
TODAY_CHN_TXT = os.path.join(NEWS_DIR, "today_chn.txt")
TODAY_ALL_HTML = os.path.join(NEWS_DIR, "today_all.html")
TODAY_ENG_HTML = os.path.join(NEWS_DIR, "today_eng.html")
TODAY_WSJ_HTML = os.path.join(NEWS_DIR, "today_wsjcn.html")
TODAY_DW_HTML = os.path.join(NEWS_DIR, "today_dwcn.html")
TODAY_RFI_HTML = os.path.join(NEWS_DIR, "today_rficn.html")
TODAY_BBC_HTML = os.path.join(NEWS_DIR, "today_bbccn.html")

# 临时中间文件
PROCESS_ENG_TXT = os.path.join(NEWS_DIR, "today_eng.txt")
PROCESS_JPN_TXT = os.path.join(NEWS_DIR, "today_jpn.txt")
RESULT_ENG_HTML = os.path.join(NEWS_DIR, "today_eng.html")
RESULT_JPN_HTML = os.path.join(NEWS_DIR, "today_jpn.html")

# ========================================================

def add_css_to_soup(soup, css_string):
    """将CSS字符串添加到BeautifulSoup对象的<head>中"""
    if not soup.head:
        head_tag = soup.new_tag("head")
        if soup.html: 
            soup.html.insert(0, head_tag)
        else: 
            soup.insert(0, head_tag)
    else:
        head_tag = soup.head
    
    style_tag = soup.new_tag("style")
    style_tag.string = css_string
    head_tag.append(style_tag)

def get_unique_filepath(directory, basename, extension):
    """生成一个唯一的文件路径"""
    filepath = os.path.join(directory, f"{basename}{extension}")
    counter = 1
    while os.path.exists(filepath):
        new_basename = f"{basename}({counter})"
        filepath = os.path.join(directory, f"{new_basename}{extension}")
        counter += 1
    return filepath

# ================= CSS 定义 =================
css = """
/* 全局字体和背景 */
body {
    font-size: 18px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #333;
    background: #f9f9f9;
    margin: 0;
    padding: 1rem;
    line-height: 1.6;
}
.container {
    max-width: 960px;
    margin: 0 auto;
    background: #fff;
    padding: 1.5rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    border-radius: 4px;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
}
th, td {
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
a {
    color: #4a90e2;
    text-decoration: none;
}
a:hover, a:focus {
    text-decoration: none;
}
td.title-eng {
    color: #666;
    font-size: 0.9em;
}
"""
# ============================================

def delete_done_txt_files(directory):
    if not os.path.exists(directory):
        return
    try:
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if filename.startswith("done_") and filename.endswith(".txt"):
                os.remove(filepath)
                print(f"已删除文件：{filename}")
    except Exception as e:
        print(f"在删除文件时发生错误：{e}")

def get_clipboard_data_list():
    """
    使用 pyperclip 替代 pbpaste，兼容 Windows
    """
    data = pyperclip.paste()
    if not data:
        return []
    return data.splitlines()

# --- 主逻辑 ---

# ============ 新增：纯中文模式检测 ============
# CHINESE_ONLY_MODE = False
# if (not os.path.exists(TODAY_CHN_TXT)
#     and not os.path.exists(TODAY_ALL_HTML)
#     and not os.path.exists(TODAY_ENG_HTML)):
#     chinese_candidates = [TODAY_WSJ_HTML, TODAY_DW_HTML, TODAY_RFI_HTML, TODAY_BBC_HTML]
#     if any(os.path.exists(f) for f in chinese_candidates):
#         CHINESE_ONLY_MODE = True
#         print("⚠️ 未检测到英文/翻译文件，进入纯中文合并模式。")

# if CHINESE_ONLY_MODE:
#     # 构造一个最小 HTML 框架（有 thead/tbody，方便后面 CSS 样式生效）
#     minimal_html = """<!DOCTYPE html>
# <html>
# <head><meta charset="utf-8"><title>Today News</title></head>
# <body>
# <div class="container">
# <table>
# <thead><tr><th>Site</th><th>Title</th></tr></thead>
# <tbody></tbody>
# </table>
# </div>
# </body>
# </html>"""
#     soup_init = BeautifulSoup(minimal_html, 'html.parser')

#     now = datetime.now()
#     time_str = now.strftime("%y%m%d")
#     base_filename = f"TodayCNH_{time_str}"
#     base_file_path = os.path.join(NEWS_DIR, f"{base_filename}.html")

#     # 若今天已存在目标文件，就直接复用（让后续合并逻辑追加新内容）
#     if not os.path.exists(base_file_path):
#         with open(base_file_path, 'w', encoding='utf-8') as f:
#             f.write(str(soup_init))
#         print(f"已创建空白主文件：{base_file_path}")
#     else:
#         print(f"复用已存在的主文件：{base_file_path}")

#     txt_file_path = base_file_path  # 交给下面的中文合并逻辑处理

# else:

# 1. 读取翻译后的中文内容
if not os.path.exists(TODAY_CHN_TXT):
    print(f"错误：未找到文件 {TODAY_CHN_TXT}")
    sys.exit(1)

with open(TODAY_CHN_TXT, 'r', encoding='utf-8') as file:
    lines = file.readlines()
    non_empty_lines = [line for line in lines if line.strip()]

content_to_copy = ''.join(non_empty_lines).rstrip('\n')
pyperclip.copy(content_to_copy)

# 获取剪贴板内容
translated_texts = get_clipboard_data_list()
translated_texts = [line for line in translated_texts if line.strip() != '']

# 2. 读取HTML文件内容
try:
    with open(TODAY_ALL_HTML, 'r', encoding='utf-8') as file:
        html_content = file.read()
except FileNotFoundError:
    try:
        print(f"未找到 {os.path.basename(TODAY_ALL_HTML)}，尝试打开 {os.path.basename(TODAY_ENG_HTML)}")
        with open(TODAY_ENG_HTML, 'r', encoding='utf-8') as file:
            html_content = file.read()
    except FileNotFoundError:
        print(f"未找到 {os.path.basename(TODAY_ENG_HTML)}，无法继续处理。")
        sys.exit(1)

# --- 核心修改部分 START ---
try:
    soup = BeautifulSoup(html_content, 'html.parser')
    target_links = [a for a in soup.find_all('a') if a.get('target') == '_blank']
    
    # 检查数量匹配
    if len(target_links) == len(translated_texts):
        
        # 1. 添加表头
        table = soup.find('table')
        if table:
            thead = table.find('thead')
            if thead:
                header_row = thead.find('tr')
                if header_row:
                    new_th = soup.new_tag('th')
                    new_th.string = "Title_eng"
                    header_row.append(new_th)

        # 2. 遍历链接替换
        for i, link in enumerate(target_links):
            eng_text = link.get_text(strip=True)
            chn_text = translated_texts[i]
            chn_text = re.sub(r'^\d+[、.。\s：:\)）]+\s*', '', chn_text)
            
            link.string = chn_text
            
            parent_td = link.find_parent('td')
            if parent_td:
                parent_tr = parent_td.find_parent('tr')
                if parent_tr:
                    new_td = soup.new_tag('td')
                    new_td.string = eng_text
                    new_td['class'] = 'title-eng'
                    parent_tr.append(new_td)
        
        # --- 保存文件 ---
        try:
            with open(TODAY_ALL_HTML, 'w', encoding='utf-8') as file:
                file.write(str(soup))
            print("文件已成功更新。")
            
            temp_files_to_delete = [TODAY_CHN_TXT, PROCESS_ENG_TXT, PROCESS_JPN_TXT, RESULT_ENG_HTML, RESULT_JPN_HTML]
            for file_to_delete in temp_files_to_delete:
                try:
                    os.remove(file_to_delete)
                except FileNotFoundError:
                    pass
            print("临时文件已成功删除。")
        except IOError as e:
            print(f"文件操作失败: {e}")

        # 生成带时间戳的最终文件
        now = datetime.now()
        time_str = now.strftime("%y%m%d")
        base_filename = f"TodayCNH_{time_str}"
        file_extension = ".html"
        
        base_file_path = os.path.join(NEWS_DIR, f"{base_filename}{file_extension}")
        
        # 检查是否合并
        if os.path.exists(base_file_path):
            print(f"找到已存在的文件：{base_file_path}，将追加新内容。")
            with open(base_file_path, 'r', encoding='utf-8') as existing_file:
                existing_html = existing_file.read()
            
            existing_soup = BeautifulSoup(existing_html, 'html.parser')
            existing_table = existing_soup.find('table')
            new_table = soup.find('table')
            
            if existing_table and new_table:
                rows_to_append = new_table.find_all('tr')[1:]
                if not rows_to_append:
                     rows_to_append = new_table.find_all('tr')

                for row in rows_to_append: 
                    existing_table.append(row.extract())

                print(f"已将新内容追加到 {base_file_path}")
                with open(base_file_path, 'w', encoding='utf-8') as file:
                    file.write(str(existing_soup))
                txt_file_path = base_file_path
            else:
                txt_file_path = get_unique_filepath(NEWS_DIR, base_filename, file_extension)
                with open(txt_file_path, 'w', encoding='utf-8') as file:
                    file.write(str(soup))
        else:
            print(f"未找到已存在文件，将创建新文件：{base_file_path}")
            with open(base_file_path, 'w', encoding='utf-8') as file:
                file.write(str(soup))
            txt_file_path = base_file_path

        # 删除临时文件
        for file_to_delete in [TODAY_ALL_HTML, TODAY_CHN_TXT, PROCESS_ENG_TXT, PROCESS_JPN_TXT, RESULT_ENG_HTML, RESULT_JPN_HTML]:
            try:
                os.remove(file_to_delete)
            except FileNotFoundError:
                pass
        
        delete_done_txt_files(TEMP_DIR)

    else:
        raise IndexError(f"翻译完的内容行数与原英文链接的数量不匹配，请检查。当前HTML中有 {len(target_links)} 个链接，但是翻译文本有 {len(translated_texts)} 行。")

except IndexError as e:
    print(e)
    # <--- 这里恢复了原有的逻辑，但加了平台判断以兼容 Windows --->
    root = tk.Tk()
    root.withdraw()
    
    if sys.platform == 'darwin':
        # 在 macOS 上保持您喜欢的原生 AppleScript 弹窗
        try:
            applescript_code = f'display dialog "{str(e)}" buttons {{"OK"}} default button "OK"'
            subprocess.run(['osascript', '-e', applescript_code], check=True)
        except Exception:
            # 万一 AppleScript 失败，回退到 Tkinter
            messagebox.showerror("错误", str(e))
    else:
        # 在 Windows/Linux 上使用 Tkinter 弹窗，防止报错
        messagebox.showerror("错误", str(e))
        
    root.destroy()

# --- 核心修改部分 END ---

if 'txt_file_path' in locals() and os.path.exists(txt_file_path):
    # --- 步骤 1: 处理中文文件合并 (WSJ, DW, RFI) ---
    # 定义需要合并的中文文件列表，按你希望的显示顺序排列
    chinese_news_files = [TODAY_WSJ_HTML, TODAY_DW_HTML, TODAY_RFI_HTML, TODAY_BBC_HTML]
    
    # 读取主文件（刚才生成的包含英文翻译的文件）
    try:
        # 读取主文件 (此时包含已翻译的英文内容)
        with open(txt_file_path, 'r', encoding='utf-8') as f_main:
            main_html_content = f_main.read()
        
        soup_main = BeautifulSoup(main_html_content, 'html.parser')
        table_main = soup_main.find('table')

        if table_main:
            # === A. 拆解英文表格 ===
            # 获取所有行
            all_eng_rows = table_main.find_all('tr')
            header_row = None
            eng_content_rows = []

            if all_eng_rows:
                # 尝试找到表头行
                # 逻辑：如果某一行包含 th，那它就是表头
                header_candidate = all_eng_rows[0]
                if header_candidate.find('th'):
                    header_row = header_candidate.extract()
                    # 剩下的行是内容
                    eng_content_rows = [row.extract() for row in all_eng_rows[1:]]
                else:
                    # 没有表头的情况
                    eng_content_rows = [row.extract() for row in all_eng_rows]
            
            # === B. 收集中文行 ===
            chinese_content_rows = []
            files_merged = False
            
            # 遍历每一个中文文件
            for cn_file_path in chinese_news_files:
                if os.path.exists(cn_file_path):
                    try:
                        print(f"读取并合并中文文件: {os.path.basename(cn_file_path)}")
                        with open(cn_file_path, 'r', encoding='utf-8') as f_cn:
                            cn_html_content = f_cn.read()
                        
                        soup_cn = BeautifulSoup(cn_html_content, 'html.parser')
                        table_cn = soup_cn.find('table')
                        
                        if table_cn:
                            cn_rows = table_cn.find_all('tr')
                            # 跳过中文文件的表头 (通常第一行是 site, title)
                            start_idx = 0
                            if cn_rows and cn_rows[0].find('th'):
                                start_idx = 1
                            
                            # 提取内容行
                            for row in cn_rows[start_idx:]:
                                chinese_content_rows.append(row.extract())
                            
                            files_merged = True
                            
                            # 合并后删除源文件
                            try:
                                os.remove(cn_file_path)
                            except OSError:
                                pass
                    except Exception as e_merge:
                        print(f"处理文件 {os.path.basename(cn_file_path)} 时出错: {e_merge}")

            # === C. 重组表格 (完美保留 CSS 结构) ===
            table_main.clear() # 清空旧结构
            
            # 1. 重建 thead (确保表头样式生效)
            if header_row:
                new_thead = soup_main.new_tag('thead')
                new_thead.append(header_row)
                table_main.append(new_thead)
            
            # 2. 重建 tbody (确保隔行变色样式生效)
            new_tbody = soup_main.new_tag('tbody')
            
            # 先加中文
            for row in chinese_content_rows:
                new_tbody.append(row)
            # 后加英文
            for row in eng_content_rows:
                new_tbody.append(row)
                
            table_main.append(new_tbody)
            
            # 写入文件
            if files_merged or header_row:
                with open(txt_file_path, 'w', encoding='utf-8') as f_out:
                    f_out.write(str(soup_main))
                print("表格已成功重组，并保留了 thead/tbody 结构。")

        else:
            print("主文件中未找到表格，跳过合并。")

    except Exception as e_main_process:
        print(f"合并重组流程出错: {e_main_process}")

    # --- 步骤 2: 添加 CSS ---
    try:
        with open(txt_file_path, 'r', encoding='utf-8') as f_current_html:
            html_content_for_css = f_current_html.read()
        
        soup_for_final_css = BeautifulSoup(html_content_for_css, 'html.parser')
        add_css_to_soup(soup_for_final_css, css)
        
        with open(txt_file_path, 'w', encoding='utf-8') as f_final_output:
            f_final_output.write(str(soup_for_final_css))
        print(f"CSS样式已成功添加到 {txt_file_path}。")
    except Exception as e:
        print(f"CSS添加错误: {e}")

else:
    print("错误：主要HTML文件路径未定义，流程失败。")

# --- 后续操作：打开文件 ---
if 'txt_file_path' in locals() and os.path.exists(txt_file_path):
    print(f"准备在浏览器中打开文件: {txt_file_path}")
    
    real_path = os.path.realpath(txt_file_path)
    if os.name == 'nt':
        url = 'file:///' + real_path.replace('\\', '/')
    else:
        url = 'file://' + real_path
        
    webbrowser.open(url, new=2)
    time.sleep(0.5)

    try:
        modifier = 'command' if sys.platform == 'darwin' else 'ctrl'
        for _ in range(4):
            pyautogui.hotkey(modifier, '=')
            time.sleep(0.2) 
    except Exception:
        pass
