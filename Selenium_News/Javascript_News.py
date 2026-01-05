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

# ================= 工具函数 =================

def capture_screen():
    """ 使用PIL的ImageGrab直接截取屏幕，并转换为OpenCV格式 """
    screenshot = ImageGrab.grab()
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

def find_image_on_screen(template, threshold=0.9):
    """ 在当前屏幕中查找给定模板图像的匹配位置（精度默认0.9）。 """
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    # 释放截图及相关资源
    del screen
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None

def is_similar(url1, url2):
    """ 比较两个URL是否只在参数不同或其他细微处不同 """
    if not url1 or not url2:
        return False
    parsed_url1, parsed_url2 = urlparse(url1), urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def get_old_content(file_path, days_ago):
    """ 读取旧的HTML文件 """
    old_content = []
    if not os.path.exists(file_path):
        return old_content
    cutoff_date = datetime.now() - timedelta(days=days_ago)
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            rows = soup.find_all('tr')[1:] # 跳过表头
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 2:
                    continue
                date_str, title = cols[0].text.strip(), cols[1].text.strip()
                link = cols[1].find('a')['href'] if cols[1].find('a') else ''
                try:
                    date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                    if date >= cutoff_date:
                        old_content.append([date_str, title, link])
                except ValueError:
                    continue
    except Exception as e:
        print(f"读取旧文件出错: {e}")
    return old_content

def get_new_content_from_files(file_prefix):
    """ 读取Downloads目录下以指定前缀开头的HTML文件内容 """
    new_content = []
    download_dir = "/Users/yanzhang/Downloads/"
    files = glob.glob(os.path.join(download_dir, f"{file_prefix}_*.html"))
    current_datetime = datetime.now().strftime("%Y_%m_%d_%H")
    
    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'html.parser')
                rows = soup.find_all('tr')[1:] # 跳过表头
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) < 2:
                        continue
                    date_str = cols[0].text.strip() if len(cols) > 0 else current_datetime
                    title = cols[1].text.strip() if len(cols) > 1 else ""
                    link = cols[1].find('a')['href'] if cols[1].find('a') else ''
                    if title and link:
                        new_content.append([date_str, title, link])
        except Exception:
            continue
    return new_content

def write_html(file_path, new_rows, old_content):
    """ 写入HTML文件并校验 """
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
    """ 追加到总表 """
    try:
        append_content = ""
        for row in new_rows1:
            append_content += f"<tr><td>{row[0]}</td><td><a href='{row[2]}' target='_blank'>{row[1]}</a></td></tr>\n"
        
        closing_tag = "</table></body></html>"
        
        if os.path.exists(today_html_path):
            with open(today_html_path, 'r', encoding='utf-8') as html_file:
                content = html_file.read()
            if closing_tag in content:
                content = content.replace(closing_tag, "")
            content += append_content + closing_tag
            
            with open(today_html_path, 'w', encoding='utf-8') as html_file:
                html_file.write(content)
        else:
            with open(today_html_path, 'w', encoding='utf-8') as html_file:
                html_file.write("<html><body><table border='1'>\n<tr><th>site</th><th>Title</th></tr>\n")
                html_file.write(append_content + closing_tag)
                
        # 验证
        with open(today_html_path, 'r', encoding='utf-8') as verify_file:
            content = verify_file.read()
            if not content.endswith(closing_tag):
                raise IOError("File writing verification failed")
    except Exception as e:
        print(f"Error writing to file: {e}")
        raise

def count_files(prefix):
    download_dir = "/Users/yanzhang/Downloads/"
    files = glob.glob(os.path.join(download_dir, f"{prefix}_*.html"))
    return len(files)

def clean_files(prefix):
    download_dir = "/Users/yanzhang/Downloads/"
    prefixes = [prefix + '_']
    if prefix == "wsj":
        prefixes.append("cnwsj_")
    elif prefix == "bloomberg":
        prefixes.append("cnbloomberg_")
        
    for current_prefix in prefixes:
        existing_files = glob.glob(os.path.join(download_dir, f"{current_prefix}*.html"))
        for file in existing_files:
            try:
                os.remove(file)
            except Exception:
                pass

def close_browser_tabs(num_tabs):
    applescript = f'''
    tell application "System Events"
        repeat {num_tabs} times
            key code 13 using command down
            delay 0.5
        end repeat
    end tell
    '''
    subprocess.run(['osascript', '-e', applescript])

# ================= 业务逻辑函数 =================

