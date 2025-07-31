import os
import cv2
import time
import glob
import subprocess
import webbrowser
import pyautogui
import numpy as np
from datetime import datetime, timedelta
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from PIL import ImageGrab

def capture_screen():
    """
    使用PIL的ImageGrab直接截取屏幕，并转换为OpenCV格式
    """
    screenshot = ImageGrab.grab()
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

def find_image_on_screen(template, threshold=0.9):
    """
    在当前屏幕中查找给定模板图像的匹配位置（精度默认0.9）。
    如果找到，则返回 (top_left坐标, 模板形状)，否则返回 (None, None)。
    """
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    # 释放截图及相关资源
    del screen
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None

def is_similar(url1, url2):
    """
    比较两个URL是否只在参数不同或其他细微处不同，
    通过比较URL的scheme、netloc和path判定是否相似。
    """
    parsed_url1, parsed_url2 = urlparse(url1), urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def get_old_content(file_path, days_ago):
    """
    读取旧的HTML文件，获取指定天数内的数据（基于<tr><td>结构）。
    """
    old_content = []
    if not os.path.exists(file_path):
        return old_content

    cutoff_date = datetime.now() - timedelta(days=days_ago)
    with open(file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file, 'html.parser')
        for row in soup.find_all('tr')[1:]:  # 跳过表头
            cols = row.find_all('td')
            if len(cols) < 2:
                continue
            date_str, title = cols[0].text.strip(), cols[1].text.strip()
            link = cols[1].find('a')['href'] if cols[1].find('a') else ''
            date = datetime.strptime(date_str, '%Y_%m_%d_%H')
            if date >= cutoff_date:
                old_content.append([date_str, title, link])
    return old_content

