import os
import re
import time
import glob
import requests
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
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
import sys
import platform

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础路径
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 3. 浏览器与驱动路径 (跨平台适配)
if platform.system() == 'Darwin':
    # macOS 配置 (保持原样)
    CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver_beta")
elif platform.system() == 'Windows':
    # Windows 配置 (默认使用标准版 Chrome)
    CHROME_BINARY_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(CHROME_BINARY_PATH):
        CHROME_BINARY_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver.exe")
else:
    # Linux
    CHROME_BINARY_PATH = "/usr/bin/google-chrome"
    CHROME_DRIVER_PATH = "/usr/bin/chromedriver"

# 4. 业务文件路径
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "nytimes.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "nytimes.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

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

# ================= [新增] 短标题黑名单 =================
# 针对那些总是抓不到完整标题、或者纯粹是网页 UI 元素的短标题，直接跳过
SHORT_TITLE_BLACKLIST = {
    "test"
}

# SHORT_TITLE_BLACKLIST = {
#     "Associated Press/Associated Press",
#     "Anthropic-White House Talks",
#     "Job Cuts on Wall Street",
#     "A.I. Arms Race",
#     "‘Jagged Intelligence’",
#     "Code Overload",
#     "Pablo Delcan",
#     "Gas Prices",
#     "Labor Secretary Steps Down",
#     "Tariff Refunds",
#     "Dispute With the Pope",
#     "Eric Lee for The New York Times",
#     "Hunt for Details",
#     "Who Was Celeste Rivas Hernandez?",
#     "Open modal at item 1 of 2",
#     "Primary Calendar",
#     "Virginia Passes New House Map"
# }

# ================= 工具函数 =================

def open_html_file(file_path):
    # <--- 跨平台修改：处理 Windows 路径反斜杠和 file:// 格式 --->
    real_path = os.path.realpath(file_path)
    if os.name == 'nt':
        url = 'file:///' + real_path.replace('\\', '/')
    else:
        url = 'file://' + real_path
    webbrowser.open(url, new=2)

def is_similar(url1, url2):
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def is_short_title(title):
    """判断标题是否过短 (少于 5 个单词 或 少于 40 个字符)"""
    if not title:
        return True
    return len(title.split()) < 5 or len(title) < 40

def fetch_full_title_via_http(url, user_agent):
    """用 requests 直接抓取 og:title 或 h1，速度远快于开新标签页"""
    try:
        headers = {"User-Agent": user_agent}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')
        # NYTimes 的 og:title 是完整标题
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        h1 = soup.find("h1", attrs={"data-testid": "headline"})
        if h1:
            return h1.get_text(strip=True)
        h1 = soup.find("h1")
        return h1.get_text(strip=True) if h1 else None
    except Exception:
        return None

