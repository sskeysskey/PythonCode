# o1优化后代码

import os
import cv2
import time
import pyautogui
import numpy as np
from PIL import ImageGrab
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def is_similar(url1, url2):
    """
    比较两个URL是否只在参数不同或其他细微处不同，
    通过比较URL的scheme、netloc和path判定是否相似。
    """
    parsed_url1, parsed_url2 = urlparse(url1), urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2


def capture_screen():
    """
    使用PIL截取当前屏幕，并转换为OpenCV可以处理的格式。
    """
    screenshot = ImageGrab.grab()
    screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    return screenshot


def find_image_on_screen(template, threshold=0.9):
    """
    在屏幕上查找给定模板图片，返回匹配位置及模板尺寸。
    threshold默认为0.9。
    """
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None


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


def fetch_content(driver, existing_links, formatted_datetime):
    """
    抓取当前页面满足CSS选择器的所有链接，同时移除已有链接，返回新增数据。
    """
    new_rows = []
    try:
        css_selector = "a[href*='/2025']"
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)))
        titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
        new_rows = process_titles(titles_elements, existing_links, formatted_datetime)
    except Exception as e:
        print("抓取过程中出现错误:", e)
    return new_rows


def switch_to_us_and_fetch(driver, existing_links, formatted_datetime):
    """
    切换到US版后，再次抓取页面内容。
    """
    try:
        region_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".media-ui-RegionPicker_region-p79mNAtF--M-"))
        )
        region_button.click()
        time.sleep(1)

        us_option = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='dropdown']//div[text()='US']"))
        )
        us_option.click()
        time.sleep(1)
        return fetch_content(driver, existing_links, formatted_datetime)
    except Exception as e:
        print("切换到US版并抓取内容时出现错误:", e)
        return []

def switch_to_asia_and_fetch(driver, existing_links, formatted_datetime):
    """
    切换到US版后，再次抓取页面内容。
    """
    try:
        region_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".media-ui-RegionPicker_region-p79mNAtF--M-"))
        )
        region_button.click()
        time.sleep(1)

        us_option = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@data-testid='dropdown']//div[text()='Asia']"))
        )
        us_option.click()
        time.sleep(1)
        return fetch_content(driver, existing_links, formatted_datetime)
    except Exception as e:
        print("切换到US版并抓取内容时出现错误:", e)
        return []

def process_titles(titles_elements, existing_links, formatted_datetime):
    """
    处理提取到的标题元素，过滤无关或重复链接，并返回新的行数据。
    同时将已抓取的链接存入existing_links集合中。
    """
    new_rows = []
    for title_element in titles_elements:
        href = title_element.get_attribute('href')
        title_text = title_element.text.strip()

        if title_text.startswith("Newsletter: "):
            title_text = title_text[11:]

        # 跳过包含 '/videos/2025' 的链接
        if '/videos/2025' in href:
            print(f"Skipped video link: {href}")
            continue

        print(f"Processing element: Href: {href}, Text: {title_text}")
        if is_valid_title(title_text) and href and not any(is_similar(href, link) for link in existing_links):
            new_rows.append([formatted_datetime, title_text, href])
            existing_links.add(href)
            print(f"Added new row: {title_text}")
        else:
            print(f"Skipped: {title_text}")
    return new_rows


def is_valid_title(title_text):
    """
    判断标题是否有效，过滤包含特定短语的标题，以及纯时间格式的标题。
    """
    invalid_phrases = [
        'Illustration:', '/Bloomberg', 'Getty Images', '/AP Photo', '/AP', 'Photos:',
        'Photo illustration', 'Source:', '/AFP', 'NurPhoto', 'SOurce:', 'WireImage',
        'Listen (', 'Podcast:'
    ]
    if any(phrase in title_text for phrase in invalid_phrases):
        return False

    if any(keyword in title_text for keyword in ['Listen', 'Watch']) and '(' in title_text and ')' in title_text:
        title_text = title_text.split(')')[1].strip()
    return True if title_text and not is_time_format(title_text) else False


