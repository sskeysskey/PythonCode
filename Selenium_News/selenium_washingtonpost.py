import os
import time
import html
import socket
import platform
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

# ================= 配置区域 (跨平台修改) =================

USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

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

SITE_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "washingtonpost.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

TARGET_URL = "https://www.washingtonpost.com/"
TARGET_HOST = "www.washingtonpost.com"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

RETENTION_DAYS = 30          # 旧记录保留天数
EXCLUDE_KEYWORDS = ['podcasts', 'sports', '/music/', 'weather', '/books/',
                    'food', '/advice/', '/tv/', '/entertainment/',
                    '/national-security/', '/opinions/']

# ---- 重试相关配置 ----
MAX_ATTEMPTS = 3             # 整轮(重建浏览器)最大尝试次数
GET_RETRIES = 4              # 单次 driver.get 的最大重试次数
NETWORK_WAIT_SECONDS = 90    # 启动前等待网络(DNS)就绪的最长时间
PAGE_LOAD_TIMEOUT = 30       # 页面加载超时(秒)
MAX_TITLE_FIXES = 30         # 单轮最多进入详情页修复标题的数量
MAX_CONSECUTIVE_FIX_FAILS = 3  # 连续失败多少次后放弃修复标题

H1_CSS = "h1[data-testid='headline'], h1[data-qa='headline'], h1"

# 一次性提取所有链接及标题(避免逐元素调用导致 stale / 慢)
EXTRACT_JS = r"""
const sel = arguments[0];
return Array.from(document.querySelectorAll(sel)).map(a => {
  const h = a.querySelector('h2, h3');
  const raw = (h ? h.innerText : a.innerText) || a.textContent || '';
  return [a.href || '', raw.replace(/\s+/g, ' ').trim()];
});
"""

# ========================================================


# ---------------------- 通用工具函数 ----------------------

def log(msg):
    print(msg, flush=True)


def short_msg(e):
    """只取异常的第一行,避免 chromedriver 堆栈刷屏"""
    text = str(e).strip()
    return text.splitlines()[0] if text else type(e).__name__


def backoff_delay(attempt, base=5, cap=60):
    """指数退避: 5, 10, 20, 40, 60, 60 ..."""
    return min(base * (2 ** (attempt - 1)), cap)


def normalize_url(url):
    """去掉协议、参数、末尾斜杠,用于判重"""
    if not url:
        return ""
    p = urlparse(url)
    return f"{p.netloc.lower()}{p.path.rstrip('/')}"


def is_short_title(title):
    """标题过短 (少于 5 个单词 或 少于 40 个字符)"""
    if not title:
        return True
    return len(title.split()) < 5 or len(title) < 40


