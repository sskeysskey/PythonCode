import os
import cv2
import time
import glob
import pyautogui
import webbrowser
import numpy as np
from PIL import ImageGrab
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# 定义一些全局变量
chrome_driver_path = "/Users/yanzhang/Downloads/backup/chromedriver"
template_path_accept = '/Users/yanzhang/Documents/python_code/Resource/economist_accept.png'
file_pattern = "/Users/yanzhang/Documents/News/backup/site/economist.html"
new_html_path = "/Users/yanzhang/Documents/News/backup/site/economist.html"
today_html_path = "/Users/yanzhang/Documents/News/today_eng.html"
timeout = 10  # 设置超时时间

# 打开 HTML 文件
def open_html_file(file_path):
    webbrowser.open('file://' + os.path.realpath(file_path), new=2)
    exit()  # 终止程序

# 比较两个 URL 的相似度
def is_similar(url1, url2):
    """
    比较两个 URL 的相似度，如果是同一篇文章则返回 True。
    考虑 URL 的协议、主机名、路径，忽略查询参数和片段。
    还会比较链接路径中的日期和标识符部分。
    """
    if not url1 or not url2:
        return False
        
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)

    # 比较基本部分：协议、主机名
    if parsed_url1.netloc != parsed_url2.netloc:
        return False
        
    # 对于Economist特有的URL结构进行处理
    # 通常格式为/section/year/month/day/article-title
    path1 = parsed_url1.path.rstrip('/')
    path2 = parsed_url2.path.rstrip('/')
    
    # 拆分路径为组件
    path_components1 = path1.split('/')
    path_components2 = path2.split('/')
    
    # 确保路径组件足够比较（至少包含部分/年份/月份/日期/标题）
    if len(path_components1) < 5 or len(path_components2) < 5:
        # 如果路径结构不符合预期，回退到简单比较
        return path1 == path2
    
    # 比较部分、年份、月份、日期和文章标题部分
    # 去掉空字符串（路径开头的'/'导致的）
    path_components1 = [comp for comp in path_components1 if comp]
    path_components2 = [comp for comp in path_components2 if comp]
    
    # 检查前5个组件（部分/年份/月份/日期/标题）是否相同
    # 如果组件数量不同，取较短的长度
    min_length = min(len(path_components1), len(path_components2))
    
    # 至少比较4个组件（确保包含日期和部分标题）
    comp_length = min(min_length, 5)
    
    return path_components1[:comp_length] == path_components2[:comp_length]

# 截取屏幕（使用PIL截屏并转换为OpenCV格式）
def capture_screen():
    # 使用PIL的ImageGrab直接截取屏幕
    screenshot = ImageGrab.grab()
    # 将截图对象转换为OpenCV格式
    screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    return screenshot

# 查找屏幕上的图片，若匹配超过阈值返回坐标和模板尺寸
def find_image_on_screen(template, threshold=0.9):
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None

# 设置Chrome选项以提高性能
chrome_options = Options()
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # 禁用图片加载
chrome_options.page_load_strategy = 'eager'  # 使用eager策略，DOM准备好就开始

# 设置 ChromeDriver
service = Service(executable_path=chrome_driver_path)
driver = webdriver.Chrome(service=service, options=chrome_options)  # 在这里添加options参数

# 打开 Economist 网站
driver.get("https://www.economist.com/")
template_accept = cv2.imread(template_path_accept, cv2.IMREAD_COLOR)

if template_accept is None:
    raise FileNotFoundError(f"模板图片未能正确读取于路径 {template_path_accept}")

found = False
start_time = time.time()
time.sleep(1)