def is_time_format(text):
    """
    判断文本是否是类似'4:57'这样纯时间格式。
    """
    try:
        if len(text) in [4, 5] and ':' in text:
            parts = text.split(':')
            return all(part.isdigit() for part in parts)
        return False
    except:
        return False


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
    将新增的抓取结果追加到today_eng.html文件末尾，并进行文件完整性校验。
    """
    append_content = ''.join([
        f"<tr><td>{row[0]}</td><td><a href='{row[2]}' target='_blank'>{row[1]}</a></td></tr>\n"
        for row in new_rows1
    ])
    try:
        if os.path.exists(today_html_path):
            with open(today_html_path, 'r+', encoding='utf-8') as html_file:
                content = html_file.read()
                insertion_point = content.rindex("</table></body></html>")
                html_file.seek(insertion_point)
                html_file.write(append_content + "</table></body></html>")
                html_file.flush()
                os.fsync(html_file.fileno())
        else:
            with open(today_html_path, 'w', encoding='utf-8') as html_file:
                html_file.write("<html><body><table border='1'>\n<tr><th>Date</th><th>Title</th></tr>\n")
                html_file.write(append_content + "</table></body></html>")
                html_file.flush()
                os.fsync(html_file.fileno())

        with open(today_html_path, 'r', encoding='utf-8') as verify_file:
            content = verify_file.read()
            if not content.endswith("</table></body></html>"):
                raise IOError("File writing verification failed")
    except Exception as e:
        print(f"Error writing to file: {e}")
        raise


if __name__ == "__main__":
    current_datetime = datetime.now().strftime("%Y_%m_%d_%H")
    chrome_driver_path = "/Users/yanzhang/Downloads/backup/chromedriver"
    timeout = 5  # 设置超时时间

    template_path_accept = '/Users/yanzhang/Coding/python_code/Resource/Bloomberg_agree.png'
    service = Service(executable_path=chrome_driver_path)
    driver = webdriver.Chrome(service=service)
    driver.get("https://www.bloomberg.com/")

    template_accept = cv2.imread(template_path_accept, cv2.IMREAD_COLOR)
    if template_accept is None:
        raise FileNotFoundError(f"模板图片未能正确读取于路径 {template_path_accept}")

    found = False
    start_time = time.time()
    time.sleep(1)

    # 循环查找“同意”（或相似）弹窗图片并点击
    while not found and time.time() - start_time < timeout:
        location, shape = find_image_on_screen(template_accept)
        if location:
            print("找到图片，继续执行后续程序。")
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            pyautogui.click(center_x, center_y)
            found = True
        else:
            time.sleep(1)

    old_file_path = "/Users/yanzhang/Coding/News/backup/site/bloomberg.html"
    old_content = get_old_content(old_file_path, 30)
    existing_links = {link for _, _, link in old_content}

    # 点击“Dismiss”按钮（若出现）
    try:
        dismiss_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'Button_text-N76nbJyFyw0-') and text()='Dismiss']"))
        )
        dismiss_button.click()
        print("Dismiss按钮已点击")
    except Exception:
        print("Dismiss按钮未出现或未点击")

    # 第一次抓取（当前页面）
    new_rows = fetch_content(driver, existing_links, current_datetime)
    # existing_links.update(link for _, _, link in new_rows)

    # 切换到US版并抓取
    # us_new_rows = switch_to_us_and_fetch(driver, existing_links, current_datetime)
    # asia_new_rows = switch_to_asia_and_fetch(driver, existing_links, current_datetime)

    # 合并两次抓取的结果并去重
    # all_new_rows_dict = {row[2]: row for row in new_rows + us_new_rows}
    # all_new_rows_dict = {row[2]: row for row in new_rows + asia_new_rows}
    # all_new_rows = list(all_new_rows_dict.values())

    # 格式化后用于插入today_html
    # new_rows1 = [["Bloomberg", title, link] for _, title, link in all_new_rows]
    new_rows1 = [["Bloomberg", title, link] for _, title, link in new_rows]

    driver.quit()

    # 如旧文件存在则删除
    if os.path.exists(old_file_path):
        os.remove(old_file_path)

    # 写入bloomberg.html并追加到today_eng.html
    write_html(old_file_path, new_rows, old_content)
    append_to_today_html("/Users/yanzhang/Coding/News/today_eng.html", new_rows1)
    time.sleep(1)