import os
import glob
import time
import webbrowser
from bs4 import BeautifulSoup
from selenium import webdriver
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# ================= 配置区域 (移植自 b.py) =================

# 1. 浏览器与驱动路径 (改为 Beta 版配置)
CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
CHROME_DRIVER_PATH = "/Users/yanzhang/Downloads/backup/chromedriver_beta"

# 2. 文件路径 (保持 a.py 原有配置)
OLD_FILE_PATTERN = "/Users/yanzhang/Coding/News/backup/site/technologyreview.html"
NEW_HTML_PATH = "/Users/yanzhang/Coding/News/backup/site/technologyreview.html"
TODAY_HTML_PATH = "/Users/yanzhang/Coding/News/today_eng.html"

# ================= 工具函数 =================

def open_html_file(file_path):
    webbrowser.open('file://' + os.path.realpath(file_path), new=2)

def main():
    # 获取当前日期
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # ================= 1. 初始化 Selenium (核心移植部分) =================
    print("正在初始化 Chrome Beta 驱动...")
    
    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_BINARY_PATH  # 指定 Beta 浏览器位置

    # --- Headless模式 & 伪装设置 ---
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    
    # --- 伪装设置 (User-Agent & 去除自动化特征) ---
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
    options.add_argument("--blink-settings=imagesEnabled=false")  # 禁用图片加载
    options.page_load_strategy = 'eager'

    # 设置 ChromeDriver
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    
    # 容器初始化
    new_rows = []
    new_rows1 = []
    old_content = []
    
    try:
        # 打开 MIT Technology Review 网站
        print("正在访问 MIT Technology Review...")
        driver.get("https://www.technologyreview.com/")

        # ================= 2. 滚动加载 (移植自 b.py) =================
        print("开始滚动页面以加载更多内容...")
        for i in range(3):  # 滚动3次，可根据需要调整
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(1)
        print("滚动完成。")

        # ================= 3. 读取旧文件逻辑 (保持 a.py 原有逻辑) =================
        old_file_list = glob.glob(OLD_FILE_PATTERN)
        
        if old_file_list:
            old_file_path = old_file_list[0]
            # 这里改成保留更长时间的数据，防止误删，比如40天
            seven_days_ago = current_datetime - timedelta(days=40)
            try:
                with open(old_file_path, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    rows = soup.find_all('tr')[1:]  # 跳过标题行
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

        # ================= 4. 抓取新内容 (Snapshot 策略移植) =================
        
        # 获取所有旧链接用于排重
        all_links = [old_link for _, _, old_link in old_content if old_link]

        # 构造选择器：针对今年的文章
        css_selector = f"a[href*='technologyreview.com/{current_datetime.year}/']"
        
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            
            # --- 步骤 A: 获取元素对象 ---
            titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
            print(f"找到了 {len(titles_elements)} 个潜在链接元素。")

            # --- 步骤 B: 快速提取数据 (避免 StaleElementReferenceException) ---
            raw_data_list = []
            for element in titles_elements:
                try:
                    href = element.get_attribute('href')
                    # 尝试获取标题，优先查找内部的h2/h3，如果没有则取自身的text
                    try:
                        title_text = element.find_element(By.CSS_SELECTOR, "h2, h3").text.strip()
                    except:
                        title_text = element.text.strip() or element.get_attribute('innerText').strip()
                    
                    if href and title_text:
                        raw_data_list.append((href, title_text))
                except StaleElementReferenceException:
                    continue # 元素失效则跳过
                except Exception:
                    continue

            print(f"成功提取了 {len(raw_data_list)} 条原始数据，开始过滤...")

            # --- 步骤 C: 逻辑过滤 (纯 Python 处理) ---
            for href, title_text in raw_data_list:
                # 1. Podcast 过滤 (a.py 原有逻辑)
                if 'podcasts' in href:
                    continue
                
                # 2. 排重过滤
                is_duplicate = False
                # 检查是否已在旧内容中
                if any(href == old_link for _, _, old_link in old_content):
                    is_duplicate = True
                # 检查是否已在本次新抓取队列中
                if any(href == new_link for _, _, new_link in new_rows):
                    is_duplicate = True
                
                if not is_duplicate:
                    new_rows.append([formatted_datetime, title_text, href])
                    new_rows1.append(["TechReview", title_text, href])
                    all_links.append(href)

            # --- 日志输出 (移植自 b.py) ---
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

    # ================= 5. 文件写入操作 (保持 a.py 原有逻辑) =================

    # 删除旧文件
    if old_file_list and os.path.exists(old_file_list[0]):
        try:
            os.remove(old_file_list[0])
            print(f"旧文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: {e.strerror}. 文件无法删除。")

    # 创建 site HTML 文件
    try:
        with open(NEW_HTML_PATH, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>Date</th><th>Title</th></tr>\n")
            
            # 写入新内容
            for row in new_rows:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
            
            # 写入旧内容
            for row in old_content:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>" if row[2] else row[1]
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
            
            html_file.write("</table></body></html>")
            print(f"已更新站点文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 HTML 出错: {e}")

    # 创建/更新每日新闻总表 (today_eng.html)
    if new_rows1:
        closing_tag = "</table></body></html>"
        file_exists = os.path.isfile(TODAY_HTML_PATH)
        
        # 准备追加内容
        append_content = ""
        for row in new_rows1:
            clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
            append_content += f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n"

        try:
            if not file_exists:
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write("<html><body><table border='1'>\n")
                    html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
                    html_file.write(append_content)
                    html_file.write(closing_tag)
            else:
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as html_file:
                    content = html_file.read()
                
                if closing_tag in content:
                    content = content.replace(closing_tag, "")
                
                new_file_content = content + append_content + closing_tag
                
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write(new_file_content)
            
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()
