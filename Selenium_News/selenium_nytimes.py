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

# ================= 新增：重试相关配置 =================
MAX_RETRIES = 3          # 最多尝试次数
RETRY_DELAY = 5          # 每次失败后等待秒数
PAGE_LOAD_TIMEOUT = 45   # 页面加载超时(秒)，适当调大

# ================= 垃圾标题过滤库 =================
# 如果抓到的标题完全等于这些词，或者包含这些词（纯大写时），则认为是噪音
GENERIC_LABELS = {
    "ANALYSIS", "OPINION", "GUEST ESSAY", "THE MORNING", "BRIEFING", 
    "THE DAILY", "LISTEN", "WATCH", "LIVE", "INTERACTIVE", "PHOTOS",
    "THE EDITORIAL BOARD", "THE INTERVIEW", "COOKING", "CROSSWORDS",
    "THE ATHLETIC", "WIRECUTTER"
}

# ================= 工具函数 =================
class EmptyResultError(Exception):
    """过滤前抓取到 0 条数据,视为抓取失败,需要重试"""
    pass

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


def create_driver():
    """创建并返回一个新的 Chrome WebDriver 实例。"""
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

    # --- 防止渲染进程被后台节流/挂起（从重试版代码引入） ---
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    options.page_load_strategy = 'eager'

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def load_old_content(current_datetime):
    """读取旧 HTML 文件中的历史内容。"""
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)
    if old_file_list:
        old_file_path = old_file_list[0]
        seven_days_ago = current_datetime - timedelta(days=30)
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
    return old_content, old_file_list


def scrape_nytimes(old_content, current_datetime, formatted_datetime, current_year):
    """
    实际执行 NYTimes 抓取的函数。
    成功返回 (new_rows, new_rows1)；失败则抛出异常，由外层重试。
    """
    driver = None
    new_rows = []
    new_rows1 = []

    try:
        print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
        driver = create_driver()

        print("正在访问 NYTimes...")
        try:
            driver.get("https://www.nytimes.com/")
        except TimeoutException:
            print("⚠️ driver.get 超时（eager 模式），尝试继续检查页面内容...")

        wait = WebDriverWait(driver, 10)

        # --- 滚动页面 ---
        print("开始滚动页面...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.5)
        print("滚动完成，开始抓取。")

        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, f"a[href*='/{current_year}/']")
            ))
        except TimeoutException:
            print("⚠️ 等待文章链接超时,仍尝试直接抓取...")

        link_elements = driver.find_elements(By.CSS_SELECTOR, f"a[href*='/{current_year}/']")

        # 兜底:万一年份跨年/链接格式变了,退回抓所有带 /20xx/ 的链接
        if not link_elements:
            link_elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/20']")

        raw_data_list = []

        # === [核心逻辑保留]：智能提取真正的标题 ===
        for link in link_elements:
            try:
                href = link.get_attribute('href')
                final_title = ""
                # 1. 优先尝试找 h3 (最标准的标题)
                try:
                    h3_text = link.find_element(By.TAG_NAME, "h3").text.strip()
                    if h3_text and h3_text.upper() not in GENERIC_LABELS:
                        final_title = h3_text
                except Exception:
                    pass

                # 2. 如果 h3 不存在或被判定为垃圾词，尝试找 p (摘要/副标题)
                if not final_title:
                    try:
                        ps = link.find_elements(By.TAG_NAME, "p")
                        valid_ps = [p.text.strip() for p in ps if p.text.strip().upper() not in GENERIC_LABELS]
                        if valid_ps:
                            final_title = max(valid_ps, key=len)
                    except Exception:
                        pass

                # 3. 如果还是没有，获取整个 Link 的文本，并按行拆分，取最长的一行
                if not final_title:
                    full_text = link.text.strip() or link.get_attribute('innerText').strip()
                    if full_text:
                        parts = full_text.split('\n')
                        valid_parts = [
                            p.strip() for p in parts
                            if p.strip().upper() not in GENERIC_LABELS and len(p.strip()) > 3
                        ]
                        if valid_parts:
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

        # ===== 关键:过滤前为 0 条,判定为抓取失败,交给外层重试 =====
        if len(raw_data_list) == 0:
            page_len = len(driver.page_source or "")

            try:
                dump = os.path.join(DOWNLOADS_DIR, f"nyt_empty_{formatted_datetime}_{int(time.time())}.html")
                with open(dump, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"   已保存空结果页面快照: {dump}")
            except Exception:
                pass

            raise EmptyResultError(
                f"过滤前抓取到 0 条原始数据(匹配 /{current_year}/ 的链接数={len(link_elements)}, "
                f"page_source 长度={page_len}),可能是页面未加载完成或被反爬拦截"
            )
        
        print(f"提取到 {len(raw_data_list)} 条原始数据，开始排重过滤...")

        # 过滤逻辑（保持原样）
        blacklist_urls = [
            'podcasts', 'theathletic', '/athletic/',
            '/eat/', 'television', '/music/',
            'sports', 'crosswords', 'cooking',
            'new-books-recommendations', 'magazine', 'wirecutter',
            '/live/',
            '/nyregion/',
            '/obituaries/',
            '/style/',
            '/arts/',
            '/theater/',
            '/books/'
        ]

        for href, title_text in raw_data_list:
            lower_title = title_text.lower()

            # 政治敏感过滤
            if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                continue

            # 1. 标题长度硬性过滤
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

        return new_rows, new_rows1

    except EmptyResultError as e:
        print(f"⚠️ 抓取结果为空: {e}")
        raise
    except Exception as e:
        print("抓取过程中出现错误:", e)
        raise

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    current_datetime = datetime.now()
    current_year = current_datetime.year
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # 驱动文件存在性检查
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        print("请下载对应版本的 ChromeDriver 并放置在该路径下。")
        return

    # 1. 先读取旧内容（与浏览器无关，只做一次）
    old_content, old_file_list = load_old_content(current_datetime)

    # 2. 带重试的抓取
    new_rows, new_rows1 = [], []
    scrape_success = False

    for attempt in range(1, MAX_RETRIES + 1):
        print("\n" + "=" * 50)
        print(f"🔄 第 {attempt}/{MAX_RETRIES} 次尝试抓取...")
        print("=" * 50)
        try:
            new_rows, new_rows1 = scrape_nytimes(
                old_content, current_datetime, formatted_datetime, current_year
            )
            scrape_success = True
            break  # 成功就跳出重试循环
        except Exception as e:
            print(f"❌ 第 {attempt} 次尝试失败: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES:
                wait_sec = RETRY_DELAY * attempt      # 5s → 10s → ...
                print(f"   等待 {wait_sec} 秒后重建浏览器重试...")
                time.sleep(wait_sec)
            else:
                print("   已达到最大重试次数，放弃本次抓取。")

    if not scrape_success:
        print("⚠️ 所有重试均失败，本次不更新任何文件，安全退出。")
        return

    # --- 3. 文件写入（只有抓取成功才执行） ---

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