def open_webpage_and_monitor_bloomberg():
    clean_files("bloomberg")
    print("Opening Bloomberg main page...")
    webbrowser.open("https://www.bloomberg.com/asia")
    
    print("Waiting for first file download...")
    while count_files("bloomberg") < 1:
        time.sleep(2)
    print("\nFirst file detected!")
    
    print("Opening Bloomberg Asia page...")
    template_paths = {
        "asia": "/Users/yanzhang/Coding/python_code/Resource/scraper_asia.png",
        "us": "/Users/yanzhang/Coding/python_code/Resource/scraper_us.png"
    }
    
    templates = {}
    for key, path in template_paths.items():
        if os.path.exists(path):
            templates[key] = cv2.imread(path, cv2.IMREAD_COLOR)
    
    found_asia_image = False
    timeout_stop = time.time() + 10
    
    if "asia" in templates:
        while not found_asia_image and time.time() < timeout_stop:
            location_asia, shape_asia = find_image_on_screen(templates["asia"])
            if location_asia:
                center_x = (location_asia[0] + shape_asia[1] // 2) // 2
                center_y = (location_asia[1] + shape_asia[0] // 2) // 2
                pyautogui.click(center_x, center_y)
                found_asia_image = True
                print(f"找到asia图片位置: {location_asia}")
            else:
                time.sleep(1)
    
    if not found_asia_image and "us" in templates:
        time.sleep(1)
        location_us, shape_us = find_image_on_screen(templates["us"])
        if location_us:
            center_x = (location_us[0] + shape_us[1] // 2) // 2
            center_y = (location_us[1] + shape_us[0] // 2) // 2
            pyautogui.click(center_x, center_y)

    print("Waiting for second file download...")
    while count_files("bloomberg") < 2:
        time.sleep(2)
    print("\nAll Bloomberg files downloaded.")
    close_browser_tabs(1)

def open_webpage_and_monitor_wsj():
    clean_files("wsj")
    print("Opening WSJ main page...")
    pyautogui.moveTo(591, 574)
    webbrowser.open("https://www.wsj.com/")
    for i in range(5):
        pyautogui.scroll(-80)
        time.sleep(0.5)
    
    print("Waiting for WSJ file download...")
    while count_files("wsj") < 1:
        time.sleep(2)
    print("\nWSJ file detected!")
    close_browser_tabs(1)

def open_webpage_and_monitor_reuters():
    clean_files("reuters")
    print("Opening reuters main page...")
    pyautogui.moveTo(591, 574)
    webbrowser.open("https://www.reuters.com/")
    for i in range(5):
        pyautogui.scroll(-80)
        time.sleep(0.5)
    
    print("Waiting for reuters file download...")
    while count_files("reuters") < 1:
        time.sleep(2)
    print("\nreuters file detected!")
    close_browser_tabs(1)

def open_webpage_and_monitor_ft():
    clean_files("ft")
    print("Opening FT main page...")
    pyautogui.moveTo(591, 574)
    webbrowser.open("https://www.ft.com/")
    for i in range(5):
        pyautogui.scroll(-80)
        time.sleep(0.5)
    
    print("Waiting for FT file download...")
    while count_files("ft") < 1:
        time.sleep(2)
    print("\nFT file detected!")
    close_browser_tabs(1)

def process_news_source(source_name, old_file_path, today_html_path):
    old_content = get_old_content(old_file_path, 30)
    existing_links = {link for _, _, link in old_content}
    new_content = get_new_content_from_files(source_name.lower())
    
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
    
    new_rows1 = [[source_name, title, link] for date_str, title, link in new_rows]
    
    if new_rows:
        write_html(old_file_path, new_rows, old_content)
        append_to_today_html(today_html_path, new_rows1)
        print(f"✅ Added {len(new_rows)} new {source_name} articles.")
    else:
        print(f"⚠️ No new {source_name} content to add.")
    return new_rows

# ================= 主执行入口 =================

def main():
    print("="*60)
    print("🚀 正在启动第一阶段：JavaScript/GUI News Scraper")
    print("⚠️ 注意：此阶段会控制鼠标和打开浏览器，请勿操作电脑！")
    print("="*60)

    today_html_path = "/Users/yanzhang/Coding/News/today_eng.html"

    # 1. FT
    print("\n[Task 1/4] Processing FT...")
    open_webpage_and_monitor_ft()
    process_news_source("FT", "/Users/yanzhang/Coding/News/backup/site/ft.html", today_html_path)

    # 2. WSJ (English)
    print("\n[Task 2/4] Processing WSJ (Eng)...")
    open_webpage_and_monitor_wsj()
    process_news_source("WSJ", "/Users/yanzhang/Coding/News/backup/site/wsj.html", today_html_path)

    # 3. Bloomberg
    print("\n[Task 3/4] Processing Bloomberg...")
    open_webpage_and_monitor_bloomberg()
    process_news_source("Bloomberg", "/Users/yanzhang/Coding/News/backup/site/bloomberg.html", today_html_path)

    # 4. Reuters
    print("\n[Task 4/4] Processing Reuters...")
    open_webpage_and_monitor_reuters()
    process_news_source("Reuters", "/Users/yanzhang/Coding/News/backup/site/reuters.html", today_html_path)

    print("\n✅ 第一阶段 (GUI/JS News) 全部完成！")

if __name__ == "__main__":
    main()
