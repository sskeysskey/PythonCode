import os
import time
import pyautogui
import pyperclip
import webbrowser
import subprocess
import tkinter as tk
from datetime import datetime
from bs4 import BeautifulSoup
# from html.parser import HTMLParser # 不再需要

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

# ==============================================================================
# CSS 定义
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
/* 链接样式 */
a {
    color: #4a90e2;
    text-decoration: none;
}
a:hover, a:focus {
    text-decoration: none;
}
/* 新增：英文标题列样式，可以稍微灰色一点或小一点 */
td.title-eng {
    color: #666;
    font-size: 0.9em;
}
"""
# ==============================================================================

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

def get_clipboard_data():
    p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
    data, _ = p.communicate()
    return data.decode('utf-8').splitlines()

# --- 主逻辑 ---

# 文件路径
file_path = "/Users/yanzhang/Coding/News/today_chn.txt"

# 读取翻译后的中文内容
with open(file_path, 'r', encoding='utf-8') as file:
    lines = file.readlines()
    non_empty_lines = [line for line in lines if line.strip()]

content_to_copy = ''.join(non_empty_lines).rstrip('\n')
pyperclip.copy(content_to_copy)

translated_texts = get_clipboard_data()
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

# --- 核心修改部分 START: 使用 BeautifulSoup 替代 Parser ---
try:
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 找到所有目标链接 (target="_blank")
    target_links = [a for a in soup.find_all('a') if a.get('target') == '_blank']
    
    # 检查数量匹配
    if len(target_links) == len(translated_texts):
        
        # 1. 尝试添加表头 "Title_eng"
        table = soup.find('table')
        if table:
            thead = table.find('thead')
            if thead:
                # 如果有 thead，在第一行加列头
                header_row = thead.find('tr')
                if header_row:
                    new_th = soup.new_tag('th')
                    new_th.string = "Title_eng"
                    header_row.append(new_th)
            else:
                # 如果没有 thead，尝试找 tbody 的第一行（如果它看起来像表头）
                # 或者暂时忽略表头，只加数据列
                pass

        # 2. 遍历链接，进行替换并添加英文列
        for i, link in enumerate(target_links):
            # 获取原始英文标题 (去除首尾空白)
            eng_text = link.get_text(strip=True)
            
            # 获取对应的中文翻译
            chn_text = translated_texts[i]
            
            # 替换链接文本为中文
            link.string = chn_text
            
            # 找到父级 td 和 tr
            parent_td = link.find_parent('td')
            if parent_td:
                parent_tr = parent_td.find_parent('tr')
                
                if parent_tr:
                    # 创建新的 td 存放英文
                    new_td = soup.new_tag('td')
                    new_td.string = eng_text
                    new_td['class'] = 'title-eng' # 添加个class方便CSS控制
                    
                    # 将新 td 追加到行末
                    parent_tr.append(new_td)
        
        # --- 数据处理完成，开始保存文件 ---
        
        original_file_path = '/Users/yanzhang/Coding/News/today_all.html'
        process_eng_txt = '/Users/yanzhang/Coding/News/today_eng.txt'
        process_jpn_txt = '/Users/yanzhang/Coding/News/today_jpn.txt'
        result_eng_html = '/Users/yanzhang/Coding/News/today_eng.html'
        result_jpn_html = '/Users/yanzhang/Coding/News/today_jpn.html'

        # 更新原始文件 (覆盖)
        try:
            with open(original_file_path, 'w', encoding='utf-8') as file:
                file.write(str(soup))
            print("文件已成功更新。")
            
            # 删除中间文件
            for file_to_delete in [file_path, process_eng_txt, process_jpn_txt, result_eng_html, result_jpn_html]:
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
        txt_directory = '/Users/yanzhang/Coding/News'

        base_file_path = os.path.join(txt_directory, f"{base_filename}{file_extension}")

        # 检查是否合并到现有文件
        if os.path.exists(base_file_path):
            print(f"找到已存在的文件：{base_file_path}，将追加新内容。")
            with open(base_file_path, 'r', encoding='utf-8') as existing_file:
                existing_html = existing_file.read()
            
            existing_soup = BeautifulSoup(existing_html, 'html.parser')
            existing_table = existing_soup.find('table')
            
            # 这里 soup 是我们刚刚处理完带有英文列的新内容的 soup
            new_table = soup.find('table')
            
            if existing_table and new_table:
                # 将新表格的所有行（跳过表头）追加到已存在表格中
                for row in new_table.find_all('tr')[1:]: 
                    existing_table.append(row.extract())
                print(f"已将新内容追加到 {base_file_path}")
                
                with open(base_file_path, 'w', encoding='utf-8') as file:
                    file.write(str(existing_soup))
                txt_file_path = base_file_path
            else:
                # 无法合并，创建新文件
                txt_file_path = get_unique_filepath(txt_directory, base_filename, file_extension)
                with open(txt_file_path, 'w', encoding='utf-8') as file:
                    file.write(str(soup))
        else:
            # 创建新文件
            print(f"未找到已存在文件，将创建新文件：{base_file_path}")
            with open(base_file_path, 'w', encoding='utf-8') as file:
                file.write(str(soup))
            txt_file_path = base_file_path

        # 再次尝试删除临时文件 (冗余清理)
        for file_to_delete in [original_file_path, file_path, process_eng_txt, process_jpn_txt, result_eng_html, result_jpn_html]:
            try:
                os.remove(file_to_delete)
            except FileNotFoundError:
                pass
        
        delete_done_txt_files("/tmp/")

    else:
        # 如果数量不匹配，抛出异常
        raise IndexError(f"翻译完的内容行数与原英文链接的数量不匹配，请检查。当前HTML中有 {len(target_links)} 个链接，但是翻译文本有 {len(translated_texts)} 行。")

except IndexError as e:
    print(e)
    root = tk.Tk()
    root.withdraw()
    applescript_code = f'display dialog "{str(e)}" buttons {{"OK"}} default button "OK"'
    subprocess.run(['osascript', '-e', applescript_code], check=True)
    root.destroy()

# --- 核心修改部分 END ---

# 定义文件路径
wsj_file = '/Users/yanzhang/Coding/News/today_wsjcn.html'

if 'txt_file_path' in locals() and os.path.exists(txt_file_path):
    
    # --- 步骤 1: 处理 WSJ 文件合并 (如果存在) ---
    if os.path.exists(wsj_file):
        try:
            print(f"找到WSJ文件 {wsj_file}，准备合并。")
            with open(wsj_file, 'r', encoding='utf-8') as f_wsj:
                wsj_html_content = f_wsj.read()
            
            with open(txt_file_path, 'r', encoding='utf-8') as f_cnh:
                today_cnh_html_content = f_cnh.read()
            
            soup_wsj_base = BeautifulSoup(wsj_html_content, 'html.parser')
            soup_today_cnh_to_merge = BeautifulSoup(today_cnh_html_content, 'html.parser')
            
            table_in_wsj = soup_wsj_base.find('table')
            table_in_cnh = soup_today_cnh_to_merge.find('table')
            
            if table_in_wsj and table_in_cnh:
                # 注意：如果 WSJ 文件原本只有2列，而 CNH 现在有3列，合并后表格可能不对齐。
                # 但这通常是浏览器渲染问题，数据会保留。
                for row in table_in_cnh.find_all('tr')[1:]: 
                    table_in_wsj.append(row.extract()) 
                print("CNH表格内容已合并到WSJ表格。")
            
            with open(txt_file_path, 'w', encoding='utf-8') as f_out:
                f_out.write(str(soup_wsj_base))
            
            try:
                os.remove(wsj_file)
            except OSError:
                pass
        except Exception as e_wsj:
            print(f"处理WSJ文件出错: {e_wsj}")

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
    webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)
    time.sleep(0.5)
    try:
        for _ in range(4):
            pyautogui.hotkey('command', '=')
            time.sleep(0.2) 
    except Exception:
        pass
