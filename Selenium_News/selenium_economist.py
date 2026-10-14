#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第一次运行可能会弹出窗口验证，按终端提示操作即可。
配置目录 ~/Coding/News/backup/chrome_profile_economist 是这个脚本专用的，不要和其他脚本共用：Chrome 同一时间只允许一个实例使用同一个配置目录。
如果提示"配置目录被占用"，在终端执行 pkill -f chrome_profile_economist 就能关掉残留进程。
如果无头模式仍然经常被拦，把 BROWSER_MODE 改成 "offscreen"。这时会用真实窗口运行，但窗口放在屏幕外看不到，是最接近真人的方式。
这个脚本一般是无人值守运行的。如果你不希望弹出窗口，把 INTERACTIVE_FALLBACK = False，失败时会安全退出，不改动任何文件。
"""

import os
import re
import time
import glob
import html
import tempfile
import platform
import subprocess
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    SessionNotCreatedException,
)

# ================= 配置区域 (跨平台) =================

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

# 业务文件路径
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "economist.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "economist.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# 【新增】本脚本专用的持久化浏览器配置目录（保存反爬通行 cookie 和 Cookie 同意状态）
#  注意：不要与其他脚本共用同一个目录，Chrome 不允许多个实例同时使用同一配置目录
PROFILE_DIR = os.path.join(BASE_CODING_DIR, "News", "backup", "chrome_profile_economist")

# 调试快照目录 & 保留天数
DEBUG_DIR = os.path.join(DOWNLOADS_DIR, "selenium_debug")
DEBUG_KEEP_DAYS = 7

HOME_URL = "https://www.economist.com/"

# 运行模式："headless" = 无头（默认）；"offscreen" = 真实窗口但放到屏幕外（更像真人，被拦概率更低）
BROWSER_MODE = "headless"

HEADLESS_ATTEMPTS = 2        # 自动(无头/屏外)尝试次数
RETRY_DELAY = 5              # 每次失败后等待秒数
PAGE_LOAD_TIMEOUT = 45       # driver 页面加载超时(秒)
CONTENT_WAIT_TIMEOUT = 45    # 等待首页文章出现的总超时(秒)
CHALLENGE_AUTO_WAIT = 25     # 检测到"可自动通过的验证页"时，最多静默等待多少秒
MIN_ARTICLE_LINKS = 5        # 首页至少出现多少个文章链接才算加载成功
COOKIE_WAIT = 4              # 等 Cookie 弹窗出现的秒数（持久化配置后通常不会再出现）
SCROLL_TIMES = 5

# 自动尝试都失败时，是否弹出可见窗口让用户手动完成验证
INTERACTIVE_FALLBACK = True
MANUAL_VERIFY_TIMEOUT = 180  # 等待用户手动验证的最长秒数

HISTORY_DAYS = 45            # 历史去重保留天数
VERBOSE = False              # True 时对"意外错误"打印完整堆栈

STATE_DESC = {
    "ok": "首页已加载",
    "loading": "页面加载中",
    "timeout": "页面加载超时（网络慢或页面结构变化）",
    "challenge": "反爬验证页（Cloudflare/DataDome 后台检测）",
    "captcha": "反爬验证码（需要人工完成）",
    "blocked": "被反爬系统直接封锁（可能是 IP 信誉问题）",
}

# ================= 工具函数 =================


def first_line(e):
    """只取异常信息第一行，避免 Selenium 打印一大段 Stacktrace。"""
    s = str(e).strip()
    return s.splitlines()[0] if s else type(e).__name__


def notify(title, message):
    """macOS 系统通知（其它系统静默跳过）。"""
    if platform.system() != "Darwin":
        return
    try:
        safe_msg = message.replace('"', "'")
        safe_title = title.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_msg}" with title "{safe_title}" sound name "Glass"'],
            check=False, timeout=5,
        )
    except Exception:
        pass


def is_similar(url1, url2):
    """比较两个 URL 是否指向同一篇文章。"""
    if not url1 or not url2:
        return False

    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    if parsed_url1.netloc != parsed_url2.netloc:
        return False

    path1 = parsed_url1.path.rstrip('/')
    path2 = parsed_url2.path.rstrip('/')

    path_components1 = path1.split('/')
    path_components2 = path2.split('/')

    if len(path_components1) < 5 or len(path_components2) < 5:
        return path1 == path2

    path_components1 = [comp for comp in path_components1 if comp]
    path_components2 = [comp for comp in path_components2 if comp]

    min_length = min(len(path_components1), len(path_components2))
    comp_length = min(min_length, 5)

    return path_components1[:comp_length] == path_components2[:comp_length]


def normalize_href(href):
    """去掉 URL 的 #fragment，便于去重。"""
    try:
        p = urlparse(href)
        return urlunparse(p._replace(fragment=""))
    except Exception:
        return href


