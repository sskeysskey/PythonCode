import os
import re
import time
import glob
import webbrowser
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# ================= 配置区域 =================

# 1. 路径配置
CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
CHROME_DRIVER_PATH = "/Users/yanzhang/Downloads/backup/chromedriver_beta"

# 文件路径
FILE_PATTERN = "/Users/yanzhang/Coding/News/backup/site/nytimes.html"
NEW_HTML_PATH = "/Users/yanzhang/Coding/News/backup/site/nytimes.html"
TODAY_HTML_PATH = "/Users/yanzhang/Coding/News/today_eng.html"

# 设置超时时间
TIMEOUT = 20 

# ================= 垃圾标题过滤库 =================
# 如果抓到的标题完全等于这些词，或者包含这些词（纯大写时），则认为是噪音
GENERIC_LABELS = {
    "ANALYSIS", "OPINION", "GUEST ESSAY", "THE MORNING", "BRIEFING", 
    "THE DAILY", "LISTEN", "WATCH", "LIVE", "INTERACTIVE", "PHOTOS",
    "THE EDITORIAL BOARD", "THE INTERVIEW", "COOKING", "CROSSWORDS",
    "THE ATHLETIC", "WIRECUTTER"
}

# ================= 工具函数 =================

def open_html_file(file_path):
    webbrowser.open('file://' + os.path.realpath(file_path), new=2)

def is_similar(url1, url2):
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def main():
    current_datetime = datetime.now()
    current_year = current_datetime.year
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # --- 1. 初始化 Selenium ---
    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_BINARY_PATH 
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')

    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # 性能优化
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.page_load_strategy = 'eager'

    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    wait = WebDriverWait(driver, 10)

    # 初始化变量
    new_rows = []
    new_rows1 = []
    old_content = []
    old_file_list = glob.glob(FILE_PATTERN)

    try:
        print("正在访问 NYTimes...")
        driver.get("https://www.nytimes.com/")

        # --- 3. 查找旧文件 ---
        if old_file_list:
            old_file_path = old_file_list[0]
            current_date = datetime.now()
            seven_days_ago = current_date - timedelta(days=30)
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
            except Exception as e:
                print(f"读取旧文件出错: {e}")

        # --- 4. 抓取新内容 ---
        print("开始滚动页面...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.5)
        print("滚动完成，开始抓取。")

        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
            
            # 查找所有 href 中包含当前年份的链接
            link_elements = driver.find_elements(By.CSS_SELECTOR, f"a[href*='/{current_year}/']")
            
            raw_data_list = []
            
            # === [核心逻辑修改]：智能提取真正的标题 ===
            for link in link_elements:
                try:
                    href = link.get_attribute('href')
                    final_title = ""

                    # 1. 优先尝试找 h3 (最标准的标题)
                    try:
                        h3_text = link.find_element(By.TAG_NAME, "h3").text.strip()
                        if h3_text and h3_text.upper() not in GENERIC_LABELS:
                            final_title = h3_text
                    except:
                        pass

                    # 2. 如果 h3 不存在或被判定为垃圾词，尝试找 p (摘要/副标题)
                    if not final_title:
                        try:
                            # 找内容最长的一个 p 标签
                            ps = link.find_elements(By.TAG_NAME, "p")
                            valid_ps = [p.text.strip() for p in ps if p.text.strip().upper() not in GENERIC_LABELS]
                            if valid_ps:
                                final_title = max(valid_ps, key=len) # 取最长的
                        except:
                            pass
                    
                    # 3. 如果还是没有，获取整个 Link 的文本，并按行拆分，取最长的一行
                    #    这能有效解决 "ANALYSIS\nTrump Plunges..." 的问题
                    if not final_title:
                        full_text = link.text.strip() or link.get_attribute('innerText').strip()
                        if full_text:
                            # 按换行符拆分
                            parts = full_text.split('\n')
                            # 过滤掉垃圾词和太短的词
                            valid_parts = [p.strip() for p in parts if p.strip().upper() not in GENERIC_LABELS and len(p.strip()) > 3]
                            if valid_parts:
                                # 假设真正的标题是里面最长的那段话
                                final_title = max(valid_parts, key=len)

                    # 4. 清理标题中的 "MIN READ" 等噪音
                    final_title = re.sub(r'\d+\s+MIN\s+READ', '', final_title, flags=re.IGNORECASE).strip()
                    
                    if href and final_title:
                        raw_data_list.append((href, final_title))
                        
                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue

            print(f"提取到 {len(raw_data_list)} 条原始数据，开始排重过滤...")

            # 过滤逻辑
            blacklist_urls = [
                'podcasts', 'theathletic', '/athletic/', # 体育
                '/eat/', 'television', '/music/', # 娱乐
                'sports', 'crosswords', 'cooking', # 生活
                'new-books-recommendations', 'magazine', 'wirecutter',
                '/live/', # 直播流
                '/nyregion/', # 纽约本地新闻 (新添加)
                '/obituaries/', # 讣告 (通常不需要)
                '/style/', # 时尚
                '/arts/', # 艺术
                '/theater/' # 戏剧
            ]

            for href, title_text in raw_data_list:
                
                # 1. 标题长度硬性过滤 (防止漏网的 "Live" 或 "Video")
                if len(title_text) < 5:
                    continue

                # 2. URL 黑名单过滤
                if any(sub.lower() in href.lower() for sub in blacklist_urls):
                    continue
                
                # 3. 排重
                is_old = any(is_similar(href, old_link) for _, _, old_link in old_content)
                is_new = any(is_similar(href, new_link) for _, _, new_link in new_rows)
                
                if not is_old and not is_new:
                    new_rows.append([formatted_datetime, title_text, href])
                    new_rows1.append(["nytimes", title_text, href])

            # 日志
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

    # --- 5. 文件写入 ---
    if old_file_list:
        try:
            if os.path.exists(old_file_list[0]):
                os.remove(old_file_list[0])
        except OSError:
            pass

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
        print(f"已更新文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 HTML 出错: {e}")

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
