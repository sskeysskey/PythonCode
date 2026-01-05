import os
import glob
import time
# import pyautogui  # 移除：Headless模式下无法使用GUI操作，已改用JS滚动
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# ================= 配置区域 =================

# 1. 浏览器与驱动路径 (Beta 版配置)
CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
CHROME_DRIVER_PATH = "/Users/yanzhang/Downloads/backup/chromedriver_beta"

# 2. 文件路径
OLD_FILE_PATTERN = "/Users/yanzhang/Coding/News/backup/site/washingtonpost.html"
NEW_HTML_PATH = "/Users/yanzhang/Coding/News/backup/site/washingtonpost.html"
TODAY_HTML_PATH = "/Users/yanzhang/Coding/News/today_eng.html"

# ================= 工具函数 =================

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度 (忽略协议和参数差异)
    """
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

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
        # 打开 WashingtonPost 网站
        print("正在访问 Washington Post...")
        driver.get("https://www.washingtonpost.com/")

        # ================= 2. 滚动加载 (替代 pyautogui) =================
        # 使用 JS 滚动，更稳定且支持 Headless
        print("开始滚动页面...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.5)
        print("滚动完成。")

        # ================= 3. 读取旧文件逻辑 =================
        old_file_list = glob.glob(OLD_FILE_PATTERN)
        if old_file_list:
            old_file_path = old_file_list[0]
            # 保持原逻辑：保留10天内的数据
            seven_days_ago = current_datetime - timedelta(days=10)
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

        # ================= 4. 抓取新内容 (Snapshot 策略) =================
        
        # 既有的所有链接（用于排重）
        all_links = [old_link for _, _, old_link in old_content]

        # 动态生成年份选择器，避免硬编码 2025
        # 逻辑：查找包含当前年份链接的文章
        css_selector = f"a[href*='/{current_datetime.year}/']:not(.label-link)"
        
        try:
            # 等待元素加载
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
                    # 尝试获取标题，优先查找内部 h2/h3，兼容性处理
                    try:
                        title_text = element.find_element(By.CSS_SELECTOR, "h2, h3").text.strip()
                    except:
                        title_text = element.text.strip() or element.get_attribute('innerText').strip()
                    
                    if href and title_text:
                        raw_data_list.append((href, title_text))
                except StaleElementReferenceException:
                    continue 
                except Exception:
                    continue
            
            print(f"成功提取了 {len(raw_data_list)} 条原始数据，开始过滤...")

            # --- 步骤 C: 逻辑过滤 (纯 Python 处理) ---
            # 定义排除关键字
            exclude_keywords = ['podcasts', 'sports', '/music/', 'weather', '/books/', 'food']

            for href, title_text in raw_data_list:
                # 1. 关键字过滤
                if any(keyword in href for keyword in exclude_keywords):
                    continue

                # 2. 排重过滤 (使用 is_similar)
                # 检查旧内容
                if any(is_similar(href, old_link) for _, _, old_link in old_content):
                    continue
                # 检查本次新内容
                if any(is_similar(href, new_link) for _, _, new_link in new_rows):
                    continue
                
                # 通过所有检查，添加数据
                new_rows.append([formatted_datetime, title_text, href])
                new_rows1.append(["WashingtonPost", title_text, href])
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

    # ================= 5. 文件写入操作 =================

    # 删除旧文件
    if old_file_list and os.path.exists(old_file_list[0]):
        try:
            os.remove(old_file_list[0])
            print(f"文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: {e.strerror}. 文件无法删除。")

    # 创建 Site HTML 文件
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

    # 创建/更新 每日新闻总表
    if new_rows1:
        file_exists = os.path.isfile(TODAY_HTML_PATH)
        closing_tag = "</table></body></html>"
        
        append_content = ""
        for row in new_rows1:
            clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
            append_content += f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n"
        
        try:
            if file_exists:
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as html_file:
                    content = html_file.read()
                
                if closing_tag in content:
                    content = content.replace(closing_tag, "")
                
                new_content = content + append_content + closing_tag
                
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write(new_content)
            else:
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write("<html><body><table border='1'>\n")
                    html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
                    html_file.write(append_content)
                    html_file.write(closing_tag)
            
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()
