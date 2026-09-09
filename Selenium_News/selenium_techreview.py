import os
import glob
import time
import shutil
import platform
import webbrowser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse

# --- Selenium 组件 ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

# ================= 配置区域 =================

USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 浏览器与驱动路径 (跨平台适配)
if platform.system() == 'Darwin':
    CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver_beta")
elif platform.system() == 'Windows':
    CHROME_BINARY_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(CHROME_BINARY_PATH):
        CHROME_BINARY_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver.exe")
else:
    CHROME_BINARY_PATH = "/usr/bin/google-chrome"
    CHROME_DRIVER_PATH = "/usr/bin/chromedriver"

# 业务文件路径
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "technologyreview.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "technologyreview.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# ================= 重试与性能配置 =================
MAX_RETRIES = 3          # 最多尝试次数
RETRY_DELAY = 5          # 每次失败后基础等待秒数
PAGE_LOAD_TIMEOUT = 30   # 页面加载超时(秒)

# ================= 自定义异常与工具函数 =================

class EmptyResultError(Exception):
    """抓取到的原始数据为 0 条，视为抓取异常，触发重试"""
    pass

def open_html_file(file_path):
    """跨平台本地打开 HTML"""
    real_path = os.path.realpath(file_path)
    url = ('file:///' + real_path.replace('\\', '/')) if os.name == 'nt' else ('file://' + real_path)
    webbrowser.open(url, new=2)

def format_html_row(row):
    site, title, link = row
    clickable_title = f'<a href="{link}" target="_blank">{title}</a>'
    return f"<tr><td>{site}</td><td>{clickable_title}</td></tr>\n"

def create_driver():
    """创建并返回配置优化的独立 Chrome WebDriver 实例"""
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH

    # Headless 模式与特征隐藏
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # 性能优化 & 资源节约
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-images")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.page_load_strategy = 'eager'

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver

def load_old_content(current_datetime):
    """读取旧 HTML 文件，返回 (old_content, old_file_list, is_success)"""
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)

    if not old_file_list:
        return old_content, old_file_list, True

    try:
        old_file_path = old_file_list[0]
        forty_days_ago = current_datetime - timedelta(days=40)
        with open(old_file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            rows = soup.find_all('tr')[1:]
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    date_str = cols[0].text.strip()
                    try:
                        date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                        if date >= forty_days_ago:
                            title_col = cols[1]
                            title = title_col.text.strip()
                            link = title_col.find('a')['href'] if title_col.find('a') else None
                            old_content.append([date_str, title, link])
                    except ValueError:
                        continue
        return old_content, old_file_list, True
    except Exception as e:
        print(f"读取旧文件警告: {e}")
        return old_content, old_file_list, False

# ================= 核心抓取函数 =================

def scrape_techreview(old_content, formatted_datetime, current_datetime):
    """
    单次抓取 TechReview。
    若未抓取到有效文章元素或出现异常，会抛出异常交由外层重试。
    """
    driver = None
    new_rows = []
    new_rows1 = []

    try:
        print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
        driver = create_driver()

        print("正在访问 MIT Technology Review...")
        try:
            driver.get("https://www.technologyreview.com/")
        except TimeoutException:
            print("⚠️ 页面加载超时（eager 模式），尝试继续执行...")

        # 1. 滚动页面以加载动态内容
        print("开始滚动页面以加载更多内容...")
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.8)
        print("滚动完成。")

        # 2. 定位当年的文章链接
        css_selector = f"a[href*='technologyreview.com/{current_datetime.year}/']"
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
        except TimeoutException:
            print("⚠️ 等待文章选择器超时，尝试直接获取...")

        titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
        print(f"页面上共发现 {len(titles_elements)} 个潜在链接元素，开始提取文本...")

        raw_data_list = []
        for element in titles_elements:
            try:
                href = element.get_attribute('href')
                try:
                    title_text = element.find_element(By.CSS_SELECTOR, "h2, h3").text.strip()
                except Exception:
                    title_text = element.text.strip() or element.get_attribute('innerText').strip()

                if href and title_text:
                    raw_data_list.append((href, title_text))
            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        # ===== 关键判断：若原始元素为 0，保存快照并触发重试 =====
        if len(raw_data_list) == 0:
            try:
                dump_path = os.path.join(DOWNLOADS_DIR, f"techreview_empty_{formatted_datetime}_{int(time.time())}.html")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"   已保存空页面快照: {dump_path}")
            except Exception:
                pass
            raise EmptyResultError("抓取到的原始数据为 0 条，可能是页面未渲染完全或被阻断。")

        print(f"成功提取了 {len(raw_data_list)} 条原始数据，开始逻辑过滤与排重...")

        # 3. 过滤与排重逻辑
        for href, title_text in raw_data_list:
            lower_title = title_text.lower()

            # 关键词过滤
            if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                continue

            # Podcast 过滤
            if 'podcasts' in href:
                continue

            # 排重检查 (同时比对旧内容和本轮已加入内容)
            if any(href == old_link for _, _, old_link in old_content):
                continue
            if any(href == new_link for _, _, new_link in new_rows):
                continue

            clean_title = title_text.replace('\n', ' ').strip()
            if len(clean_title) > 2:
                new_rows.append([formatted_datetime, clean_title, href])
                new_rows1.append(["TechReview", clean_title, href])

        print("-" * 40)
        if new_rows:
            print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条 TechReview 新闻！")
        else:
            print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
        print("-" * 40)

        return new_rows, new_rows1

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