def get_full_title_with_retry(driver, max_retries=3):
    """Selenium 兜底：在详情页用 JS 读取 h1 的 textContent"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    # 增加更多可能的 h1 选择器，适配 NYTimes 不同的页面结构
    h1_css = "h1[data-testid='headline'], article h1, h1.css-88wicj"
    
    for attempt in range(max_retries):
        try:
            # 稍微增加超时时间到 10 秒，应对详情页加载慢的问题
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, h1_css))
            )
            time.sleep(1) # 强制等待 JS 渲染完成
            
            # 即使有 Paywall 遮挡，textContent 依然能读取到 DOM 里的文本
            full_title = driver.execute_script(
                "const el = document.querySelector(\"h1[data-testid='headline'], article h1, h1\");"
                "return el ? el.textContent.trim() : '';"
            )
            if full_title and len(full_title) >= 10:
                return full_title
                
        except StaleElementReferenceException:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.5)
            continue
        except TimeoutException:
            return None
    return None

def main():
    current_datetime = datetime.now()
    current_year = current_datetime.year
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # ================= 1. 初始化 Selenium (核心移植部分) =================
    print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
    
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        print(f"警告：未找到 Chrome 二进制文件于 {CHROME_BINARY_PATH}，尝试使用系统默认路径...")

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
    options.add_argument("--disable-images")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.page_load_strategy = 'eager'

    # 设置 ChromeDriver
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        print("请下载对应版本的 ChromeDriver 并放置在该路径下。")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Selenium 启动失败: {e}")
        return
        
    driver.set_page_load_timeout(30)
    wait = WebDriverWait(driver, 10)

    # 初始化变量
    new_rows = []
    new_rows1 = []
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)

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
                    if final_title:
                        final_title = re.sub(r'\d+\s+MIN\s+READ', '', final_title, flags=re.IGNORECASE).strip()
                    
                    if href and final_title:
                        raw_data_list.append((href, final_title))
                        
                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue

            # --- 步骤 B.5: 针对过短的标题，获取完整标题 ---
            print("正在检查并修复过短的标题...")
            updated_raw_data_list = []

            for href, title_text in raw_data_list:
                if is_short_title(title_text):
                    # ==========================================
                    # [核心修改]：在这里判断是否在黑名单中
                    # ==========================================
                    if title_text in SHORT_TITLE_BLACKLIST:
                        print(f"命中黑名单，跳过抓取完整标题: '{title_text}'")
                        # 什么都不做，直接保留原始的 title_text 进入后续逻辑
                    else:
                        print(f"发现短标题: '{title_text}' -> 正在抓取完整标题...")
                        
                        # 优先 HTTP 方式（快）
                        full_title = fetch_full_title_via_http(href, user_agent)
                        
                        # HTTP 失败就用 Selenium 开新标签兜底
                        if not full_title or is_short_title(full_title):
                            main_handle = driver.current_window_handle
                            try:
                                driver.execute_script(f"window.open('{href}', '_blank');")
                                new_handle = [h for h in driver.window_handles if h != main_handle][-1]
                                driver.switch_to.window(new_handle)

                                # # [核心修改] 使用 Selenium 4 原生方法打开新标签页，比 JS window.open 更稳定
                                # driver.switch_to.new_window('tab')
                                # driver.get(href) # 显式导航到目标链接
                                full_title = get_full_title_with_retry(driver)
                            except Exception as e:
                                print(f"  ⚠️ Selenium 兜底失败 ({type(e).__name__})")
                                full_title = None
                            finally:
                                # # 确保关闭新标签页并切回主页面
                                # if len(driver.window_handles) > 1:
                                if driver.current_window_handle != main_handle:
                                    driver.close()
                                driver.switch_to.window(main_handle)
                        
                        if full_title and not is_short_title(full_title):
                            print(f"  ✅ 成功: '{full_title}'")
                            title_text = full_title
                        else:
                            print(f"  ⚠️ 未能获取完整标题，保留原始值。")
                
                # 无论是否命中黑名单，无论是否抓取成功，都会把数据加入新列表
                updated_raw_data_list.append((href, title_text))

            raw_data_list = updated_raw_data_list
            
            print(f"提取到 {len(raw_data_list)} 条原始数据，开始排重过滤...")
            
            # 过滤逻辑
            blacklist_urls = [
                'podcasts', 'theathletic', '/athletic/', # 体育
                '/eat/', 'television', '/music/', # 娱乐
                'sports', 'crosswords', 'cooking', # 生活
                'new-books-recommendations', 'magazine', 'wirecutter',
                '/live/', # 直播流
                '/nyregion/', # 纽约本地新闻
                '/obituaries/', # 讣告
                '/style/', # 时尚
                '/arts/', # 艺术
                '/theater/', # 戏剧
                '/books/' # 书籍
            ]
            
            for href, title_text in raw_data_list:
                lower_title = title_text.lower()
                
                # 逻辑解释：
                # 1. "xi jinping" in lower_title -> 忽略大小写 (匹配 Xi Jinping, xi jinping, XI JINPING)
                # 2. "Xi's" in title_text      -> 严格匹配 (只匹配 Xi's，不匹配 xi's 或 XI'S)
                if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                    continue
                
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
    
    # 确保目标目录存在
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)

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
                content = content.replace("</table>\n</body>\n</html>", "")
                
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