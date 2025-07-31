import os
import re
import glob
import shutil
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

def is_similar(url1, url2):
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    return f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}" == f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"

def get_old_content(file_path, days_ago):
    if not os.path.isfile(file_path):
        return []

    cutoff_date = datetime.now() - timedelta(days=days_ago)
    old_content = []

    with open(file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file, 'html.parser')
        rows = soup.find_all('tr')[1:]  # 跳过标题行
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 2:
                date_str = cols[0].text.strip()
                date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                if date >= cutoff_date:
                    title_column = cols[1]
                    title = title_column.text.strip()
                    link = title_column.find('a')['href'] if title_column.find('a') else None
                    old_content.append([date_str, title, link])
    return old_content

def fetch_new_content(driver, old_links, formatted_datetime):
    new_rows = []
    css_selector = "a[href*='/article/']"
    titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)

    for title_element in titles_elements:
        href = title_element.get_attribute('href')
        title_text = title_element.text.strip()
        if not title_text or any(sub in title_text for sub in ["AP", "ＡＰ", "共同", "ロイター", "高野地域協議会提供"]):
            continue
        title_text = re.sub(r'^\d{1,2}:\d{2}\s*', '', title_text)
        if not any(is_similar(href, link) for link in old_links + [row[2] for row in new_rows]):
            new_rows.append([formatted_datetime, title_text, href])
    return new_rows

def write_html(file_path, new_rows, old_content):
    with open(file_path, 'w', encoding='utf-8') as html_file:
        html_file.write("<html><body><table border='1'>\n<tr><th>Date</th><th>Title</th></tr>\n")
        for row in new_rows + old_content:
            clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>" if row[2] else row[1]
            html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
        html_file.write("</table></body></html>")

def append_to_html(file_path, new_rows1):
    append_content = "".join([f"<tr><td>{row[0]}</td><td><a href='{row[2]}' target='_blank'>{row[1]}</a></td></tr>\n" for row in new_rows1])
    
    if not os.path.isfile(file_path):
        with open(file_path, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n<tr><th>site</th><th>Title</th></tr>\n")
            html_file.write(append_content)
            html_file.write("</table></body></html>")
    else:
        with open(file_path, 'r+', encoding='utf-8') as html_file:
            html_file.seek(0, os.SEEK_END)
            html_file.seek(html_file.tell() - len("</table></body></html>"), os.SEEK_SET)
            html_file.write(append_content)
            html_file.write("</table></body></html>")

current_datetime = datetime.now().strftime("%Y_%m_%d_%H")

chrome_driver_path = "/Users/yanzhang/Downloads/backup/chromedriver"
service = Service(executable_path=chrome_driver_path)
driver = webdriver.Chrome(service=service)
driver.get("https://www.nikkei.com/")

old_file_path = "/Users/yanzhang/Documents/News/backup/site/nikkei.html"
old_content = get_old_content(old_file_path, 18)
old_links = [row[2] for row in old_content]

new_rows = fetch_new_content(driver, old_links, current_datetime)
driver.quit()

if new_rows:
    try:
        os.remove(old_file_path)
    except OSError as e:
        print(f"错误: {e.strerror}. 文件 {old_file_path} 无法删除。")

    new_html_path = "/Users/yanzhang/Documents/News/backup/site/nikkei.html"
    write_html(new_html_path, new_rows, old_content)

    new_rows1 = [["Nikkei", row[1], row[2]] for row in new_rows]

    # 复制 today_eng.html 到 today_all.html
    today_eng_path = "/Users/yanzhang/Documents/News/today_eng.html"
    today_all_path = "/Users/yanzhang/Documents/News/today_all.html"
    if os.path.isfile(today_eng_path):
        shutil.copy(today_eng_path, today_all_path)

    append_to_html(today_all_path, new_rows1)
    append_to_html("/Users/yanzhang/Documents/News/today_jpn.html", new_rows1)