def atomic_write(path, text):
    """先写临时文件再原子替换,防止写到一半出错导致数据丢失"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp_path, path)


def make_link(href, title):
    safe_title = html.escape(title)
    if not href:
        return safe_title
    return f"<a href='{html.escape(href, quote=True)}' target='_blank'>{safe_title}</a>"


# ---------------------- 网络与浏览器 ----------------------

def wait_for_network(host=TARGET_HOST, max_wait=NETWORK_WAIT_SECONDS):
    """轮询 DNS,直到目标域名可解析(应对开机/唤醒后网络未就绪)"""
    deadline = time.time() + max_wait
    delay = 2
    first = True
    while True:
        try:
            socket.getaddrinfo(host, 443)
            if not first:
                log("✅ 网络已恢复。")
            return True
        except OSError:
            if first:
                log(f"⏳ 网络/DNS 尚未就绪,等待最长 {max_wait} 秒...")
                first = False
            if time.time() + delay > deadline:
                log("⚠️ 等待网络超时,仍将尝试继续(后续有重试)。")
                return False
            time.sleep(delay)
            delay = min(delay * 2, 15)


def create_driver():
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        log(f"警告:未找到 Chrome 二进制文件于 {CHROME_BINARY_PATH},尝试使用系统默认路径...")

    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(f'user-agent={USER_AGENT}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--blink-settings=imagesEnabled=false")
    if platform.system() == 'Linux':
        options.add_argument("--no-sandbox")
    options.page_load_strategy = 'eager'

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def safe_quit(driver):
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass


def load_homepage(driver):
    """访问首页;遇到 net::ERR_* 等瞬时网络错误时退避重试"""
    for attempt in range(1, GET_RETRIES + 1):
        try:
            driver.get(TARGET_URL)
            return
        except TimeoutException:
            # eager 模式下超时通常页面主体已出现,停止加载继续往下
            log("⚠️ 页面加载超时,停止加载并继续...")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            return
        except WebDriverException as e:
            msg = str(e)
            retryable = "net::ERR_" in msg
            if retryable and attempt < GET_RETRIES:
                delay = backoff_delay(attempt)
                log(f"⚠️ 访问失败({short_msg(e)}),{delay}s 后重试 [{attempt}/{GET_RETRIES}]...")
                time.sleep(delay)
                wait_for_network(max_wait=30)
                continue
            raise


# ---------------------- 标题修复 ----------------------

def get_full_title(driver, max_retries=3):
    """在当前标签页(详情页)中读取完整标题"""
    for _ in range(max_retries):
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, H1_CSS))
            )
            time.sleep(0.8)  # 等 React hydration
            title = driver.execute_script(
                "const el = document.querySelector(arguments[0]);"
                "return el ? el.textContent.trim() : '';",
                H1_CSS,
            )
            if title and len(title) >= 10:
                return title
            time.sleep(0.5)
        except StaleElementReferenceException:
            time.sleep(0.5)
        except TimeoutException:
            return None
    return None


def fetch_title_in_new_tab(driver, href):
    """新开标签页读取完整标题,无论成败都关闭标签并回到主页"""
    main_handle = driver.current_window_handle
    try:
        driver.switch_to.new_window('tab')
        try:
            driver.get(href)
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
        return get_full_title(driver)
    finally:
        try:
            if driver.current_window_handle != main_handle:
                driver.close()
        except Exception:
            pass
        driver.switch_to.window(main_handle)


def fix_short_titles(driver, items):
    """对过短标题进入详情页获取完整标题(尽力而为,失败不影响主流程)"""
    log("正在检查并修复过短的标题...")
    fixed = 0
    consecutive_fails = 0
    result = []

    for href, title in items:
        if (is_short_title(title)
                and fixed < MAX_TITLE_FIXES
                and consecutive_fails < MAX_CONSECUTIVE_FIX_FAILS):
            fixed += 1
            log(f"发现短标题: '{title}' -> 正在进入详情页获取完整标题...")
            try:
                full_title = fetch_title_in_new_tab(driver, href)
                if full_title and len(full_title) >= len(title):
                    log(f"  ✅ 成功获取完整标题: '{full_title}'")
                    title = full_title
                    consecutive_fails = 0
                elif full_title:
                    log(f"  ⚠️ 获取的标题({len(full_title)}字符)不如原标题({len(title)}字符)长,保留原标题。")
                    consecutive_fails = 0
                else:
                    log("  ⚠️ 未能获取完整标题,保留原标题。")
                    consecutive_fails += 1
            except Exception as e:
                log(f"  ⚠️ 获取详情页标题失败 ({type(e).__name__}: {short_msg(e)}),保留原标题。")
                consecutive_fails += 1
        result.append((href, title))

    if consecutive_fails >= MAX_CONSECUTIVE_FIX_FAILS:
        log("⚠️ 连续多次修复标题失败,已跳过剩余短标题。")
    return result


# ---------------------- 抓取主流程 ----------------------

def pre_filter(raw_items, known_keys):
    """按 URL 关键字排除 + 与旧内容/本次内容去重(不依赖标题)"""
    seen = set(known_keys)
    result = []
    for href, title in raw_items:
        if not href or not title:
            continue
        if any(k in href for k in EXCLUDE_KEYWORDS):
            continue
        key = normalize_url(href)
        if key in seen:
            continue
        seen.add(key)
        result.append((href, title))
    return result


def scrape_once(driver, known_keys):
    """单轮抓取。任何致命问题都抛异常,交给外层重建浏览器重试"""
    log("正在访问 Washington Post...")
    load_homepage(driver)

    log("开始滚动页面...")
    for _ in range(4):
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(0.5)
    log("滚动完成。")

    css_selector = f"a[href*='/{datetime.now().year}/']:not(.label-link)"
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
    except TimeoutException:
        raise RuntimeError("页面中未找到文章链接(页面可能未正常渲染)")

    raw = driver.execute_script(EXTRACT_JS, css_selector) or []
    raw_items = [(h, t) for h, t in raw if h and t]
    log(f"找到 {len(raw)} 个潜在链接,成功提取 {len(raw_items)} 条原始数据。")
    if not raw_items:
        raise RuntimeError("提取到的原始数据为 0 条")

    candidates = pre_filter(raw_items, known_keys)
    log(f"URL 过滤/去重后剩余 {len(candidates)} 条候选。")

    return fix_short_titles(driver, candidates)


def scrape_with_retry(known_keys):
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"--- 第 {attempt}/{MAX_ATTEMPTS} 次尝试 ---")
        wait_for_network()
        driver = None
        try:
            log(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
            driver = create_driver()
            return scrape_once(driver, known_keys)
        except Exception as e:
            last_err = e
            log(f"❌ 第 {attempt} 次尝试失败: {type(e).__name__}: {short_msg(e)}")
        finally:
            safe_quit(driver)

        if attempt < MAX_ATTEMPTS:
            delay = backoff_delay(attempt, base=10)
            log(f"⏳ {delay}s 后重新创建浏览器重试...")
            time.sleep(delay)

    raise RuntimeError(f"连续 {MAX_ATTEMPTS} 次尝试均失败,最后错误: {short_msg(last_err)}") from last_err


# ---------------------- 文件读写 ----------------------

def load_old_content(now):
    """读取旧站点文件,返回 [[date_str, title, link], ...](仅保留 RETENTION_DAYS 天内)"""
    old_content = []
    if not os.path.exists(SITE_HTML_PATH):
        return old_content

    cutoff = now - timedelta(days=RETENTION_DAYS)
    try:
        with open(SITE_HTML_PATH, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        for row in soup.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) < 2:
                continue
            date_str = cols[0].text.strip()
            try:
                date = datetime.strptime(date_str, '%Y_%m_%d_%H')
            except ValueError:
                continue
            if date >= cutoff:
                a = cols[1].find('a')
                link = a['href'] if a and a.has_attr('href') else None
                old_content.append([date_str, cols[1].text.strip(), link])
    except OSError as e:
        log(f"读取旧文件时出错: {e}")
    return old_content


def write_site_file(new_rows, old_content):
    parts = ["<html><body><table border='1'>\n",
             "<tr><th>Date</th><th>Title</th></tr>\n"]
    for date_str, title, href in new_rows:
        parts.append(f"<tr><td>{date_str}</td><td>{make_link(href, title)}</td></tr>\n")
    for date_str, title, href in old_content:
        parts.append(f"<tr><td>{date_str}</td><td>{make_link(href, title)}</td></tr>\n")
    parts.append("</table></body></html>")
    atomic_write(SITE_HTML_PATH, "".join(parts))
    log(f"已更新站点文件: {SITE_HTML_PATH}")


def append_to_today(new_rows):
    closing_tag = "</table></body></html>"
    append_content = "".join(
        f"<tr><td>WashingtonPost</td><td>{make_link(href, title)}</td></tr>\n"
        for _, title, href in new_rows
    )

    if os.path.isfile(TODAY_HTML_PATH):
        with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        idx = content.rfind("</table>")  # 兼容各种换行格式的结尾标签
        head = content[:idx] if idx != -1 else content
        new_content = head + append_content + closing_tag
    else:
        new_content = ("<html><body><table border='1'>\n"
                       "<tr><th>site</th><th>Title</th></tr>\n"
                       + append_content + closing_tag)

    atomic_write(TODAY_HTML_PATH, new_content)
    log(f"已追加到总表: {TODAY_HTML_PATH}")


# ---------------------- 入口 ----------------------

def main():
    if not os.path.exists(CHROME_DRIVER_PATH):
        log(f"错误:未找到驱动文件: {CHROME_DRIVER_PATH}")
        log("请下载对应版本的 ChromeDriver 并放置在该路径下。")
        return

    now = datetime.now()
    formatted_datetime = now.strftime("%Y_%m_%d_%H")

    # 先读旧数据(此时不动任何文件)
    old_content = load_old_content(now)
    known_keys = {normalize_url(link) for _, _, link in old_content if link}

    # 抓取(内部含完整重试;全部失败会抛异常,且不会改动任何已有文件)
    candidates = scrape_with_retry(known_keys)

    # 基于(可能已修复的)完整标题做内容过滤
    log("开始过滤数据...")
    new_rows = []
    for href, title in candidates:
        lower_title = title.lower()
        # "xi jinping" 忽略大小写;"Xi's"、"Tiananmen" 严格匹配
        if "xi jinping" in lower_title or "Xi's" in title or "Tiananmen" in title:
            continue
        new_rows.append([formatted_datetime, title, href])

    log("-" * 40)
    if new_rows:
        log(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻!")
    else:
        log("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
    log("-" * 40)

    # 写文件(原子替换,不会出现"删了旧文件却没写成功")
    try:
        write_site_file(new_rows, old_content)
    except Exception as e:
        log(f"写入 Site HTML 出错: {e}")

    if new_rows:
        try:
            append_to_today(new_rows)
        except Exception as e:
            log(f"写入总表出错: {e}")


if __name__ == "__main__":
    main()