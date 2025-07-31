import os
import glob
import webbrowser
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

def open_html_file(file_path):
    webbrowser.open('file://' + os.path.realpath(file_path), new=2)
    exit()  # 终止程序

def open_new_html_file():
    webbrowser.open('file://' + os.path.realpath(new_html_path), new=2)

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度，如果相似度超过阈值则返回 True，否则返回 False。
    主要比较 URL 的协议、主机名和路径。
    """
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)

    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"

    return base_url1 == base_url2

# 获取当前日期
current_datetime = datetime.now()
current_year = datetime.now().year
current_month = datetime.now().month
current_day = datetime.now().day
formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

# ChromeDriver 路径
chrome_driver_path = "/Users/yanzhang/Downloads/backup/chromedriver"

# 设置 ChromeDriver
service = Service(executable_path=chrome_driver_path)
driver = webdriver.Chrome(service=service)

# 打开 Economist 网站
driver.get("https://hbr.org/")

# 查找旧的 html 文件
file_pattern = "/Users/yanzhang/Coding/News/backup/site/hbr.html"
old_file_list = glob.glob(file_pattern)

if not old_file_list:
    print("未找到符合条件的旧文件。")
    # 处理未找到旧文件的情况
else:
    # 选择第一个找到的文件（您可能需要进一步的逻辑来选择正确的文件）
    old_file_path = old_file_list[0]

    # 计算当前日期26天前的日期
    current_date = datetime.now()
    seven_days_ago = current_date - timedelta(days=30)
    
    # 读取旧文件中的所有内容，并删除20天前的内容
    old_content = []
    with open(old_file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file, 'html.parser')
        rows = soup.find_all('tr')[1:]  # 跳过标题行
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 2:  # 确保行有足够的列
                date_str = cols[0].text.strip()
                # 解析日期字符串
                date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                # 若日期大于等于26天前的日期，则保留
                if date >= seven_days_ago:
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
    # css_selector = f"a[href*='hbr.org/{current_year}/']"
    driver.implicitly_wait(20)  # 等待20秒，根据实际情况调整
    css_selector = "a[href*='/2024/']"
    titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)

    for title_element in titles_elements:
        href = title_element.get_attribute('href')
        title_text = title_element.text.strip()

        if "Audio" in title_text:
            continue

        if href and title_text:
            #print(f"标题: {title_text}, 链接: {href}")

            if 'podcasts' not in href:
                # if not any(href == old_link for _, _, old_link in old_content):
                #     if not any(href == new_link for _, _, new_link in new_rows):
                if not any(is_similar(href, old_link) for _, _, old_link in old_content):
                    if not any(is_similar(href, new_link) for _, _, new_link in new_rows):
                        new_rows.append([formatted_datetime, title_text, href])
                        new_rows1.append(["HBR", title_text, href])
                        all_links.append(href)  # 添加到所有链接的列表中

except Exception as e:
    print("抓取过程中出现错误:", e)

finally:
    # 无论成功与否，最终都关闭驱动
    driver.quit()

try:
    os.remove(old_file_path)
    print(f"文件 {old_file_path} 已被删除。")
except OSError as e:
    print(f"错误: {e.strerror}. 文件 {old_file_path} 无法删除。")

# 创建 HTML 文件
new_html_path = f"/Users/yanzhang/Coding/News/backup/site/hbr.html"
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

if new_rows1:
    # 创建用于翻译的每日新闻总表html
    today_html_path = "/Users/yanzhang/Coding/News/today_eng.html"

    # 检查文件是否存在
    file_exists = os.path.isfile(today_html_path)

    # 如果文件不存在，创建文件并写入基础HTML结构
    if not file_exists:
        with open(today_html_path, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>site</th><th>Title</th></tr>\n")

    # 准备要追加的内容
    append_content = ""
    for row in new_rows1:
        clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
        append_content += f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n"

    # 如果文件已存在，先删除末尾的HTML结束标签，再追加新内容，最后重新添加结束标签
    if file_exists:
        with open(today_html_path, 'r+', encoding='utf-8') as html_file:
            # 移动到文件末尾的"</table></body></html>"前
            html_file.seek(0, os.SEEK_END)
            html_file.seek(html_file.tell() - len("</table></body></html>"), os.SEEK_SET)
            # 追加新内容
            html_file.write(append_content)
            # 重新添加HTML结束标签
            html_file.write("</table></body></html>")

    # 如果文件是新建的，添加新内容和HTML结束标签
    else:
        with open(today_html_path, 'a', encoding='utf-8') as html_file:
            html_file.write(append_content)
            html_file.write("</table></body></html>")

# open_new_html_file()