def normalize_title(text):
    """合并多余空白/换行。"""
    return " ".join((text or "").split())


def atomic_write(path, content):
    """先写临时文件再原子替换，避免写一半失败导致历史数据丢失。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".html")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def build_row(first_col, title, href):
    """生成一行表格 HTML（做好转义）。"""
    safe_title = html.escape(title or "", quote=False)
    if href:
        cell = f'<a href="{html.escape(href, quote=True)}" target="_blank">{safe_title}</a>'
    else:
        cell = safe_title
    return f"<tr><td>{html.escape(first_col or '', quote=False)}</td><td>{cell}</td></tr>\n"


def cleanup_old_debug_files():
    """清理过期的调试快照，避免目录无限膨胀。"""
    if not os.path.isdir(DEBUG_DIR):
        return
    cutoff = time.time() - DEBUG_KEEP_DAYS * 86400
    for f in glob.glob(os.path.join(DEBUG_DIR, "econ_*")):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
        except OSError:
            pass


def save_debug_snapshot(driver, tag):
    """保存截图 + 源码，便于排查。"""
    if not driver:
        return
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(DEBUG_DIR, f"econ_{ts}_{tag}")
        driver.save_screenshot(base + ".png")
        with open(base + ".html", 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"   调试快照: {base}.png / .html (URL: {driver.current_url}, 标题: {driver.title!r})")
    except Exception as e:
        print(f"   保存调试快照失败: {first_line(e)}")


# ================= 浏览器相关 =================

class PageNotReadyError(Exception):
    """首页未能正常加载（被反爬拦截/超时）。属于"预期内"的失败，不打印堆栈。"""

    def __init__(self, state):
        self.state = state
        super().__init__(STATE_DESC.get(state, state))


def _fix_headless_fingerprint(driver):
    """
    修正 headless 指纹：使用浏览器真实 UA，仅把 HeadlessChrome 替换为 Chrome，
    并同步 Sec-CH-UA 客户端提示，保证 UA 与客户端提示一致（不一致是 DataDome 的强特征）。
    """
    try:
        ua = driver.execute_script("return navigator.userAgent") or ""
        if "HeadlessChrome" not in ua:
            return
        params = {"userAgent": ua.replace("HeadlessChrome", "Chrome"),
                  "acceptLanguage": "en-US,en;q=0.9"}

        meta = None
        try:
            meta = driver.execute_async_script("""
                const done = arguments[arguments.length - 1];
                if (!navigator.userAgentData) { done(null); return; }
                navigator.userAgentData.getHighEntropyValues(
                    ['architecture', 'bitness', 'model', 'platformVersion', 'fullVersionList', 'wow64']
                ).then(v => done(v)).catch(() => done(null));
            """)
        except Exception:
            meta = None

        def fix(lst):
            return [{"brand": ("Google Chrome" if b.get("brand") == "HeadlessChrome" else b.get("brand")),
                     "version": b.get("version", "")} for b in (lst or [])]

        if meta:
            brands = fix(meta.get("brands"))
            full_list = fix(meta.get("fullVersionList"))
            full_version = next((b["version"] for b in full_list if b["brand"] == "Google Chrome"), "")
            params["userAgentMetadata"] = {
                "brands": brands,
                "fullVersionList": full_list,
                "fullVersion": full_version,
                "platform": meta.get("platform", ""),
                "platformVersion": meta.get("platformVersion", ""),
                "architecture": meta.get("architecture", ""),
                "model": meta.get("model", ""),
                "mobile": bool(meta.get("mobile", False)),
                "bitness": meta.get("bitness", ""),
                "wow64": bool(meta.get("wow64", False)),
            }
        else:
            # 兜底：根据浏览器版本手工构造
            full_version = driver.capabilities.get("browserVersion", "")
            major = full_version.split(".")[0] if full_version else ""
            plat = {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), "Linux")
            arch = "arm" if platform.machine().lower() in ("arm64", "aarch64") else "x86"
            brands = [{"brand": "Google Chrome", "version": major},
                      {"brand": "Chromium", "version": major},
                      {"brand": "Not_A Brand", "version": "99"}]
            params["userAgentMetadata"] = {
                "brands": brands,
                "fullVersionList": [dict(b, version=full_version if b["brand"] != "Not_A Brand" else "99.0.0.0")
                                    for b in brands],
                "fullVersion": full_version,
                "platform": plat,
                "platformVersion": "",
                "architecture": arch,
                "model": "",
                "mobile": False,
                "bitness": "64",
                "wow64": False,
            }

        driver.execute_cdp_cmd("Network.setUserAgentOverride", params)
    except Exception as e:
        print(f"   (指纹修正跳过: {first_line(e)})")


def create_driver(mode):
    """
    mode: "headless" / "offscreen" / "visible"
    """
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        print(f"警告：未找到 Chrome 于 {CHROME_BINARY_PATH}，尝试使用系统默认 Chrome...")

    # 持久化配置目录：保留反爬通行 cookie 与 Cookie 同意状态
    os.makedirs(PROFILE_DIR, exist_ok=True)
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")

    if mode == "headless":
        options.add_argument("--headless=new")
        # 只在无头模式下禁图提速；可见模式必须显示图片，否则滑块验证码无法完成
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--window-size=1920,1080")
    elif mode == "offscreen":
        options.add_argument("--window-position=-2400,-2400")
        options.add_argument("--window-size=1920,1080")
    else:  # visible
        options.add_argument("--window-size=1280,900")

    # 去除自动化特征（不再写死 User-Agent，避免版本/平台自相矛盾）
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--lang=en-US")
    options.add_experimental_option("prefs", {
        "intl.accept_languages": "en-US,en",
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-extensions")

    # 防止渲染进程被节流/挂起
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    # 仅 Linux（容器/服务器）需要
    if platform.system() == "Linux":
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

    options.page_load_strategy = 'none'

    if os.path.exists(CHROME_DRIVER_PATH):
        service = Service(executable_path=CHROME_DRIVER_PATH)
    else:
        print(f"提示：未找到 {CHROME_DRIVER_PATH}，改用 Selenium Manager 自动匹配驱动...")
        service = Service()

    try:
        driver = webdriver.Chrome(service=service, options=options)
    except SessionNotCreatedException as e:
        msg = str(e)
        if "user data directory is already in use" in msg or "user-data-dir" in msg:
            raise RuntimeError(
                f"浏览器配置目录被占用：{PROFILE_DIR}。可能有残留的 Chrome 进程，"
                f"请执行 pkill -f chrome_profile_economist 后重试。") from None
        if "version" in msg.lower():
            raise RuntimeError(f"ChromeDriver 与 Chrome 版本不匹配：{first_line(e)}") from None
        raise

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    if mode == "headless":
        _fix_headless_fingerprint(driver)
    return driver


STATE_JS = r"""
const t = (document.title || '').trim().toLowerCase();
const n = document.querySelectorAll('a[data-analytics]').length;
let ddrt = null;
try { if (window.dd && window.dd.rt) ddrt = String(window.dd.rt); } catch (e) {}
const ddFrame = !!document.querySelector("iframe[src*='captcha-delivery.com']");
let cf = false;
try {
  cf = !!window._cf_chl_opt ||
       !!document.querySelector("iframe[src*='challenges.cloudflare.com'], #challenge-form, #challenge-running, .cf-turnstile") ||
       t.startsWith('just a moment');
} catch (e) {}
return {title: t, articles: n, ddrt: ddrt, ddFrame: ddFrame, cf: cf,
        ready: document.readyState, url: location.href};
