import os
import time
import glob
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
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
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "economist.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "economist.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# 设置超时时间
TIMEOUT = 20

# 重试相关配置 (从 a.py 移植)
MAX_RETRIES = 3          # 最多尝试次数
RETRY_DELAY = 5          # 每次失败后等待秒数
PAGE_LOAD_TIMEOUT = 45   # 页面加载超时(秒)

# ================= 工具函数 =================

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度，如果是同一篇文章则返回 True。
    """
    if not url1 or not url2:
        return False

    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    # 比较基本部分：协议、主机名
    if parsed_url1.netloc != parsed_url2.netloc:
        return False

    # 对于Economist特有的URL结构进行处理
    path1 = parsed_url1.path.rstrip('/')
    path2 = parsed_url2.path.rstrip('/')

    path_components1 = path1.split('/')
    path_components2 = path2.split('/')

    # 确保路径组件足够比较
    if len(path_components1) < 5 or len(path_components2) < 5:
        return path1 == path2

    # 去掉空字符串
    path_components1 = [comp for comp in path_components1 if comp]
    path_components2 = [comp for comp in path_components2 if comp]

    min_length = min(len(path_components1), len(path_components2))
    comp_length = min(min_length, 5)

    return path_components1[:comp_length] == path_components2[:comp_length]


def create_driver():
    """创建并返回一个新的 Chrome WebDriver 实例 (从 a.py 移植的独立建驱动逻辑)。"""
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        print(f"警告：未找到 Chrome 二进制文件于 {CHROME_BINARY_PATH}，尝试使用系统默认路径...")

    # --- Headless模式 & 伪装设置 ---
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')

    # --- 伪装设置 (User-Agent & 去除自动化特征) ---
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
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
    options.add_argument("--blink-settings=imagesEnabled=false")  # 禁用图片加载

    # === 新增：防止渲染进程被后台节流/挂起，缓解 renderer timeout (从 a.py 移植) ===
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    # 保留 b.py 原本的 none 策略：不等待页面完全加载，防止渲染器卡死超时
    options.page_load_strategy = 'none'

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def load_old_content():
    """读取旧 HTML 文件中的历史内容 (与浏览器无关，只执行一次)。"""
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)
    if old_file_list:
        old_file_path = old_file_list[0]
        threshold_date = datetime.now() - timedelta(days=45)
        try:
            with open(old_file_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'html.parser')
                rows = soup.find_all('tr')[1:]  # 跳过标题行
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        date_str = cols[0].text.strip()
                        try:
                            date_obj = datetime.strptime(date_str, '%Y_%m_%d_%H')
                            if date_obj >= threshold_date:
                                title_column = cols[1]
                                title = title_column.text.strip()
                                link = title_column.find('a')['href'] if title_column.find('a') else None
                                old_content.append([date_str, title, link])
                        except ValueError:
                            continue
        except Exception as e:
            print(f"读取旧文件出错: {e}")
    return old_content, old_file_list


def scrape_economist(old_content, formatted_datetime, current_year):
    """
    实际执行抓取的函数。成功返回 (new_rows, new_rows1)。
    若抓取失败则抛出异常，交由外层重试逻辑处理。
    """
    driver = None
    new_rows = []
    new_rows1 = []
    try:
        print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
        driver = create_driver()
        wait = WebDriverWait(driver, 15)

        print("正在访问 The Economist...")

        # [容错]：捕获 TimeoutException。即使超时，DOM 可能已经加载完毕，继续执行即可
        try:
            driver.get("https://www.economist.com/")
            # page_load_strategy='none' 下，需要主动等 DOM
            try:
                WebDriverWait(driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
            except TimeoutException:
                print("DOM 未就绪，继续尝试...")
            time.sleep(3)  # 给 Next.js 水合一点时间
        except TimeoutException:
            print("警告: 页面加载超时，但可能核心内容已加载，尝试继续执行...")

        # --- 处理 Cookie 同意弹窗 ---
        try:
            print("正在检测 Cookie 弹窗...")

            # 1. 尝试查找 Cookie 弹窗的 iframe
            try:
                cookie_iframe = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//iframe[contains(@id, 'sp_message_iframe') or contains(@title, 'SP Consent Message')]"))
                )
                driver.switch_to.frame(cookie_iframe)
                print("已成功切换到 Cookie 弹窗的 iframe...")
            except Exception:
                # 如果没找到 iframe，说明可能在主页面上，直接继续往下找
                pass

            # 2. 查找 "Accept all" 按钮
            accept_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//*[normalize-space(text())='Accept all' or contains(text(), 'Accept all')]")
            ))

            print("检测到 'Accept all' 按钮，正在点击...")
            accept_button.click()
            time.sleep(2)  # 等待弹窗完全消失

        except Exception:
            print("未检测到明显的 Cookie 弹窗或已自动跳过，继续执行。")
        finally:
            # 3. 无论是否找到弹窗，最后都必须将焦点切回主页面
            driver.switch_to.default_content()

        # --- 抓取新内容 ---

        # 滚动机制
        print("开始滚动页面以加载更多内容...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 1000);")
            print(f"滚动次数: {i+1}/4")
            time.sleep(1)
        print("滚动完成，开始抓取内容。")

        try:
            # Economist 所有文章链接都有 data-analytics 属性
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-analytics]")))

            # 综合选择器：data-analytics 链接 + h3 下的链接 + 简报链接
            selector = "a[data-analytics], main h3 a, a[href*='world-in-brief']"
            titles_elements = driver.find_elements(By.CSS_SELECTOR, selector)

            # 第一步 - 提取原始数据 (Snapshot)
            raw_data_list = []
            seen_links = set()  # 用于本次抓取内部去重

            print(f"初步定位到 {len(titles_elements)} 个元素，开始提取...")

            for element in titles_elements:
                try:
                    href = element.get_attribute('href')
                    title_text = element.get_attribute('innerText').strip()
                    if not title_text:
                        title_text = element.text.strip()

                    if href and title_text and href not in seen_links:
                        if len(title_text) > 5 and "Read more" not in title_text:
                            raw_data_list.append((href, title_text))
                            seen_links.add(href)
                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue

            print(f"提取到 {len(raw_data_list)} 个有效原始链接，开始业务逻辑过滤...")

            # 第二步 - 业务逻辑过滤
            for href, title_text in raw_data_list:
                lower_title = title_text.lower()

                # 过滤器 1: 敏感词过滤
                if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                    continue

                # 过滤器 2: 类型过滤 (排除播客、电影等)
                if ('podcasts' in href or "film" in href or "cartoon" in href or
                        ('letters' in href and 'editor' in href)):
                    continue

                # 过滤器 3: 年份与重要性校验
                is_valid_article = False
                if "world-in-brief" in href:
                    is_valid_article = True
                elif f"/{current_year}/" in href:
                    is_valid_article = True

                if is_valid_article:
                    is_old_duplicate = any(is_similar(href, old_link) for _, _, old_link in old_content)
                    is_new_duplicate = any(is_similar(href, new_link) for _, _, new_link in new_rows)

                    if not is_old_duplicate and not is_new_duplicate:
                        print(f"  [新增] {title_text}")
                        new_rows.append([formatted_datetime, title_text, href])
                        new_rows1.append(["Economist", title_text, href])

            print("-" * 40)
            if new_rows:
                print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
            else:
                print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
                if raw_data_list:
                    print("调试 - 抓取到的原始数据样例 (前3条):")
                    for item in raw_data_list[:3]:
                        print(item)
            print("-" * 40)

        except Exception as e:
            print("抓取过程中出现错误:", e)
            # === 关键调试：保存现场 ===
            debug_dir = os.path.join(DOWNLOADS_DIR, "selenium_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                driver.save_screenshot(os.path.join(debug_dir, f"econ_{ts}.png"))
                with open(os.path.join(debug_dir, f"econ_{ts}.html"), 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                print(f"调试快照已保存到 {debug_dir}")
                print(f"当前 URL: {driver.current_url}")
                print(f"页面 title: {driver.title}")
            except Exception as de:
                print(f"保存调试信息失败: {de}")
            import traceback
            traceback.print_exc()
            # 重新抛出异常，交给外层重试循环处理
            raise

        return new_rows, new_rows1

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ================= 主程序逻辑 =================

def main():
    # 驱动文件存在性检查
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        print("请下载对应版本的 ChromeDriver 并放置在该路径下。")
        return

    formatted_datetime = datetime.now().strftime("%Y_%m_%d_%H")
    current_year = str(datetime.now().year)

    # 1. 先读取旧内容（与浏览器无关，只做一次）
    old_content, old_file_list = load_old_content()

    # 2. 带重试的抓取
    new_rows, new_rows1 = [], []
    scrape_success = False

    for attempt in range(1, MAX_RETRIES + 1):
        print("\n" + "=" * 50)
        print(f"🔄 第 {attempt}/{MAX_RETRIES} 次尝试抓取...")
        print("=" * 50)
        try:
            new_rows, new_rows1 = scrape_economist(old_content, formatted_datetime, current_year)
            scrape_success = True
            break  # 成功就跳出重试循环
        except Exception as e:
            print(f"❌ 第 {attempt} 次尝试失败: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES:
                print(f"   等待 {RETRY_DELAY} 秒后重建浏览器重试...")
                time.sleep(RETRY_DELAY)
            else:
                print("   已达到最大重试次数，放弃本次抓取。")

    if not scrape_success:
        print("⚠️ 所有重试均失败，本次不更新任何文件，安全退出。")
        return

    # --- 文件写入操作（只有抓取成功才执行） ---

    # 确保目标目录存在
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)

    if old_file_list:
        try:
            if os.path.exists(old_file_list[0]):
                os.remove(old_file_list[0])
                print(f"文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: 无法删除旧文件 {e}")

    # 创建 site HTML 文件
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

    # 创建每日新闻总表 HTML
    if new_rows1:
        closing_tag = "</table></body></html>"
        file_exists = os.path.isfile(TODAY_HTML_PATH)

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
                new_file_content = content + append_content + closing_tag
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write(new_file_content)
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