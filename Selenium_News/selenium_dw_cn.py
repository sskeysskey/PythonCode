import os
import re
import glob
import time
import shutil
import platform
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

# ================= 配置区域 (DW 专用) =================

USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 浏览器与驱动路径
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
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "de_cn.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "de_cn.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_dwcn.html")

# ================= 重试与抓取配置 =================
MAX_RETRIES = 3          # 最多尝试次数
RETRY_DELAY = 5          # 每次失败后基础等待秒数
PAGE_LOAD_TIMEOUT = 30   # 页面加载超时(秒)

# 🚫 定义屏蔽黑名单
BLOCK_KEYWORDS = [
    # 标题关键词
    "订阅新闻", "数据保护", "责任声明", "无障碍内容声明", "隐私政策", 
    "关于我们", "德广联", "DW 简介", "版本说明", "联系我们",
    # URL 关键词
    "legal-notice", "accessibility-statement", "data-protection", 
    "newsletter-registration", "about-dw", "contact"
]

# ================= 自定义异常与工具函数 =================

class EmptyResultError(Exception):
    """过滤前抓取到 0 条原始数据，视为抓取失败，触发重试"""
    pass

def is_similar(url1, url2):
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    return f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}" == \
           f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"

def format_html_row(row):
    site, title, link = row
    clickable_title = f'<a href="{link}" target="_blank">{title}</a>'
    return f"<tr><td>{site}</td><td>{clickable_title}</td></tr>\n"

