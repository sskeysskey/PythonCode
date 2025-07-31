import re
import os
import time
import glob
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime, timedelta
import random
from playwright.sync_api import sync_playwright

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

def simulate_human_behavior(page):
    """ 模拟人类的随机行为，如滚动和鼠标移动 """
    # 模拟随机的页面滚动
    for _ in range(random.randint(1, 3)):
        page.mouse.wheel(0, random.randint(100, 500))
        time.sleep(random.uniform(1, 3))  # 随机等待

    # 模拟随机的鼠标移动
    page.mouse.move(random.randint(0, 400), random.randint(0, 400))
    time.sleep(random.uniform(1, 2))

# 获取当前日期
current_datetime = datetime.now()
formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

# 查找旧的 html 文件
file_pattern = "/Users/yanzhang/Coding/News/backup/site/wsj.html"
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
                    # 若日期大于等于50天前的日期，则保留
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

# 使用 Playwright 进行网页抓取
with sync_playwright() as p:
    # 启动正常的浏览器，而不是无头浏览器
    browser = p.chromium.launch(headless=False)

    # 创建一个新的浏览器上下文
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )

    # 修改 `navigator.webdriver` 属性为 `undefined`，绕过检测
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    # 禁用 headless 模式，并启动页面
    page = context.new_page()

    try:
        # 打开 WSJ 网站
        page.goto("https://www.wsj.com/")

        # 等待页面的主要内容加载完成
        page.wait_for_load_state('networkidle')

        # 模拟人类的滚动和鼠标移动
        simulate_human_behavior(page)

        # 等待文章标题加载完毕
        page.wait_for_selector('h3.css-fsvegl a')

        # 抓取所有符合条件的标题元素
        titles_elements = page.query_selector_all('h3.css-fsvegl a')

        print(f"找到 {len(titles_elements)} 个标题元素。")

        for title_element in titles_elements:
            href = title_element.get_attribute('href')
            # 跳过包含 livecoverage 的链接
            if 'livecoverage' in href.lower():
                continue
            
            title_text = title_element.inner_text().strip()

            # 移除阅读时间标记或其他不必要的内容
            title_text = re.sub(r'\d+ min read', '', title_text).strip()

            # 打印抓取到的标题和链接
            print(f"标题: {title_text}")
            print(f"链接: {href}")

    except Exception as e:
        print(f"抓取过程中出现错误: {e}")

    # 关闭浏览器
    browser.close()

# 旧文件处理
if old_file_list:
    try:
        os.remove(old_file_path)
        print(f"文件 {old_file_path} 已被删除。")
    except OSError as e:
        print(f"错误: {e.strerror}. 文件 {old_file_path} 无法删除。")

# 创建 HTML 文件
new_html_path = f"/Users/yanzhang/Coding/News/backup/site/wsj.html"
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
    today_html_path = "/Users/yanzhang/Coding/News/today_wsj.html"
    file_exists = os.path.isfile(today_html_path)

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
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
            html_file.write(append_content)
            html_file.write("</table></body></html>")
            html_file.flush()
            os.fsync(html_file.fileno())

# 延迟一秒再结束
time.sleep(1)  # 等待1秒