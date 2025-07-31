import os
import glob
import webbrowser
from bs4 import BeautifulSoup
from selenium import webdriver
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

def open_html_file(file_path):
    webbrowser.open('file://' + os.path.realpath(file_path), new=2)
    exit()  # 终止程序

def open_new_html_file():
    webbrowser.open('file://' + os.path.realpath(new_html_path), new=2)

# 获取当前日期
current_datetime = datetime.now()
formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

# ChromeDriver 路径
chrome_driver_path = "/Users/yanzhang/Downloads/backup/chromedriver"

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

# 打开 MIT Technology Review 网站
driver.get("https://www.technologyreview.com/")

# 查找旧的 html 文件
file_pattern = "/Users/yanzhang/Documents/News/backup/site/technologyreview.html"
old_file_list = glob.glob(file_pattern)

old_content = []
if old_file_list:
    old_file_path = old_file_list[0]
    seven_days_ago = current_datetime - timedelta(days=40)

    try:
        with open(old_file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            rows = soup.find_all('tr')[1:]  # 跳过标题行
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 2:  # 确保行有足够的列
                    date_str = cols[0].text.strip()
                    # 解析日期字符串
                    date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                    # 若日期大于等于指定时间，则保留
                    if date >= seven_days_ago:
                        title_column = cols[1]
                        title = title_column.text.strip()
                        # 从标题所在的列中提取链接
                        link = title_column.find('a')['href'] if title_column.find('a') else None
                        old_content.append([date_str, title, link])
    except OSError as e:
        print(f"读取文件时出错: {e}")

# 抓取新内容
new_rows = []
new_rows1 = []
all_links = [old_link for _, _, old_link in old_content]  # 既有的所有链接

try:
    css_selector = f"a[href*='technologyreview.com/{current_datetime.year}/']"
    titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)

    for title_element in titles_elements:
        href = title_element.get_attribute('href')
        title_text = title_element.text.strip()

        if href and title_text:
            #print(f"标题: {title_text}, 链接: {href}")

            # 排除不需要的链接（例如包含 'podcasts' 的）
            if 'podcasts' not in href:
                if not any(href == old_link for _, _, old_link in old_content):
                    if not any(href == new_link for _, _, new_link in new_rows):
                        new_rows.append([formatted_datetime, title_text, href])
                        new_rows1.append(["TechReview", title_text, href])
                        all_links.append(href)  # 添加到所有链接的列表中

except Exception as e:
    print("抓取过程中出现错误:", e)

# 关闭驱动
driver.quit()

if old_file_list:
    try:
        os.remove(old_file_path)
        print(f"文件 {old_file_path} 已被删除。")
    except OSError as e:
        print(f"错误: {e.strerror}. 文件 {old_file_path} 无法删除。")

# 创建 site HTML 文件（technologyreview.html）
new_html_path = f"/Users/yanzhang/Documents/News/backup/site/technologyreview.html"
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
    # 创建用于翻译的每日新闻总表html
    today_html_path = "/Users/yanzhang/Documents/News/today_eng.html"
    closing_tag = "</table></body></html>"
    file_exists = os.path.isfile(today_html_path)

    # 如果文件不存在，则创建初始框架
    if not file_exists:
        with open(today_html_path, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
            html_file.write(closing_tag)
    
    # 准备要追加的内容
    append_content = ""
    for row in new_rows1:
        clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
        append_content += f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n"
    
    # 先读取整个文件内容，去掉末尾的结束标签后，再追加新内容，再重新拼接结束标签
    with open(today_html_path, 'r', encoding='utf-8') as html_file:
        content = html_file.read()
    if closing_tag in content:
        content = content.replace(closing_tag, "")
    new_file_content = content + append_content + closing_tag
    with open(today_html_path, 'w', encoding='utf-8') as html_file:
        html_file.write(new_file_content)