"""


def get_page_state(driver):
    try:
        info = driver.execute_script(STATE_JS)
    except WebDriverException:
        return "loading", {}
    if not info:
        return "loading", {}
    if "economist.com" not in (info.get("url") or ""):
        # 仍停留在 data:, / about:blank（page_load_strategy='none' 时很常见）
        return "loading", info
    if info.get("articles", 0) >= MIN_ARTICLE_LINKS:
        return "ok", info
    rt = (info.get("ddrt") or "").lower()
    if rt == "b":
        return "blocked", info
    if rt == "c":
        return "captcha", info
    if rt == "i" or info.get("ddFrame") or info.get("cf"):
        return "challenge", info
    if info.get("title") in ("economist.com", "www.economist.com"):
        return "challenge", info
    return "loading", info


def wait_for_homepage(driver, interactive):
    """轮询页面状态，直到首页文章出现；遇到验证页按策略等待或放弃。"""
    start = time.time()
    limit = MANUAL_VERIFY_TIMEOUT if interactive else CONTENT_WAIT_TIMEOUT
    last_state = None
    challenge_since = None

    while True:
        state, info = get_page_state(driver)
        if state != last_state:
            if state == "ok":
                print(f"   ✔ 首页已加载（检测到 {info.get('articles')} 个文章链接，用时 {time.time() - start:.1f}s）")
            elif state != "loading":
                print(f"   … 检测到{STATE_DESC[state]}，"
                      f"{'等待你在浏览器窗口中完成验证' if interactive else '静默等待其自动通过'}...")
            last_state = state

        if state == "ok":
            return info

        if interactive:
            if state == "blocked":
                raise PageNotReadyError("blocked")
        else:
            if state in ("captcha", "blocked"):
                raise PageNotReadyError(state)
            if state == "challenge":
                challenge_since = challenge_since or time.time()
                if time.time() - challenge_since > CHALLENGE_AUTO_WAIT:
                    raise PageNotReadyError("challenge")

        if time.time() - start > limit:
            raise PageNotReadyError(state if state != "loading" else "timeout")
        time.sleep(1)


def handle_cookie_consent(driver):
    """处理 Sourcepoint Cookie 弹窗（持久化配置后通常只需处理一次）。"""
    iframe_locator = (By.XPATH, "//iframe[contains(@id, 'sp_message_iframe') or contains(@title, 'SP Consent Message')]")
    button_xpath = ("//button[contains(normalize-space(.), 'Accept all') or contains(@title, 'Accept all')]"
                    " | //*[normalize-space(text())='Accept all']")
    try:
        try:
            WebDriverWait(driver, COOKIE_WAIT).until(EC.frame_to_be_available_and_switch_to_it(iframe_locator))
        except TimeoutException:
            if not driver.find_elements(By.XPATH, button_xpath):
                print("   Cookie 弹窗未出现（已记住同意或无需同意），跳过。")
                return
        btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
        try:
            btn.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", btn)
        print("   已点击 'Accept all'。")
        time.sleep(1.5)
    except Exception as e:
        print(f"   Cookie 弹窗处理跳过（不影响抓取）：{first_line(e)}")
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


EXTRACT_JS = r"""
const sel = "a[data-analytics], main h3 a, a[href*='world-in-brief']";
const out = [];
document.querySelectorAll(sel).forEach(a => {
  out.push([a.href || '', a.innerText || a.textContent || '']);
});
return out;
"""

SKIP_TITLE_KEYWORDS = ("read the rest", "read more")
SKIP_TITLE_PREFIXES = ("→", "›", "»")
XI_PATTERN = re.compile(r"\bxi jinping\b|\bxi's\b")


def filter_articles(raw_pairs, old_links, formatted_datetime, valid_years):
    """业务逻辑过滤，返回 (new_rows, new_rows1, raw_data_list)。"""
    raw_data_list = []
    seen = set()
    for href, text in raw_pairs:
        href = normalize_href(href)
        title = normalize_title(text)
        if not href or not title or href in seen:
            continue
        if len(title) <= 5:
            continue
        lower_title = title.lower().replace("’", "'")
        if title.startswith(SKIP_TITLE_PREFIXES) or any(k in lower_title for k in SKIP_TITLE_KEYWORDS):
            continue
        raw_data_list.append((href, title))
        seen.add(href)

    new_rows, new_rows1 = [], []
    for href, title in raw_data_list:
        lower_title = title.lower().replace("’", "'")
        lower_href = href.lower()

        # 过滤器 1: 敏感词（兼容弯撇号，且不误伤 taxi's 之类）
        if XI_PATTERN.search(lower_title) or "tiananmen" in lower_title:
            continue

        # 过滤器 2: 类型过滤
        if ('podcasts' in lower_href or "film" in lower_href or "cartoon" in lower_href or
                ('letters' in lower_href and 'editor' in lower_href)):
            continue

        # 过滤器 3: 年份
        if "world-in-brief" in lower_href:
            is_valid = True
        else:
            is_valid = any(f"/{y}/" in href for y in valid_years)
        if not is_valid:
            continue

        if any(is_similar(href, old) for old in old_links):
            continue
        if any(is_similar(href, r[2]) for r in new_rows):
            continue

        print(f"  [新增] {title}")
        new_rows.append([formatted_datetime, title, href])
        new_rows1.append(["Economist", title, href])

    return new_rows, new_rows1, raw_data_list


def scrape_economist(old_links, formatted_datetime, valid_years, mode):
    """
    执行一次抓取。成功返回 (new_rows, new_rows1)；
    首页进不去抛 PageNotReadyError；其它异常原样抛出。
    """
    driver = None
    interactive = (mode == "visible")
    try:
        print(f"正在启动 Chrome（模式: {mode}, OS: {platform.system()}）...")
        driver = create_driver(mode)

        print("正在访问 The Economist...")
        try:
            driver.get(HOME_URL)
        except TimeoutException:
            print("   页面加载超时，继续检测页面状态...")

        if interactive:
            print("\n" + "!" * 60)
            print("  已弹出浏览器窗口。如出现验证（点击/拖动滑块/勾选），请在窗口中完成。")
            print(f"  完成后脚本会自动继续（最长等待 {MANUAL_VERIFY_TIMEOUT} 秒）。请勿关闭窗口。")
            print("!" * 60 + "\n")
            notify("Economist 抓取", "需要你在弹出的浏览器窗口中完成一次人机验证")

        wait_for_homepage(driver, interactive)
        time.sleep(2)  # 给 Next.js 水合一点时间

        handle_cookie_consent(driver)

        print("滚动页面以加载更多内容...")
        for _ in range(SCROLL_TIMES):
            driver.execute_script("window.scrollBy(0, Math.max(window.innerHeight * 0.9, 800));")
            time.sleep(1)

        raw_pairs = driver.execute_script(EXTRACT_JS) or []
        print(f"定位到 {len(raw_pairs)} 个链接元素，开始过滤...")

        new_rows, new_rows1, raw_data_list = filter_articles(
            raw_pairs, old_links, formatted_datetime, valid_years)

        print("-" * 40)
        print(f"有效原始链接 {len(raw_data_list)} 个。")
        if new_rows:
            print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
        else:
            print("ℹ️ 统计报告: 本次未发现新内容 (0 条)。")
            if raw_data_list:
                print("调试 - 原始数据样例 (前3条):")
                for item in raw_data_list[:3]:
                    print("  ", item)
        print("-" * 40)
        return new_rows, new_rows1

    except PageNotReadyError as e:
        save_debug_snapshot(driver, e.state)
        raise
    except Exception:
        save_debug_snapshot(driver, "error")
        raise
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ================= 文件读写 =================

def load_old_content():
    """读取历史 HTML 中 HISTORY_DAYS 天内的内容。"""
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)
    if not old_file_list:
        return old_content
    threshold_date = datetime.now() - timedelta(days=HISTORY_DAYS)
    try:
        with open(old_file_list[0], 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
        for row in soup.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) < 2:
                continue
            date_str = cols[0].text.strip()
            try:
                date_obj = datetime.strptime(date_str, '%Y_%m_%d_%H')
            except ValueError:
                continue
            if date_obj >= threshold_date:
                a = cols[1].find('a')
                link = a.get('href') if a else None
                old_content.append([date_str, cols[1].text.strip(), link])
    except Exception as e:
        print(f"读取旧文件出错: {e}")
    return old_content


def write_site_html(new_rows, old_content):
    parts = ["<html><body><table border='1'>\n", "<tr><th>Date</th><th>Title</th></tr>\n"]
    for row in new_rows + old_content:
        parts.append(build_row(row[0], row[1], row[2]))
    parts.append("</table></body></html>")
    atomic_write(NEW_HTML_PATH, "".join(parts))
    print(f"已更新文件: {NEW_HTML_PATH}")


def append_today_html(new_rows1):
    if not new_rows1:
        return
    closing_tag = "</table></body></html>"
    append_content = "".join(build_row(r[0], r[1], r[2]) for r in new_rows1)

    if os.path.isfile(TODAY_HTML_PATH):
        with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        idx = content.rfind(closing_tag)
        if idx != -1:
            content = content[:idx]
        new_content = content + append_content + closing_tag
    else:
        new_content = ("<html><body><table border='1'>\n"
                       "<tr><th>site</th><th>Title</th></tr>\n"
                       + append_content + closing_tag)
    atomic_write(TODAY_HTML_PATH, new_content)
    print(f"已追加到总表: {TODAY_HTML_PATH}")


# ================= 主程序 =================

def run_attempt(label, old_links, formatted_datetime, valid_years, mode):
    """执行一次尝试，返回 (result 或 None, 失败状态)。"""
    print("\n" + "=" * 50)
    print(f"🔄 {label}")
    print("=" * 50)
    try:
        return scrape_economist(old_links, formatted_datetime, valid_years, mode), None
    except PageNotReadyError as e:
        print(f"⚠️ 未能进入首页：{STATE_DESC.get(e.state, e.state)}")
        return None, e.state
    except Exception as e:
        print(f"⚠️ 本次尝试出现意外错误：{type(e).__name__}: {first_line(e)}")
        if VERBOSE:
            traceback.print_exc()
        return None, "error"


def main():
    cleanup_old_debug_files()

    now = datetime.now()
    formatted_datetime = now.strftime("%Y_%m_%d_%H")
    valid_years = {str(now.year)}
    if now.month == 1:  # 跨年时首页可能仍有上一年 12 月底的文章
        valid_years.add(str(now.year - 1))

    old_content = load_old_content()
    old_links = [r[2] for r in old_content if r[2]]

    result = None
    for attempt in range(1, HEADLESS_ATTEMPTS + 1):
        result, state = run_attempt(f"第 {attempt}/{HEADLESS_ATTEMPTS} 次自动抓取",
                                    old_links, formatted_datetime, valid_years, BROWSER_MODE)
        if result is not None:
            break
        if state in ("captcha", "blocked"):
            print("   该类验证无法自动通过，跳过剩余自动重试。")
            break
        if attempt < HEADLESS_ATTEMPTS:
            print(f"   {RETRY_DELAY} 秒后重试...")
            time.sleep(RETRY_DELAY)

    if result is None and INTERACTIVE_FALLBACK:
        result, state = run_attempt("自动抓取未成功，弹出浏览器窗口请你协助验证",
                                    old_links, formatted_datetime, valid_years, "visible")
        if result is not None:
            print("👍 验证已通过，通行凭证已保存到专用配置目录，后续运行通常可静默完成。")

    if result is None:
        print("⚠️ 本次抓取未成功，不更新任何文件，安全退出。")
        return

    new_rows, new_rows1 = result
    try:
        write_site_html(new_rows, old_content)
    except Exception as e:
        print(f"写入站点 HTML 出错（原文件未被破坏）: {e}")
    try:
        append_today_html(new_rows1)
    except Exception as e:
        print(f"写入总表出错（原文件未被破坏）: {e}")


if __name__ == "__main__":
    main()