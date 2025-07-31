import re
import os
import glob
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

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

# 打开 WSJ_CN 网站
driver.get("https://cn.wsj.com/")

# 等待页面上某个特定元素出现，表明页面已经正常加载
# 这里等待任意一个新闻标题元素出现
# wait = WebDriverWait(driver,30)
# wait.until(EC.presence_of_element_located((By.XPATH, 
#     "//a[contains(@class, 'css-g4pnb7')] | " +
#     "//a[contains(@class, 'css-1rznr30-CardLink')] | " +
#     "//div[contains(@class, 'css-wxquvv-HeadlineTextBlock')]/parent::a | " +
#     "//div[contains(@class, 'css-18mqv2f-HeadlineTextBlock')]/parent::a"
# )))

# 查找旧的 html 文件
file_pattern = "/Users/yanzhang/Coding/News/backup/site/wsj_cn.html"
old_file_list = glob.glob(file_pattern)

old_content = []
if old_file_list:
    old_file_path = old_file_list[0]
    seven_days_ago = current_datetime - timedelta(days=10)

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
    # 使用多个选择器来匹配不同类型的新闻标题
    selectors = [
        # 匹配中等大小的头条新闻
        "//a[contains(@class, 'css-g4pnb7')]",
        # 匹配常规新闻标题
        "//a[contains(@class, 'css-1rznr30-CardLink')]",
        # 匹配其他可能的新闻标题格式
        "//div[contains(@class, 'css-wxquvv-HeadlineTextBlock')]/parent::a",
        "//div[contains(@class, 'css-18mqv2f-HeadlineTextBlock')]/parent::a"
    ]
    
    titles_elements = []
    for selector in selectors:
        elements = driver.find_elements(By.XPATH, selector)
        titles_elements.extend(elements)

    print(f"找到 {len(titles_elements)} 个标题元素。")

    for title_element in titles_elements:
        href = title_element.get_attribute('href')
        # 对于某些元素，文本可能在子元素中
        title_text = title_element.text.strip()
        if not title_text:
            # 尝试从子元素获取文本
            title_spans = title_element.find_elements(By.XPATH, ".//span[contains(@class, 'css-nj7t9y')] | .//div[contains(@class, 'css-wxquvv-HeadlineTextBlock')] | .//div[contains(@class, 'css-18mqv2f-HeadlineTextBlock')]")
            if title_spans:
                title_text = title_spans[0].text.strip()
        
        # 此处添加移除阅读时间标记的逻辑
        title_text = re.sub(r'\d+ min read', '', title_text).strip()

        if href and title_text:
            #print(f"标题: {title_text}, 链接: {href}")

            if 'cn.wsj.com' in href and 'podcasts' not in href and 'sports' not in href and 'buyside' not in href:
                if not any(is_similar(href, old_link) for _, _, old_link in old_content):
                    if not any(is_similar(href, new_link) for _, _, new_link in new_rows):
                        new_rows.append([formatted_datetime, title_text, href])
                        new_rows1.append(["WSJCN", title_text, href])
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

# 创建站点 HTML 文件 (wsj_cn.html)
new_html_path = f"/Users/yanzhang/Coding/News/backup/site/wsj_cn.html"
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
    today_html_path = "/Users/yanzhang/Coding/News/today_wsjcn.html"
    file_exists = os.path.isfile(today_html_path)
    
    # 格式化HTML内容，确保每行都有适当的换行和缩进
    def format_html_row(row):
        site, title, link = row
        clickable_title = f'<a href="{link}" target="_blank">{title}</a>'
        return f"<tr><td>{site}</td><td>{clickable_title}</td></tr>\n"

    if file_exists:
        # 读取现有内容
        with open(today_html_path, 'r', encoding='utf-8') as file:
            content = file.read()
            # 移除结束标签
            content = content.replace("</table></body></html>", "")

        # 追加新内容
        with open(today_html_path, 'w', encoding='utf-8') as file:
            file.write(content)
            for row in new_rows1:
                file.write(format_html_row(row))
            file.write("</table>\n</body>\n</html>")
    else:
        # 创建新文件
        with open(today_html_path, 'w', encoding='utf-8') as file:
            file.write("<!DOCTYPE html>\n")
            file.write("<html>\n<head>\n<meta charset='utf-8'>\n</head>\n<body>\n")
            file.write("<table border='1'>\n")
            file.write("<tr><th>site</th><th>Title</th></tr>\n")
            for row in new_rows1:
                file.write(format_html_row(row))
            file.write("</table>\n</body>\n</html>")

    # 确保文件写入完成
    with open(today_html_path, 'r+', encoding='utf-8') as file:
        file.flush()
        os.fsync(file.fileno())