# 循环查找图片
while not found and time.time() - start_time < timeout:
    location, shape = find_image_on_screen(template_accept)
    if location:
        print("找到图片，继续执行后续程序。")
        # 计算中心坐标（注意这里的计算和实际可能有调整需求）
        center_x = (location[0] + shape[1] // 2) // 2
        center_y = (location[1] + shape[0] // 2) // 2
            
        # 鼠标点击中心坐标
        pyautogui.click(center_x, center_y)
        found = True  # 找到图片，设置found为True以退出循环
    else:
        time.sleep(1)

# 查找旧的 HTML 文件
old_file_list = glob.glob(file_pattern)
old_content = []

if old_file_list:
    old_file_path = old_file_list[0]
    threshold_date = datetime.now() - timedelta(days=45)
    with open(old_file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file, 'html.parser')
        rows = soup.find_all('tr')[1:]  # 跳过标题行
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 2:
                date_str = cols[0].text.strip()
                # 解析日期字符串
                date_obj = datetime.strptime(date_str, '%Y_%m_%d_%H')
                # 若日期大于等于30天前的日期，则保留
                if date_obj >= threshold_date:
                    title_column = cols[1]
                    title = title_column.text.strip()
                    # 从标题所在的列中提取链接
                    link = title_column.find('a')['href'] if title_column.find('a') else None
                    old_content.append([date_str, title, link])

# 抓取新内容
new_rows = []
new_rows1 = []
all_links = [old_link for _, _, old_link in old_content]  # 既有的所有链接

try:
    # 查找今年内的链接
    titles_elements = driver.find_elements(By.CSS_SELECTOR, f"a[href*='/{datetime.now().year}/']")
    # 打印titles_elements的内容
    # for title_element in titles_elements:
    #     print(f"Element: {title_element}, Href: {title_element.get_attribute('href')}, Text: {title_element.text.strip()}")
    
    formatted_datetime = datetime.now().strftime("%Y_%m_%d_%H")
    for title_element in titles_elements:
        href = title_element.get_attribute('href')
        title_text = title_element.text.strip()

        if href and title_text:
            if ('podcasts' not in href and "film" not in href and "cartoon" not in href and 
                not ('letters' in href and 'editor' in href and 'Sources and acknowledgments' in href)):
                if not any(is_similar(href, old_link) for _, _, old_link in old_content):
                    if not any(is_similar(href, new_link) for _, _, new_link in new_rows):
                        new_rows.append([formatted_datetime, title_text, href])
                        new_rows1.append(["Economist", title_text, href])
                        all_links.append(href)  # 添加到所有链接的列表中

except Exception as e:
    print("抓取过程中出现错误:", e)

# 关闭驱动
driver.quit()

# 删除旧的 HTML 文件
if old_file_list:
    try:
        os.remove(old_file_path)
        print(f"文件 {old_file_path} 已被删除。")
    except OSError as e:
        print(f"错误: {e.strerror}. 文件 {old_file_path} 无法删除。")

# 创建 site HTML 文件（economist.html）
with open(new_html_path, 'w', encoding='utf-8') as html_file:
    # 写入 HTML 基础结构和表格开始标签
    html_file.write("<html><body><table border='1'>\n")

    # 写入标题行
    html_file.write("<tr><th>Date</th><th>Title</th></tr>\n")

    # 写入新抓取的内容
    new_content_added = False
    for row in new_rows:
        clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
        html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
        new_content_added = True

    # 写入旧内容
    for row in old_content:
        clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>" if row[2] else row[1]
        html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")

    # 结束表格和 HTML 结构
    html_file.write("</table></body></html>")

# 创建每日新闻总表 HTML（today_eng.html）
if new_rows1:
    closing_tag = "</table></body></html>"
    file_exists = os.path.isfile(today_html_path)
    
    # 如果文件不存在，则创建文件并写入基础HTML结构
    if not file_exists:
        with open(today_html_path, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
    
    # 准备要追加的内容
    append_content = ""
    for row in new_rows1:
        clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
        append_content += f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n"
    
    # 采用先读取文件、去掉关闭标签，再追加新内容后重写整个文件的方法
    if file_exists:
        with open(today_html_path, 'r', encoding='utf-8') as html_file:
            content = html_file.read()
        # 移除已有的结束标签（如果存在）
        if closing_tag in content:
            content = content.replace(closing_tag, "")
        new_file_content = content + append_content + closing_tag
        with open(today_html_path, 'w', encoding='utf-8') as html_file:
            html_file.write(new_file_content)
    else:
        # 新建文件时写入全部内容
        with open(today_html_path, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
            html_file.write(append_content)
            html_file.write(closing_tag)
            html_file.flush()
            os.fsync(html_file.fileno())