def get_new_content_from_files(file_prefix):
    """
    读取Downloads目录下以指定前缀开头的HTML文件内容
    """
    new_content = []
    download_dir = "/Users/yanzhang/Downloads/"
    files = glob.glob(os.path.join(download_dir, f"{file_prefix}_*.html"))
    
    current_datetime = datetime.now().strftime("%Y_%m_%d_%H")
    
    for file_path in files:
        with open(file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            for row in soup.find_all('tr')[1:]:  # 跳过表头
                cols = row.find_all('td')
                if len(cols) < 2:
                    continue
                date_str = cols[0].text.strip() if len(cols) > 0 else current_datetime
                title = cols[1].text.strip() if len(cols) > 1 else ""
                link = cols[1].find('a')['href'] if cols[1].find('a') else ''
                if title and link:
                    new_content.append([date_str, title, link])
    return new_content

def write_html(file_path, new_rows, old_content):
    """
    将新的抓取结果与旧内容写入同一个HTML文件，包含表格结构，
    并进行完整性校验。
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n<tr><th>Date</th><th>Title</th></tr>\n")
            for row in new_rows + old_content:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
            html_file.write("</table></body></html>")
            html_file.flush()
            os.fsync(html_file.fileno())

        # 验证完整性
        with open(file_path, 'r', encoding='utf-8') as verify_file:
            content = verify_file.read()
            if not content.endswith("</table></body></html>"):
                raise IOError("File writing verification failed")
    except Exception as e:
        print(f"Error writing to file: {e}")
        raise

def append_to_today_html(today_html_path, new_rows1):
    """
    将新增的抓取结果追加到today_eng.html文件末尾，并进行文件完整性校验
    使用完整读取-修改-写入的安全方式，并添加错误处理和文件完整性验证。
    """
    try:
        # 准备追加的内容
        append_content = ""
        for row in new_rows1:
            # 确保每一行标签完整闭合
            append_content += f"<tr><td>{row[0]}</td><td><a href='{row[2]}' target='_blank'>{row[1]}</a></td></tr>\n"
        
        closing_tag = "</table></body></html>"
        
        # 如果文件存在，则读取旧内容，去掉结束标签后重写文件
        if os.path.exists(today_html_path):
            with open(today_html_path, 'r', encoding='utf-8') as html_file:
                content = html_file.read()
            # 去除原有的关闭标签，避免重复写入
            if closing_tag in content:
                content = content.replace(closing_tag, "")
            content += append_content + closing_tag
            
            with open(today_html_path, 'w', encoding='utf-8') as html_file:
                html_file.write(content)
                html_file.flush()
                os.fsync(html_file.fileno())
        else:
            # 如果文件不存在，则构造新的 HTML 文件
            with open(today_html_path, 'w', encoding='utf-8') as html_file:
                html_file.write("<html><body><table border='1'>\n<tr><th>Date</th><th>Title</th></tr>\n")
                html_file.write(append_content + closing_tag)
                html_file.flush()
                os.fsync(html_file.fileno())

        # 验证文件完整性
        with open(today_html_path, 'r', encoding='utf-8') as verify_file:
            content = verify_file.read()
            if not content.endswith(closing_tag):
                raise IOError("File writing verification failed")
                
    except Exception as e:
        print(f"Error writing to file: {e}")
        raise

def count_files(prefix):
    """
    计算Downloads目录中指定前缀开头的文件数量
    """
    download_dir = "/Users/yanzhang/Downloads/"
    files = glob.glob(os.path.join(download_dir, f"{prefix}_*.html"))
    return len(files)

def clean_files(prefix):
    """
    清理Downloads目录中指定前缀开头的文件
    同时清理相关的其他前缀文件（如wsj_和cnwsj_）
    """
    download_dir = "/Users/yanzhang/Downloads/"
    prefixes = [prefix + '_']
    
    # 为特定前缀添加相关的其他前缀
    if prefix == "wsj":
        prefixes.append("cnwsj_")
    elif prefix == "bloomberg":
        prefixes.append("cnbloomberg_")
    
    for current_prefix in prefixes:
        existing_files = glob.glob(os.path.join(download_dir, f"{current_prefix}*.html"))
        for file in existing_files:
            try:
                os.remove(file)
                print(f"Removed existing file: {file}")
            except Exception as e:
                print(f"Error removing file {file}: {e}")

def open_webpage_and_monitor_bloomberg():
    """
    打开Bloomberg页面并监控下载文件
    """
    # 清理已存在的bloomberg文件
    clean_files("bloomberg")
    
    # 打开第一个页面
    print("Opening Bloomberg main page...")
    webbrowser.open("https://www.bloomberg.com/asia")
    
    # 等待第一个文件下载
    print("Waiting for first file download...")
    while count_files("bloomberg") < 1:
        time.sleep(2)
        print(".", end="", flush=True)
    
    print("\nFirst file detected!")
    
    # 打开第二个页面
    print("Opening Bloomberg Asia page...")
    template_paths = {
        "asia": "/Users/yanzhang/Coding/python_code/Resource/scraper_asia.png",
        "us": "/Users/yanzhang/Coding/python_code/Resource/scraper_us.png"
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {path}")
        templates[key] = template

    # 第一阶段：在 10 秒内尝试找到 asia 图片
    found_asia_image = False
    timeout_stop = time.time() + 10
    while not found_asia_image and time.time() < timeout_stop:
        location_asia, shape_asia = find_image_on_screen(templates["asia"])
        if location_asia:
            center_x = (location_asia[0] + shape_asia[1] // 2) // 2
            center_y = (location_asia[1] + shape_asia[0] // 2) // 2
            pyautogui.click(center_x, center_y)
            found_asia_image = True
            print(f"找到asia图片位置: {location_asia}")
        else:
            print("未找到asia图片，继续监控...")
            time.sleep(1)
    
    time.sleep(1)
    location_us, shape_us = find_image_on_screen(templates["us"])
    if location_us:
        center_x = (location_us[0] + shape_us[1] // 2) // 2
        center_y = (location_us[1] + shape_us[0] // 2) // 2
        pyautogui.click(center_x, center_y)
    
    # 等待第二个文件下载
    print("Waiting for second file download...")
    while count_files("bloomberg") < 2:
        time.sleep(2)
        print(".", end="", flush=True)
    
    print("\nSecond file detected!")
    print("All Bloomberg files downloaded. Processing...")
    
    # 关闭页面
    close_browser_tabs(1)

def open_webpage_and_monitor_wsj():
    """
    打开WSJ页面并监控下载文件
    """
    # 清理已存在的wsj文件
    clean_files("wsj")
    
    # 打开WSJ页面
    print("Opening WSJ main page...")
    pyautogui.moveTo(591, 574)
    webbrowser.open("https://www.wsj.com/")
    for i in range(5):
        pyautogui.scroll(-80)
        time.sleep(0.5)
    
    # 等待文件下载
    print("Waiting for WSJ file download...")
    while count_files("wsj") < 1:
        time.sleep(2)
        print(".", end="", flush=True)
    
    print("\nWSJ file detected!")
    print("WSJ file downloaded. Processing...")
    
    # 关闭页面
    close_browser_tabs(1)

def open_webpage_and_monitor_reuters():
    """
    打开reuters页面并监控下载文件
    """
    # 清理已存在的wsj文件
    clean_files("reuters")
    
    # 打开WSJ页面
    print("Opening reuters main page...")
    pyautogui.moveTo(591, 574)
    webbrowser.open("https://www.reuters.com/")
    for i in range(5):
        pyautogui.scroll(-80)
        time.sleep(0.5)
    
    # 等待文件下载
    print("Waiting for reuters file download...")
    while count_files("reuters") < 1:
        time.sleep(2)
        print(".", end="", flush=True)
    
    print("\nreuters file detected!")
    print("reuters file downloaded. Processing...")
    close_browser_tabs(1)

# 新增 FT 的监控函数
def open_webpage_and_monitor_ft():
    """
    打开FT页面并监控下载文件
    """
    # 清理已存在的ft文件
    clean_files("ft")
    
    # 打开FT页面
    print("Opening FT main page...")
    pyautogui.moveTo(591, 574)
    webbrowser.open("https://www.ft.com/")
    # 稍微滚动一下页面，以确保所有内容都加载
    for i in range(5):
        pyautogui.scroll(-80)
        time.sleep(0.5)
    
    # 等待文件下载
    print("Waiting for FT file download...")
    while count_files("ft") < 1:
        time.sleep(2)
        print(".", end="", flush=True)
    
    print("\nFT file detected!")
    print("FT file downloaded. Processing...")
    
    # 关闭页面
    close_browser_tabs(1)

def close_browser_tabs(num_tabs):
    """
    关闭指定数量的浏览器标签页
    """
    # AppleScript 代码 (按下 Command+W 快捷键)
    applescript = f'''
    tell application "System Events"
        repeat {num_tabs} times
            key code 13 using command down
            delay 0.5
        end repeat
    end tell
    '''

    # 使用 subprocess 执行 AppleScript
    subprocess.run(['osascript', '-e', applescript])

def display_notification(message):
    """
    显示系统通知
    """
    applescript_code = f'display dialog "{message}" buttons {{"OK"}} default button "OK"'
    subprocess.run(['osascript', '-e', applescript_code], check=True)

def process_news_source(source_name, old_file_path, today_html_path):
    """
    处理特定新闻源的数据，并更新相应文件
    """
    current_datetime = datetime.now().strftime("%Y_%m_%d_%H")

    # 读取旧文件内容
    old_content = get_old_content(old_file_path, 30)
    
    # 获取旧文件中的链接列表(用于去重)
    existing_links = {link for _, _, link in old_content}
    
    # 从新文件中读取内容
    new_content = get_new_content_from_files(source_name.lower())
    
    # 根据is_similar规则排重
    new_rows = []
    for date_str, title, link in new_content:
        is_duplicate = False
        for existing_link in existing_links:
            if is_similar(link, existing_link):
                is_duplicate = True
                break
        if not is_duplicate:
            new_rows.append([date_str, title, link])
            existing_links.add(link)
    
    # 根据source_name，将第一列的字符串替换为对应的名称
    # 注意：today_eng.html 的格式是 [来源, 标题, 链接]
    new_rows1 = [[source_name, title, link] for date_str, title, link in new_rows]

    # 写入source.html并追加到today_eng.html
    if new_rows:
        write_html(old_file_path, new_rows, old_content)
        append_to_today_html(today_html_path, new_rows1)
        print(f"Added {len(new_rows)} new {source_name} articles to files")
    else:
        print(f"No new {source_name} content to add")
    
    return new_rows

if __name__ == "__main__":
    today_html_path = "/Users/yanzhang/Coding/News/today_eng.html"
    
    # 新增：处理FT
    print("\nStarting FT processing...")
    open_webpage_and_monitor_ft()
    process_news_source(
        "FT", 
        "/Users/yanzhang/Coding/News/backup/site/ft.html",
        today_html_path
    )

    # 处理WSJ
    print("\nStarting WSJ processing...")
    open_webpage_and_monitor_wsj()
    process_news_source(
        "WSJ", 
        "/Users/yanzhang/Coding/News/backup/site/wsj.html",
        today_html_path
    )

    # 处理Bloomberg
    print("\nStarting Bloomberg processing...")
    open_webpage_and_monitor_bloomberg()
    process_news_source(
        "Bloomberg", 
        "/Users/yanzhang/Coding/News/backup/site/bloomberg.html",
        today_html_path
    )

    # 处理Reuters
    print("\nStarting Reuters processing...")
    open_webpage_and_monitor_reuters()
    process_news_source(
        "Reuters", 
        "/Users/yanzhang/Coding/News/backup/site/reuters.html",
        today_html_path
    )

    print("\nAll news sources processed.")