def create_driver():
    """创建并返回独立的 Chrome WebDriver 实例"""
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH

    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # 性能与反卡死配置
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
        return old_content, old_file_list, True  # 首次运行无旧文件，属于正常情况
    
    try:
        with open(old_file_list[0], 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            all_rows = soup.find_all('tr')
            if len(all_rows) > 1:
                for row in all_rows[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        date_str = cols[0].text.strip()
                        try:
                            if datetime.strptime(date_str, '%Y_%m_%d_%H') >= (current_datetime - timedelta(days=30)):
                                t = cols[1].text.strip()
                                l = cols[1].find('a')['href'] if cols[1].find('a') else None
                                old_content.append([date_str, t, l])
                        except ValueError:
                            continue
        return old_content, old_file_list, True
    except Exception as e:
        print(f"读取旧文件警告: {e}")
        return old_content, old_file_list, False

# ================= 核心抓取函数 =================

def scrape_dw(old_content, formatted_datetime):
    """
    单次抓取 DW 逻辑。
    成功返回 (new_rows, new_rows1)；
    若未抓取到任何原始元素或发生异常，抛出异常交由外层重试。
    """
    driver = None
    new_rows = []
    new_rows1 = []

    try:
        print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
        driver = create_driver()

        print("正在访问 DW CN...")
        try:
            driver.get("https://www.dw.com/zh/")
        except TimeoutException:
            print("⚠️ 页面加载超时（eager 模式），尝试继续执行...")

        # 1. 尝试处理 Privacy 隐私弹窗
        try:
            wait = WebDriverWait(driver, 5)
            agree_xpath = "//button[contains(., '同意')] | //button[contains(., 'Accept')]"
            agree_button = wait.until(EC.element_to_be_clickable((By.XPATH, agree_xpath)))
            agree_button.click()
            print("✅ 已点击同意隐私条款。")
            time.sleep(1)
        except Exception:
            print("ℹ️ 未检测到弹窗或自动跳过。")

        # 2. 深度滚动页面以加载 React 动态内容
        print("开始深度滚动页面 (4次)...")
        for _ in range(4):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.5)
        print("滚动完成。")

        # 3. 等待并提取带 /a- 的文章元素
        print("开始扫描元素...")
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/a-')]")))
        except TimeoutException:
            print("⚠️ 等待文章元素超时，尝试直接获取...")

        elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/a-')]")
        print(f"页面上共发现 {len(elements)} 个潜在链接元素，开始提取文本...")

        raw_data_list = []
        for element in elements:
            try:
                href = element.get_attribute('href')
                
                # 多层文本回退提取
                title_text = element.text.strip()
                if not title_text:
                    title_text = element.get_attribute("textContent").strip()
                if not title_text:
                    title_text = element.get_attribute("title") or ""
                if not title_text:
                    try:
                        inner = element.find_element(By.XPATH, ".//h2 | .//h3 | .//span")
                        title_text = inner.get_attribute("textContent").strip()
                    except Exception:
                        pass

                if href and title_text:
                    if not href.startswith('http'):
                        href = "https://www.dw.com" + href
                    raw_data_list.append((href, title_text))

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        # ===== 关键判断：原始抓取结果为 0，视为抓取失败触发重试 =====
        if len(raw_data_list) == 0:
            try:
                dump_path = os.path.join(DOWNLOADS_DIR, f"dw_empty_{formatted_datetime}_{int(time.time())}.html")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"   已保存空页面快照: {dump_path}")
            except Exception:
                pass
            raise EmptyResultError(f"抓取到的原始数据为 0 条，可能是页面未渲染完全或被拦截。")

        print(f"解析完成，获得 {len(raw_data_list)} 条原始数据，开始逻辑排重与过滤...")

        # 4. 逻辑过滤与排重
        seen_links = set()
        for href, title_text in raw_data_list:
            if 'dw.com' not in href:
                continue

            # 过滤非文章及多媒体
            if any(x in href for x in ['/av-', '/media-center', 'search?', 'tv-programs']):
                continue

            # 校验 DW 文章 ID 格式 (/a-数字)
            if not re.search(r'/a-\d+', href):
                continue

            # 黑名单过滤
            if any(kw in title_text or kw in href for kw in BLOCK_KEYWORDS):
                continue

            link_key = href.split('?')[0]
            if link_key in seen_links:
                continue
            seen_links.add(link_key)

            # 历史与本轮去重
            if any(is_similar(href, old_link) for _, _, old_link in old_content):
                continue
            if any(is_similar(href, new_link) for _, _, new_link in new_rows):
                continue

            clean_title = title_text.replace('\n', ' ').strip()
            if len(clean_title) > 2:
                new_rows.append([formatted_datetime, clean_title, href])
                new_rows1.append(["DW", clean_title, href])

        print("-" * 40)
        if new_rows:
            print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条 DW 新闻！")
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

    # 1. 读取历史数据
    old_content, old_file_list, old_content_loaded = load_old_content(current_datetime)
    if not old_content_loaded:
        print("❌ 旧数据未能成功读取，为保护历史数据，终止执行！")
        return

    # 2. 循环重试机制
    new_rows, new_rows1 = [], []
    scrape_success = False

    for attempt in range(1, MAX_RETRIES + 1):
        print("\n" + "=" * 50)
        print(f"🔄 DW CN 第 {attempt}/{MAX_RETRIES} 次尝试抓取...")
        print("=" * 50)
        try:
            new_rows, new_rows1 = scrape_dw(old_content, formatted_datetime)
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

    # 4. 备份历史文件
    if os.path.exists(NEW_HTML_PATH):
        backup_path = NEW_HTML_PATH + f".bak_{formatted_datetime}"
        shutil.copy2(NEW_HTML_PATH, backup_path)
        print(f"📦 已备份到: {backup_path}")

        # 保留最近 5 个备份
        backups = sorted(glob.glob(NEW_HTML_PATH + ".bak_*"))
        for old_bak in backups[:-5]:
            try:
                os.remove(old_bak)
            except OSError:
                pass

    # 5. 写入站点 HTML
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    try:
        with open(NEW_HTML_PATH, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>Date</th><th>Title</th></tr>\n")
            for row in new_rows:
                html_file.write(f"<tr><td>{row[0]}</td><td><a href='{row[2]}' target='_blank'>{row[1]}</a></td></tr>\n")
            for row in old_content:
                l = row[2] if row[2] else "#"
                html_file.write(f"<tr><td>{row[0]}</td><td><a href='{l}' target='_blank'>{row[1]}</a></td></tr>\n")
            html_file.write("</table></body></html>")
        print(f"已更新站点文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 Site HTML 出错: {e}")

    # 6. 追加到每日总表
    if new_rows1:
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