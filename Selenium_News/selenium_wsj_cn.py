import re
import os
import glob
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import StaleElementReferenceException

# ================= 配置区域 =================

# 1. 浏览器与驱动路径 (Beta 版配置)
CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
CHROME_DRIVER_PATH = "/Users/yanzhang/Downloads/backup/chromedriver_beta"

# 2. 文件路径
OLD_FILE_PATTERN = "/Users/yanzhang/Coding/News/backup/site/wsj_cn.html"
NEW_HTML_PATH = "/Users/yanzhang/Coding/News/backup/site/wsj_cn.html"
TODAY_HTML_PATH = "/Users/yanzhang/Coding/News/today_wsjcn.html"

# ================= 工具函数 =================

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度
    """
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def format_html_row(row):
    """
    today_wsjcn.html 专用的行格式化函数
    """
    site, title, link = row
    clickable_title = f'<a href="{link}" target="_blank">{title}</a>'
    return f"<tr><td>{site}</td><td>{clickable_title}</td></tr>\n"

def main():
    # 获取当前日期
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # ================= 1. 初始化 Selenium (优化版) =================
    print("正在初始化 Chrome Beta 驱动...")

    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_BINARY_PATH

    # --- Headless模式 & 伪装设置 ---
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')

    # --- 伪装 User-Agent ---
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # --- 性能优化 ---
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.page_load_strategy = 'eager'

    # 设置 ChromeDriver
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    # 初始化容器
    new_rows = []
    new_rows1 = []
    old_content = []

    try:
        # 打开 WSJ_CN 网站
        print("正在访问 WSJ CN...")
        driver.get("https://cn.wsj.com/")

        # ================= 2. 滚动加载 (新增) =================
        print("开始滚动页面...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.5)
        print("滚动完成。")

        # ================= 3. 读取旧文件逻辑 (保持不变) =================
        old_file_list = glob.glob(OLD_FILE_PATTERN)
        if old_file_list:
            old_file_path = old_file_list[0]
            seven_days_ago = current_datetime - timedelta(days=10)
            try:
                with open(old_file_path, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    rows = soup.find_all('tr')[1:]
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            date_str = cols[0].text.strip()
                            try:
                                date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                                if date >= seven_days_ago:
                                    title_column = cols[1]
                                    title = title_column.text.strip()
                                    link = title_column.find('a')['href'] if title_column.find('a') else None
                                    old_content.append([date_str, title, link])
                            except ValueError:
                                continue
            except OSError as e:
                print(f"读取旧文件时出错: {e}")

        # ================= 4. 抓取新内容 (Snapshot 策略) =================
        
        all_links = [old_link for _, _, old_link in old_content]

        # WSJ 特有的 XPath 选择器列表 (保留原样)
        selectors = [
            "//a[contains(@class, 'css-g4pnb7')]",
            "//a[contains(@class, 'css-1rznr30-CardLink')]",
            "//div[contains(@class, 'css-wxquvv-HeadlineTextBlock')]/parent::a",
            "//div[contains(@class, 'css-18mqv2f-HeadlineTextBlock')]/parent::a"
        ]

        print("开始扫描标题元素...")
        raw_data_list = []

        # --- 步骤 A & B: 遍历选择器并快速提取数据 ---
        for selector in selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for element in elements:
                    try:
                        href = element.get_attribute('href')
                        
                        # --- 复杂的标题提取逻辑 (保留原样) ---
                        title_text = element.text.strip()
                        if not title_text:
                            # 尝试从子元素获取文本
                            title_spans = element.find_elements(By.XPATH, ".//span[contains(@class, 'css-nj7t9y')] | .//div[contains(@class, 'css-wxquvv-HeadlineTextBlock')] | .//div[contains(@class, 'css-18mqv2f-HeadlineTextBlock')]")
                            if title_spans:
                                title_text = title_spans[0].text.strip()
                        
                        # --- 移除阅读时间标记 (保留原样) ---
                        if title_text:
                            title_text = re.sub(r'\d+ min read', '', title_text).strip()

                        if href and title_text:
                            raw_data_list.append((href, title_text))

                    except StaleElementReferenceException:
                        continue # 元素失效跳过
                    except Exception:
                        continue
            except Exception as e:
                print(f"选择器 {selector} 处理出错: {e}")

        print(f"成功提取了 {len(raw_data_list)} 条原始数据，开始过滤...")

        # --- 步骤 C: 逻辑过滤 (纯 Python) ---
        for href, title_text in raw_data_list:
            
            # 1. 基础过滤 (WSJ 特有规则)
            if 'cn.wsj.com' not in href:
                continue
            if any(x in href for x in ['podcasts', 'sports', 'buyside']):
                continue
            
            # 2. 排重过滤
            is_duplicate = False
            if any(is_similar(href, old_link) for _, _, old_link in old_content):
                is_duplicate = True
            if any(is_similar(href, new_link) for _, _, new_link in new_rows):
                is_duplicate = True
            
            if not is_duplicate:
                new_rows.append([formatted_datetime, title_text, href])
                new_rows1.append(["WSJCN", title_text, href])
                all_links.append(href)

        # --- 日志输出 ---
        print("-" * 40)
        if new_rows:
            print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
        else:
            print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
        print("-" * 40)

    except Exception as e:
        print("抓取过程中出现错误:", e)

    finally:
        driver.quit()

    # ================= 5. 文件写入操作 (保持原样) =================

    # 删除旧文件
    if old_file_list and os.path.exists(old_file_list[0]):
        try:
            os.remove(old_file_list[0])
            print(f"文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: {e.strerror}. 文件无法删除。")

    # 创建站点 HTML 文件 (wsj_cn.html)
    try:
        with open(NEW_HTML_PATH, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>Date</th><th>Title</th></tr>\n")
            
            for row in new_rows:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
                
            for row in old_content:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>" if row[2] else row[1]
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
            
            html_file.write("</table></body></html>")
        print(f"已更新站点文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 Site HTML 出错: {e}")

    # 创建/更新 每日新闻总表 (today_wsjcn.html)
    # 逻辑保留：使用 format_html_row 辅助函数和 DOCTYPE 写法
    if new_rows1:
        file_exists = os.path.isfile(TODAY_HTML_PATH)
        
        try:
            if file_exists:
                # 读取现有内容
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as file:
                    content = file.read()
                    # 移除结束标签
                    content = content.replace("</table></body></html>", "")
                    # 有些版本可能是带换行的，尝试移除宽松一点的结束标记
                    content = content.replace("</table>\n</body>\n</html>", "")

                # 追加新内容
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as file:
                    file.write(content)
                    for row in new_rows1:
                        file.write(format_html_row(row))
                    file.write("</table>\n</body>\n</html>")
            else:
                # 创建新文件
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as file:
                    file.write("<!DOCTYPE html>\n")
                    file.write("<html>\n<head>\n<meta charset='utf-8'>\n</head>\n<body>\n")
                    file.write("<table border='1'>\n")
                    file.write("<tr><th>site</th><th>Title</th></tr>\n")
                    for row in new_rows1:
                        file.write(format_html_row(row))
                    file.write("</table>\n</body>\n</html>")

            # 确保文件写入完成
            with open(TODAY_HTML_PATH, 'r+', encoding='utf-8') as file:
                file.flush()
                os.fsync(file.fileno())
                
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()