# ================= 主控制流程 =================

def main():
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    # 1. 安全读取历史数据
    old_content, old_file_list, old_content_loaded = load_old_content(current_datetime)
    if not old_content_loaded:
        print("❌ 旧数据未能成功读取，为保护历史数据，终止执行！")
        return

    # 2. 循环重试机制
    new_rows, new_rows1 = [], []
    scrape_success = False

    for attempt in range(1, MAX_RETRIES + 1):
        print("\n" + "=" * 50)
        print(f"🔄 TechReview 第 {attempt}/{MAX_RETRIES} 次尝试抓取...")
        print("=" * 50)
        try:
            new_rows, new_rows1 = scrape_techreview(old_content, formatted_datetime, current_datetime)
            scrape_success = True
            break
        except Exception as e:
            print(f"❌ 第 {attempt} 次抓取失败: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES:
                wait_sec = RETRY_DELAY * attempt
                print(f"   等待 {wait_sec} 秒后重建浏览器重试...")
                time.sleep(wait_sec)
            else:
                print("   已达到最大重试次数，放弃本次抓取。")

    # 3. 熔断保护与校验
    if not scrape_success:
        print("❌ 本次抓取所有重试均失败，为保护历史数据，拒绝写入并安全退出！")
        return

    if not new_rows and not old_content:
        print("❌ 新旧数据都为空，拒绝写入空文件！")
        return

    # 4. 备份历史文件并保留最近 5 个备份
    if os.path.exists(NEW_HTML_PATH):
        backup_path = NEW_HTML_PATH + f".bak_{formatted_datetime}"
        try:
            shutil.copy2(NEW_HTML_PATH, backup_path)
            print(f"📦 已备份到: {backup_path}")

            backups = sorted(glob.glob(NEW_HTML_PATH + ".bak_*"))
            for old_bak in backups[:-5]:
                try:
                    os.remove(old_bak)
                except OSError:
                    pass
        except Exception as e:
            print(f"备份旧文件提示: {e}")

    # 5. 写入站点 HTML 文件
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
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

    # 6. 追加到每日总表 (today_eng.html)
    if new_rows1:
        os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)
        try:
            mode = 'r+' if os.path.exists(TODAY_HTML_PATH) else 'w'
            if mode == 'r+':
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as f:
                    c = f.read().replace("</table></body></html>", "").replace("</table>\n</body>\n</html>", "")
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as f:
                    f.write(c)
                    for r in new_rows1:
                        f.write(format_html_row(r))
                    f.write("</table>\n</body>\n</html>")
            else:
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as f:
                    f.write("<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><table border='1'>\n")
                    f.write("<tr><th>site</th><th>Title</th></tr>\n")
                    for r in new_rows1:
                        f.write(format_html_row(r))
                    f.write("</table>\n</body>\n</html>")
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()