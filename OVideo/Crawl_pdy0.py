# -*- coding: utf-8 -*-
"""
pys2.com (pdy0) 爬取脚本
—— Cloudflare Turnstile 版：推荐「手动过一次验证 + CDP 附着 + curl_cffi 高速通道」

【推荐用法】
    1) 彻底退出 Chrome：osascript -e 'quit app "Google Chrome"'
    2) python Crawl_pdy0.py open        # 用脚本 profile 启动带调试端口的 Chrome
    3) 在弹出的窗口里手动勾选过 Cloudflare/滑块验证（一次就过）
    4) 窗口别关，另开终端： python Crawl_pdy0.py cdp fast

其它用法：
    python Crawl_pdy0.py                 # 正常抓取（自动弹出真实 Chrome 窗口）
    python Crawl_pdy0.py cdp             # 附着到你手动启动的 Chrome
    python Crawl_pdy0.py fast            # 开启 curl_cffi 加速通道（失败会自动降级）
参数可组合，例如：python Crawl_pdy0.py cdp fast
"""

import os
import re
import sys
import json
import time
import glob
import shutil
import socket
import platform
import subprocess
import atexit
import urllib.request
from urllib.parse import urljoin, urlparse

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup
from curl_cffi import requests as c_requests
import requests

# ================= 日志双写控制器 =================
class DualLogger:
    """同时将输出写入终端和磁盘日志文件"""
    def __init__(self, log_filepath):
        self.terminal = sys.stdout
        self.log_file = open(log_filepath, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.terminal.flush()
        self.log_file.write(message)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self):
        return getattr(self.terminal, "isatty", lambda: False)()


def setup_logging():
    """初始化日志文件"""
    log_dir = os.path.join(os.path.dirname(OUTPUT_FILE), "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"crawl_{SITE_KEY}_{ts}.log")

    logger = DualLogger(log_file)
    sys.stdout = logger
    sys.stderr = logger
    print(f">>> [日志] 本次抓取日志将同步记录至: {log_file}")


# ================= 防止系统休眠控制 =================
_caffeinate_proc = None

def start_caffeinate():
    global _caffeinate_proc
    if platform.system() == 'Darwin':
        try:
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-idmu"])
            print(">>> [系统] 已开启防休眠模式 (caffeinate)")
        except Exception as e:
            print(f">>> [系统] 无法启动 caffeinate: {e}")


def stop_caffeinate():
    global _caffeinate_proc
    if _caffeinate_proc:
        try:
            _caffeinate_proc.terminate()
            print(">>> [系统] 已关闭防休眠模式")
        except Exception:
            pass


atexit.register(stop_caffeinate)


# =============================================================
# 基础配置
# =============================================================
SITE_KEY        = "pdy0"
TARGET_DOMAIN   = "pys2.com"
DOMAIN          = "https://www.pys2.com"
LIST_BASE_URL   = DOMAIN
DETAIL_BASE_URL = DOMAIN
INDEX_BASE_URL  = DOMAIN
OUTPUT_FILE     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"

VERBOSE_LOG = False

def log(message: str, force: bool = False):
    if force or VERBOSE_LOG:
        print(message)


# ============ 浏览器 / CDP / Cloudflare 相关配置 ============
USER_DATA_DIR   = os.path.expanduser("~/Library/Application Support/Google/Chrome_Dev_pys2")
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9333
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False
FAST_MODE       = False
NAV_TIMEOUT_MS  = 60000

# curl_cffi 指纹（按常见指纹降级轮询）
FAST_IMPERSONATE_CANDIDATES = ["chrome124", "chrome131", "chrome120", "chrome116", "chrome"]
FAST_RESYNC_INTERVAL        = 300      # 每 300 秒从浏览器重新同步一次 cookie
FAST_MAX_RESYNC_FAIL        = 3        # 连续 N 次同步后仍 403，则本次运行不再用 FAST

# 人机验证等待策略
CHALLENGE_WAIT        = 600
CHALLENGE_GRACE       = 10
PASS_STABLE_HITS      = 3
POLL_INTERVAL         = 1.5
SITE_READY_TIMEOUT    = 8
PAGE_SETTLE           = 1.0

AUTO_CLICK_TURNSTILE   = True
AUTO_CLICK_FIRST_DELAY = 8
AUTO_CLICK_EVERY       = 15

CHALLENGE_MARKERS = (
    "Just a moment",
    "challenges.cloudflare.com/turnstile",
    "__cf_chl",
    "cf_chl_opt",
    "cf-challenge",
    "challenge-platform",
    "Checking your browser",
    "Verifying you are human",
    "Enable JavaScript and cookies to continue",
    "需要先验证您是真人",
    "正在验证您是否是真人",
)
SITE_MARKERS = ("vod-list", "vod-info", "vlist", "playlist-box", "otherbox", "/mv/", "/vod/", "/detail/")

REQUEST_TIMEOUT        = 20
SLEEP_BETWEEN_REQUESTS = 1.0
MAX_RETRIES            = 3
RETRY_BACKOFF          = 5.0

# ============ 数据安全相关配置 ============
BACKUP_DIR = os.path.join(os.path.dirname(OUTPUT_FILE), "backup")
BAK_FILE = OUTPUT_FILE + ".bak"
REJECTED_FILE = OUTPUT_FILE + ".rejected.json"
MAX_BACKUPS = 20
ALLOW_SHRINK_RATIO = 0.90
SHRINK_GUARD_MIN_ITEMS = 20
ALLOW_FRESH_START = False
REMOVE_EMPTY_PLAYLIST_ITEMS = False

_BASELINE_TOTAL = 0
_LOAD_OK = False

MIN_SCORE_LIMIT = 6.3
OLD_VIDEO_MIN_SCORE = 6.3
CURRENT_YEAR = str(time.localtime().tm_year)

DRAMA_MAX_EPISODES_LIMIT = 25
ANIME_MAX_EPISODES_LIMIT = 25
EPISODE_WHITELIST = {"test"}

FILTER_REGIONS = {"中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"}
EXCLUDED_SOURCES = {"非凡", "牛牛", "无尽", "奇异", "猫眼", "ikun"}
QIANGXIAN_KEYWORDS = ['TC', 'TS', '抢先', 'HC']

ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
IMAGE_PROXY_TEMPLATES = [
    "https://images.weserv.nl/?url={host_and_path}",
    "https://wsrv.nl/?url={host_and_path}",
]

_std_session = requests.Session()


# =============================================================
# 网络异常类
# =============================================================
class FetchError(Exception):
    pass

class NoRetryFetchError(FetchError):
    pass


# =============================================================
# CDP 启动与端口探测
# =============================================================
def cdp_alive(port=CDP_PORT, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except Exception:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            json.loads(r.read().decode("utf-8", "ignore"))
        return True
    except Exception:
        return False


def cdp_launch_command():
    return (
        'open -na "Google Chrome" --args \\\n'
        f'  --user-data-dir="{USER_DATA_DIR}" \\\n'
        f'  --remote-debugging-port={CDP_PORT} \\\n'
        f'  {DOMAIN}/'
    )


def launch_chrome_for_cdp(open_url=True):
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    if cdp_alive():
        print(f">>> [CDP] 端口 {CDP_PORT} 已在监听，无需重复启动。")
        print(f">>> [CDP] 请在该 Chrome 窗口打开 {DOMAIN}/ 手动过一次验证。")
        return True

    print(">>> [CDP] 正在启动 Chrome（若已有 Chrome 在运行，请先 ⌘Q 完全退出！）")
    args = [
        f"--user-data-dir={USER_DATA_DIR}",
        f"--remote-debugging-port={CDP_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if open_url:
        args.append(DOMAIN + "/")

    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-na", "Google Chrome", "--args"] + args)
        else:
            subprocess.Popen(["google-chrome"] + args)
    except Exception as e:
        print(f"!!! 启动失败：{e}\n请手动执行：\n{cdp_launch_command()}")
        return False

    for _ in range(30):
        time.sleep(1)
        if cdp_alive():
            print(f">>> [CDP] Chrome 已就绪（端口 {CDP_PORT}）")
            print(">>> 请在窗口里手动勾选过 Cloudflare/滑块验证，然后另开终端执行：")
            print("        python Crawl_pdy0.py cdp fast")
            return True

    print("!!! 等待调试端口超时。可能是已有 Chrome 实例占用了 profile。")
    print("    请先执行：osascript -e 'quit app \"Google Chrome\"'  再重试。")
    print("    或手动执行：\n" + cdp_launch_command())
    return False


# =============================================================
# DOM 状态与抓取层 (BrowserFetcher)
# =============================================================
_STATE_JS = """
() => {
  const q = s => !!document.querySelector(s);
  const hasSite = q('.vod-list') || q('.vod-info') || q('.vlist') || q('.playlist-box') ||
                  q('#index-vod-1') || q('div.name h3') || q('.otherbox') ||
                  q('a[href*="/mv/"]') || q('a[href*="/vod/"]') || q('a[href*="/detail/"]') || q('a[href*="/ms/"]');
  const cfFrame = Array.from(document.querySelectorAll('iframe'))
                       .some(f => (f.src || '').includes('challenges.cloudflare.com'));
  const hasChl  = cfFrame || q('#challenge-form') || q('#challenge-running') ||
                  q('#cf-challenge-running') || q('.cf-turnstile') ||
                  q('#turnstile-wrapper') || q('#challenge-stage');
  const title   = document.title || '';
  const titleChl = /just a moment|attention required|checking your browser|verify|请稍候|稍等|安全检查/i.test(title);
  const len = (document.body && document.body.innerText) ? document.body.innerText.length : 0;
  return { hasSite, hasChl, titleChl, len, title };
}
"""

def _looks_like_challenge(html: str) -> bool:
    if not html or len(html) < 200:
        return True
    head = html[:8000]
    hit_challenge = any(m in head for m in CHALLENGE_MARKERS)
    if not hit_challenge:
        return False
    if any(m in html for m in SITE_MARKERS):
        return False
    return True


class BrowserFetcher:
    """真实 Chrome 抓取层，支持 CDP 附着与 curl_cffi 高速通道双模降级"""
    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None
        self._browser = None
        self.ua = ""
        self._fast = None
        self._fast_ok = False
        self._fast_disabled = False
        self._fast_sync_at = 0.0
        self._fast_resync_fail = 0
        self._impersonate = None

    def start(self):
        if self._ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("!!! 未安装 playwright，请先执行：pip install playwright")
            raise

        self._pw = sync_playwright().start()

        if USE_CDP:
            if not cdp_alive():
                print(f"\n!!! 没有检测到可用的 Chrome 调试端口 {CDP_ENDPOINT}\n")
                print("请先执行：")
                print("    osascript -e 'quit app \"Google Chrome\"'")
                print("    python Crawl_pdy0.py open")
                print("或手动执行：")
                print(cdp_launch_command())
                raise FetchError("CDP 端口不可用")

            print(f">>> [浏览器] 正在附着到已运行的 Chrome：{CDP_ENDPOINT}")
            self._browser = self._pw.chromium.connect_over_cdp(CDP_ENDPOINT)
            self._ctx = (self._browser.contexts[0]
                         if self._browser.contexts else self._browser.new_context())
        else:
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            print(f">>> [浏览器] 启动真实 Chrome（profile: {USER_DATA_DIR}）")
            launch_kwargs = dict(
                user_data_dir=USER_DATA_DIR,
                headless=HEADLESS,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1360, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--start-maximized",
                ],
                ignore_default_args=["--enable-automation"],
            )
            if BROWSER_CHANNEL:
                launch_kwargs["channel"] = BROWSER_CHANNEL
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e:
                print(f">>> [浏览器] 用系统 Chrome 启动失败({e})，改用 Playwright 自带 Chromium")
                launch_kwargs.pop("channel", None)
                self._ctx = self._pw.chromium.launch_persistent_context(**launch_kwargs)

        self._ctx.set_default_timeout(NAV_TIMEOUT_MS)
        self._ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)

        if not USE_CDP:
            try:
                self._ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                )
            except Exception:
                pass

        self._page = self._pick_page()

        try:
            self.ua = self._page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            self.ua = ""

        self._report_clearance()

        print(f">>> [浏览器] 预热首页，检查 Cloudflare 状态 ...")
        try:
            self.get_html(DOMAIN + "/", warmup=True)
            print(">>> [浏览器] 已可正常访问站点 ✅")
        except Exception as e:
            print(f">>> [浏览器] 预热异常（不致命，继续）：{e}")

        if FAST_MODE:
            self._sync_fast_session()

    def _pick_page(self):
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        for p in pages:
            try:
                if TARGET_DOMAIN in (p.url or ""):
                    return p
            except Exception:
                continue
        if pages:
            return pages[0]
        return self._ctx.new_page()

    def _report_clearance(self):
        try:
            cookies = {c["name"]: c["value"] for c in self._ctx.cookies(DOMAIN)}
        except Exception:
            cookies = {}
        if "cf_clearance" in cookies:
            print(">>> [Cloudflare] 已检测到 cf_clearance cookie ✅")
        else:
            print(">>> [Cloudflare] 未检测到 cf_clearance cookie ⚠️")
            if USE_CDP:
                print(f"    建议：先在这个 Chrome 窗口打开 {DOMAIN}/ 手动过一次验证。")

    def close(self):
        try:
            if self._ctx and not USE_CDP:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = self._page = self._browser = None

    def _page_state(self):
        try:
            info = self._page.evaluate(_STATE_JS)
        except Exception:
            return "unknown", ""
        try:
            html = self._page.content()
        except Exception:
            html = ""
        try:
            cf_frame = any("challenges.cloudflare.com" in (f.url or "")
                           for f in self._page.frames)
        except Exception:
            cf_frame = False

        if info.get("hasSite"):
            return "site", html
        if info.get("hasChl") or info.get("titleChl") or cf_frame:
            return "challenge", html
        if info.get("len", 0) < 50:
            return "unknown", html
        return "unknown", html

    def _notify_challenge(self, url):
        print("\a", end="", flush=True)
        print("\n" + "=" * 72)
        print("  ⚠️  检测到 Cloudflare 人机验证页面，脚本已暂停")
        print("  👉  请切到 Chrome 窗口，勾选 “确认您是真人 / Verify you are human”")
        print(f"  ⏳  脚本至少会等你 {CHALLENGE_GRACE} 秒，最长等待 {CHALLENGE_WAIT} 秒。")
        print(f"      URL: {url}")
        if not USE_CDP:
            print("-" * 72)
            print("  💡 强烈建议改用【手动过验证 + CDP 附着】：")
            print("       1) osascript -e 'quit app \"Google Chrome\"'")
            print("       2) python Crawl_pdy0.py open")
            print("       3) 在窗口里手动过验证")
            print("       4) python Crawl_pdy0.py cdp fast")
        print("=" * 72 + "\n")
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        if platform.system() == "Darwin":
            try:
                subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'],
                               check=False, capture_output=True)
            except Exception:
                pass

    def _try_click_turnstile(self) -> bool:
        try:
            for fr in self._page.frames:
                if "challenges.cloudflare.com" not in (fr.url or ""):
                    continue
                for sel in ("input[type=checkbox]",
                            "#challenge-stage input[type=checkbox]",
                            "label.ctp-checkbox-label",
                            "#cf-stage input"):
                    try:
                        loc = fr.locator(sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.click(timeout=2000)
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    def _wait_until_ready(self, url, _depth=0):
        soft_deadline = time.time() + SITE_READY_TIMEOUT
        hard_deadline = time.time() + CHALLENGE_WAIT
        challenge_seen = False
        grace_until = 0.0
        next_click_at = 0.0
        last_tip = 0.0
        stable = 0
        html = ""

        while True:
            state, html = self._page_state()

            if state == "site" and not (challenge_seen and time.time() < grace_until):
                stable += 1
                need = PASS_STABLE_HITS if challenge_seen else 1
                if stable >= need:
                    if challenge_seen:
                        print("    ✅ 人机验证已通过，继续抓取\n")
                        time.sleep(1.0)
                        cur = (self._page.url or "").split("#")[0].rstrip("/")
                        tgt = url.split("#")[0].rstrip("/")
                        if _depth == 0 and cur != tgt:
                            self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                            time.sleep(PAGE_SETTLE)
                            return self._wait_until_ready(url, _depth=1)
                        try:
                            html = self._page.content()
                        except Exception:
                            pass
                        if FAST_MODE:
                            self._sync_fast_session()
                    return html
            else:
                stable = 0

            if state == "challenge":
                if not challenge_seen:
                    challenge_seen = True
                    self._notify_challenge(url)
                    grace_until   = time.time() + CHALLENGE_GRACE
                    next_click_at = time.time() + AUTO_CLICK_FIRST_DELAY
                    last_tip = time.time()
                if AUTO_CLICK_TURNSTILE and time.time() >= next_click_at:
                    if self._try_click_turnstile():
                        print("    [自动] 已尝试点击 Turnstile 复选框")
                    next_click_at = time.time() + AUTO_CLICK_EVERY

            if challenge_seen:
                if time.time() - last_tip > 20:
                    print(f"    ... 仍在等待人机验证（剩余 {int(hard_deadline - time.time())}s）")
                    last_tip = time.time()
                if time.time() > hard_deadline:
                    raise FetchError(f"等待 Cloudflare 人机验证超时: {url}")
            else:
                if time.time() > soft_deadline:
                    return html

            time.sleep(POLL_INTERVAL)

    def get_html(self, url, warmup=False):
        self.start()

        fast = self._fast_get(url)
        if fast is not None:
            return fast

        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        status = resp.status if resp else 0
        if status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")

        time.sleep(PAGE_SETTLE)
        html = self._wait_until_ready(url)

        if status >= 500 or status == 429:
            state, _ = self._page_state()
            if state != "site":
                raise FetchError(f"HTTP {status}: {url}")

        return html

    def _make_fast_session(self):
        last_err = None
        candidates = ([self._impersonate] if self._impersonate else []) + FAST_IMPERSONATE_CANDIDATES
        for imp in candidates:
            if not imp:
                continue
            try:
                s = c_requests.Session(impersonate=imp)
                if self._impersonate != imp:
                    print(f">>> [FAST] 使用 TLS 指纹: {imp}")
                self._impersonate = imp
                return s
            except Exception as e:
                last_err = e
                continue
        print(f">>> [FAST] 无法创建 curl_cffi Session：{last_err}")
        return None

    def _sync_fast_session(self, verbose=True):
        if self._fast_disabled or not FAST_MODE:
            return
        try:
            cookies = {c["name"]: c["value"] for c in self._ctx.cookies(DOMAIN)}
        except Exception:
            cookies = {}
        if not cookies:
            self._fast_ok = False
            if verbose:
                print(">>> [FAST] 浏览器暂无 cookie，继续使用浏览器通道")
            return

        s = self._make_fast_session()
        if s is None:
            self._fast_ok = False
            self._fast_disabled = True
            return

        s.headers.update({
            "User-Agent": self.ua or s.headers.get("User-Agent", ""),
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,image/apng,*/*;q=0.8"),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": DOMAIN + "/",
            "Upgrade-Insecure-Requests": "1",
        })
        self._fast = (s, cookies)
        self._fast_ok = True
        self._fast_sync_at = time.time()
        if verbose:
            has_clr = "cf_clearance" in cookies
            print(f">>> [FAST] 已同步 {len(cookies)} 个 cookie 到快速通道 "
                  f"(cf_clearance: {'有 ✅' if has_clr else '无 ⚠️'})")

    def _fast_get(self, url, is_binary=False):
        if not FAST_MODE or self._fast_disabled:
            return None

        if self._fast_ok and (time.time() - self._fast_sync_at > FAST_RESYNC_INTERVAL):
            self._sync_fast_session(verbose=False)

        if not (self._fast_ok and self._fast):
            return None

        s, cookies = self._fast
        try:
            r = s.get(url, cookies=cookies, timeout=REQUEST_TIMEOUT, allow_redirects=True, verify=False)
            if r.status_code in (403, 503):
                print(f"    [FAST] HTTP {r.status_code}，重新同步 cookie 后本次降级浏览器通道")
                self._fast_ok = False
                self._sync_fast_session(verbose=False)
                if self._fast_ok:
                    self._fast_resync_fail += 1
                    if self._fast_resync_fail >= FAST_MAX_RESYNC_FAIL:
                        print("    [FAST] 连续多次被拦，本次运行关闭 FAST 通道")
                        self._fast_ok = False
                        self._fast_disabled = True
                return None
            if r.status_code == 404:
                raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
            if r.status_code >= 400:
                return None

            if is_binary:
                self._fast_resync_fail = 0
                return r.content

            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding or "utf-8"
            if _looks_like_challenge(r.text):
                print("    [FAST] 命中挑战页，重新同步 cookie 后本次降级浏览器通道")
                self._fast_ok = False
                self._sync_fast_session(verbose=False)
                return None

            self._fast_resync_fail = 0
            return r.text
        except NoRetryFetchError:
            raise
        except Exception as e:
            print(f"    [FAST] 请求异常({e})，本次降级浏览器通道")
            self._fast_ok = False
            self._sync_fast_session(verbose=False)
            return None

    def get_bytes(self, url):
        self.start()
        fast = self._fast_get(url, is_binary=True)
        if fast is not None:
            return fast
        r = self._ctx.request.get(url, timeout=REQUEST_TIMEOUT * 1000)
        if r.status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status >= 400:
            raise FetchError(f"HTTP {r.status}: {url}")
        return r.body()


_fetcher = BrowserFetcher()
atexit.register(_fetcher.close)


def fetch(url: str, is_binary: bool = False) -> str | bytes | None:
    """统一的网络请求入口（带重试与降级退避）"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if is_binary:
                return _fetcher.get_bytes(url)
            return _fetcher.get_html(url)
        except NoRetryFetchError:
            return None
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                if "验证" in str(e) or "Cloudflare" in str(e):
                    wait = max(wait, 15)
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    log(f"  [请求彻底失败] {url} -> {last_err}", force=True)
    return None


# =============================================================
# 抓取任务总配置
# =============================================================
def get_year_config(year: str):
    return {
        "year": year,
        "categories": {
            "Movie": {"id": 1, "enabled": True,  "pages": 0},
            "Drama": {"id": 2, "enabled": True,  "pages": 1},
            "Show":  {"id": 3, "enabled": True,  "pages": 0},
            "Anime": {"id": 4, "enabled": True,  "pages": 0},
        }
    }


historical_jobs = [get_year_config(str(y)) for y in range(1990, 1985, -1)]

TASKS = [
    {
        "sort_type": "score",
        "enabled": False,
        "jobs": [*historical_jobs],
    },
    {
        "sort_type": "score",
        "enabled": False,
        "jobs": [
            {
                "year": "",
                "categories": {
                    "Movie": {"id": 1, "enabled": True, "pages": 4},
                    "Drama": {"id": 2, "enabled": True, "pages": 3},
                    "Show":  {"id": 3, "enabled": True, "pages": 2},
                    "Anime": {"id": 4, "enabled": True, "pages": 2},
                }
            },
        ]
    },
    {
        "sort_type": "hits",
        "enabled": True,
        "jobs": [
            {"year": "",
             "categories": {
                 "Movie": {"id": 1, "enabled": True, "pages": 1, "skip_score_filter": True},
                 "Drama": {"id": 2, "enabled": True, "pages": 1},
                 "Show": {"id": 3, "enabled": True, "pages": 1},
                 "Anime": {"id": 4, "enabled": True, "pages": 1}
             }
             },
        ]
    },
    {
        "sort_type": "time",
        "enabled": True,
        "jobs": [
            {"year": "2026",
             "categories": {
                 "Movie": {"id": 1, "enabled": True, "pages": 1, "skip_score_filter": True},
                 "Drama": {"id": 2, "enabled": True, "pages": 0},
                 "Show": {"id": 3, "enabled": True, "pages": 0},
                 "Anime": {"id": 4, "enabled": True, "pages": 0}
             }
             },
        ]
    },
    {
        "sort_type": "index",
        "enabled": True,
        "jobs": [
            {"year": "",
             "categories": {
                 "Movie": {"id": 1, "enabled": True},
                 "Drama": {"id": 2, "enabled": True},
                 "Show":  {"id": 3, "enabled": True},
                 "Anime": {"id": 4, "enabled": True},
             }
             },
        ]
    },
]


# =============================================================
# URL 辅助与业务工具函数
# =============================================================
def get_all_url_keys(item: dict) -> list[str]:
    keys = [k for k in item.keys()
            if k == "url" or (k.startswith("url") and k[3:].isdigit())]

    def _sort_key(k):
        return -1 if k == "url" else int(k[3:])

    return sorted(keys, key=_sort_key)


def append_new_url_fields(old_entry: dict, ordered_detail: dict, new_url: str) -> str:
    old_url_keys = get_all_url_keys(old_entry)
    existing_url_vals = []
    max_idx = 0

    for k in old_url_keys:
        v = old_entry.get(k, "")
        existing_url_vals.append(v)
        if k != "url":
            ordered_detail[k] = v
            m = re.match(r"^url(\d+)$", k)
            if m:
                max_idx = max(max_idx, int(m.group(1)))

    if not new_url or new_url in existing_url_vals:
        return ""

    next_key = f"url{max_idx + 1}"
    ordered_detail[next_key] = new_url
    return next_key


def format_date_str(date_str: str) -> str:
    if not date_str:
        return date_str
    if '/' in date_str or '／' in date_str:
        parts = re.split(r'[/／]', date_str)
        date_str = parts[-1].strip()
    try:
        parts = re.findall(r'\d+', date_str)
        if len(parts) >= 3:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        elif len(parts) == 2:
            return f"{parts[0]}-{parts[1].zfill(2)}"
        elif len(parts) == 1:
            return parts[0]
    except Exception:
        pass
    return date_str


def get_url_path(url: str) -> str:
    try:
        return urlparse(url).path
    except Exception:
        return url


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fa5]", text or ""))


def extract_episode_num(ep_name: str) -> int:
    m = re.search(r"(\d+)", ep_name)
    return int(m.group(1)) if m else 0


def extract_video_id(url: str, name: str) -> str:
    m = re.search(r"/(?:mv|vod|detail)/(\d+)", url)
    if m:
        return m.group(1)
    safe = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", name).strip("_")
    return safe or "unknown"


# =============================================================
# 数据持久化：安全读 / 安全写 / 备份
# =============================================================
def count_items(data: dict) -> int:
    if not isinstance(data, dict):
        return 0
    return sum(len(v) for v in data.values() if isinstance(v, list))


def _read_json_strict(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    if not txt.strip():
        raise ValueError("文件内容为空（0 字节或全空白）")
    data = json.loads(txt)
    if not isinstance(data, dict):
        raise ValueError(f"顶层结构不是 dict，而是 {type(data).__name__}")
    return data


def _backup_candidates() -> list[str]:
    cands = [BAK_FILE]
    try:
        snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")), reverse=True)
        cands.extend(snaps)
    except Exception:
        pass
    return cands


def snapshot_backup(path: str):
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return
        ensure_dir(BACKUP_DIR)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"OVideos_{ts}.json")
        shutil.copy2(path, dst)
        print(f">>> [备份] 启动快照已保存: {dst}")
        snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")))
        if len(snaps) > MAX_BACKUPS:
            for old in snaps[:len(snaps) - MAX_BACKUPS]:
                try:
                    os.remove(old)
                except Exception:
                    pass
    except Exception as e:
        print(f">>> [备份] 创建启动快照失败: {e}")


def load_existing(path: str) -> dict:
    global _BASELINE_TOTAL, _LOAD_OK

    main_exists = os.path.exists(path)
    main_size = os.path.getsize(path) if main_exists else -1

    if main_exists and main_size > 0:
        try:
            data = _read_json_strict(path)
            _BASELINE_TOTAL = count_items(data)
            _LOAD_OK = True
            print(f">>> [读取] 主文件正常: {path} ({main_size/1024:.1f} KB, {_BASELINE_TOTAL} 条)")
            return data
        except Exception as e:
            print(f"\n❌ [严重] 主数据文件损坏，无法解析: {e}")
    elif main_exists:
        print(f"\n❌ [严重] 主数据文件为 0 字节: {path}")

    if main_exists:
        for cand in _backup_candidates():
            if not os.path.exists(cand) or os.path.getsize(cand) == 0:
                continue
            try:
                data = _read_json_strict(cand)
            except Exception as e:
                print(f"   [恢复] 备份也不可用: {cand} -> {e}")
                continue
            n = count_items(data)
            _BASELINE_TOTAL = n
            _LOAD_OK = True
            print(f"✅ [恢复] 已从备份恢复数据: {cand} ({n} 条)")
            save_data(data, force=True, quiet=False)
            return data

        if not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print("脚本已终止：为防止用空数据覆盖你的历史库，本次不会写入任何内容。")
            print("!" * 70 + "\n")
            sys.exit(1)
        _BASELINE_TOTAL = 0
        _LOAD_OK = True
        return {}

    print(f">>> [读取] 主文件不存在，视为首次运行: {path}")
    _BASELINE_TOTAL = 0
    _LOAD_OK = True
    return {}


def save_data(data: dict, force: bool = False, quiet: bool = True) -> bool:
    global _BASELINE_TOTAL

    if not _LOAD_OK or not isinstance(data, dict):
        return False

    total = count_items(data)

    if (not force) and _BASELINE_TOTAL >= SHRINK_GUARD_MIN_ITEMS \
            and total < _BASELINE_TOTAL * ALLOW_SHRINK_RATIO:
        print(f"\n  ⛔ [拒绝保存] 条目数异常缩水：{_BASELINE_TOTAL} -> {total}")
        try:
            with open(REJECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        return False

    try:
        payload = json.dumps(data, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"  [错误] JSON 序列化失败: {e}")
        return False

    tmp_file = OUTPUT_FILE + ".tmp"
    try:
        ensure_dir(os.path.dirname(OUTPUT_FILE))
        if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
            try:
                shutil.copy2(OUTPUT_FILE, BAK_FILE)
            except Exception:
                pass

        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

        _read_json_strict(tmp_file)
        os.replace(tmp_file, OUTPUT_FILE)

        _BASELINE_TOTAL = max(_BASELINE_TOTAL, total)
        if not quiet:
            print(f"  [已保存] {OUTPUT_FILE} 共 {total} 条")
        return True
    except Exception as e:
        print(f"  [错误] 实时保存失败: {e}")
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        return False


def download_cover(img_url: str, video_id: str, log_prefix: str = "") -> str:
    if not img_url:
        return ""

    def _print(msg):
        nonlocal log_prefix
        if log_prefix:
            print(f"{log_prefix} {msg}")
            log_prefix = "    "
        else:
            print(f"     {msg}")

    ensure_dir(COVER_IMAGE_DIR)
    base = img_url.split("?")[0].split("#")[0]
    ext = os.path.splitext(base)[1].lower()
    if ext not in ALLOWED_IMG_EXT:
        ext = ".jpg"

    filename = f"{video_id}{ext}"
    filepath = os.path.join(COVER_IMAGE_DIR, filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return filename

    def _save(content: bytes) -> bool:
        if not content or len(content) < 200:
            return False
        with open(filepath, "wb") as f:
            f.write(content)
        if os.path.getsize(filepath) > 0:
            return True
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

    url_candidates = [img_url]
    if img_url.startswith("https://"):
        url_candidates.append("http://" + img_url[8:])
    elif img_url.startswith("http://"):
        url_candidates.append("https://" + img_url[7:])

    for url in url_candidates:
        content = fetch(url, is_binary=True)
        if content and _save(content):
            _print(f"[封面已下载] {filename}")
            return filename

    _print("[快速降级] 直接走第三方图片代理...")
    parsed = urlparse(img_url)
    host_and_path = parsed.netloc + parsed.path
    if parsed.query:
        host_and_path += "?" + parsed.query
    proxy_headers = {"User-Agent": _fetcher.ua or "Mozilla/5.0"}

    for proxy_tpl in IMAGE_PROXY_TEMPLATES:
        proxy_url = proxy_tpl.format(host_and_path=host_and_path)
        for use_curl in (True, False):
            try:
                if use_curl:
                    resp = c_requests.get(proxy_url, headers=proxy_headers,
                                          timeout=REQUEST_TIMEOUT * 2,
                                          verify=False)
                else:
                    resp = _std_session.get(proxy_url, headers=proxy_headers,
                                            timeout=REQUEST_TIMEOUT * 2, verify=False)
                if resp.status_code == 200 and _save(resp.content):
                    via = proxy_tpl.split("/?")[0]
                    method = "curl_cffi" if use_curl else "requests"
                    _print(f"[封面已下载|proxy/{method}] {filename} via {via}")
                    return filename
            except Exception:
                pass

    return ""


# =============================================================
# 解析与业务逻辑
# =============================================================
def build_index(existing: dict) -> dict:
    idx = {}
    for cat, items in existing.items():
        if isinstance(items, list):
            for list_idx, it in enumerate(items):
                if not isinstance(it, dict):
                    continue
                name = it.get("name", "")
                info = it.get("info", "")
                update = it.get("update", "")
                image = it.get("image", "")

                if name:
                    url_keys = [k for k in it.keys()
                                if k == "url" or (k.startswith("url") and k[3:].isdigit())]
                    for key_name in url_keys:
                        url_val = it.get(key_name, "")
                        if url_val:
                            path = get_url_path(url_val)
                            idx[(name, path)] = {
                                "info": info,
                                "update": update,
                                "image": image,
                                "real_name": name,
                                "real_path": path,
                                "category": cat,
                                "list_idx": list_idx
                            }
    return idx


def parse_list_items(scope, li_selector: str, base_url: str) -> list[dict]:
    items = []
    for li in scope.select(li_selector):
        a = li.select_one("div.name h3 a")
        if not a:
            continue
        name = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")
        if not href:
            continue
        full_url = urljoin(base_url, href)

        info = ""
        s1 = li.select_one(".pic span.s1")
        if s1:
            tmp = BeautifulSoup(str(s1), "html.parser")
            for i in tmp.find_all("i"):
                i.decompose()
            info = clean_ws(tmp.get_text(" ", strip=True))

        score_val = 0.0
        s2 = li.select_one(".pic span.s2")
        if s2:
            score_text = clean_ws(s2.get_text(strip=True))
            if score_text and score_text != "--":
                try:
                    score_val = float(score_text)
                except ValueError:
                    score_val = 0.0

        item_year = ""
        item_region = ""
        status_p = li.select_one("div.name p.item-status")
        if status_p:
            status_text = clean_ws(status_p.get_text(strip=True))
            year_match = re.match(r"^(\d{4})", status_text)
            if year_match:
                item_year = year_match.group(1)
            parts = [p.strip() for p in re.split(r'[/／]', status_text)]
            if len(parts) >= 2:
                item_region = parts[1]

        items.append({
            "name": name,
            "url": full_url,
            "info": info,
            "score": score_val,
            "year": item_year,
            "region": item_region
        })
    return items


def parse_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    return parse_list_items(soup, "div.vod-list ul.row > li", DETAIL_BASE_URL)


def parse_homepage(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    cat_map = {1: "Movie", 2: "Drama", 3: "Show", 4: "Anime"}
    result = {}
    for sec_id, cat_name in cat_map.items():
        section = soup.select_one(f"#index-vod-{sec_id}")
        if section:
            result[cat_name] = parse_list_items(section, "div.vlist ul.row > li", INDEX_BASE_URL)
        else:
            result[cat_name] = []
    return result


def _split_by_slash(span) -> list[str]:
    return [a.get_text(strip=True) for a in span.find_all("a")
            if a.get_text(strip=True) and a.get_text(strip=True) != "[展开...]"]


def _find_span_by_label(info_block, label: str):
    for span in info_block.find_all("span"):
        text = span.get_text(" ", strip=True)
        if text.startswith(label):
            return span
    return None


def parse_playlist(soup, base_url: str = DETAIL_BASE_URL) -> list[dict]:
    online_section = (soup.select_one("#url-content1")
                      or soup.select_one(".playlist-box")
                      or soup)

    tabs = online_section.select(".playlist-tab ul.swiper-wrapper > li.swiper-slide")
    if not tabs:
        return []

    collected_sources = {}

    for tab in tabs:
        target = tab.get("data-target", "")
        if not target:
            continue
        channel_name = ""
        for content in tab.contents:
            if isinstance(content, str) and content.strip():
                channel_name = content.strip()
                break
        if not channel_name:
            channel_name = tab.get_text(strip=True)

        channel_name = channel_name.replace('"', '').replace('“', '').replace('”', '').strip()
        badge_ele = tab.select_one(".badge")
        if badge_ele:
            badge_text = badge_ele.get_text(strip=True)
            if badge_text and channel_name.endswith(badge_text):
                channel_name = channel_name[:-len(badge_text)].strip()

        ul_id = target.lstrip("#")
        ul = online_section.find("ul", id=ul_id)

        episodes = {}
        if ul:
            for a in ul.select("li a"):
                href = a.get("href", "")
                ep_name = a.get_text(strip=True)
                if href and ep_name:
                    episodes[ep_name] = urljoin(base_url, href)

        if episodes:
            if channel_name in collected_sources:
                existing_ep_len = len(collected_sources[channel_name].get("episodes", {}))
                if len(episodes) > existing_ep_len:
                    collected_sources[channel_name] = {"name": channel_name, "episodes": episodes}
            else:
                collected_sources[channel_name] = {"name": channel_name, "episodes": episodes}

    allowed_playlist = []
    excluded_playlist = []

    for item in collected_sources.values():
        if item["name"] in EXCLUDED_SOURCES:
            excluded_playlist.append(item)
        else:
            allowed_playlist.append(item)

    return allowed_playlist if allowed_playlist else excluded_playlist


def parse_detail_page(html: str, name: str, url: str,
                      info: str = "", base_url: str = DETAIL_BASE_URL,
                      list_year: str = "", skip_score_filter: bool = False,
                      cat_name: str = "", sort_type: str = "") -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    playlist = parse_playlist(soup, base_url)
    if not playlist:
        log(f"     [警告] 没有有效播放源，跳过该条目: {name}", force=True)
        return None

    update_time = ""
    otherbox = soup.select_one("div.vod-info .otherbox") or soup.select_one(".otherbox")
    if otherbox:
        ems = otherbox.find_all("em")
        if ems:
            last_text = clean_ws(ems[-1].get_text(strip=True))
            if re.search(r"\d{4}-\d{2}-\d{2}", last_text):
                update_time = last_text
            elif len(ems) >= 2:
                update_time = clean_ws(ems[-1].get_text(strip=True))

    data = {
        "name": name,
        "url": url,
        "info": info,
        "update": update_time,
        "image": "",
        "导演": "",
        "编剧": [],
        "主演": [],
        "类型": [],
        "地区": "",
        "date": "",
        "alias": "",
        "intro": "",
        "评分": {"豆瓣": "", "IMDB": ""},
        "playlist": playlist,
    }

    info_block = soup.select_one("div.vod-info .info") or soup

    span = _find_span_by_label(info_block, "导演：")
    if span:
        directors = _split_by_slash(span)
        data["导演"] = directors[0] if directors else ""

    span = _find_span_by_label(info_block, "编剧：")
    if span:
        data["编剧"] = _split_by_slash(span)

    span = info_block.select_one("span.zksq-actor") or _find_span_by_label(info_block, "主演：")
    if span:
        data["主演"] = _split_by_slash(span)

    span = _find_span_by_label(info_block, "类型：")
    if span:
        data["类型"] = _split_by_slash(span)

    span = _find_span_by_label(info_block, "地区：")
    if span:
        regions = _split_by_slash(span)
        data["地区"] = regions[0] if regions else ""

    for span in info_block.find_all("span"):
        text = span.get_text(" ", strip=True)
        if text.startswith("上映："):
            cleaned = clean_ws(text)
            cleaned = cleaned.replace("上映：", "", 1)
            cleaned = re.sub(r"\((.*?)(网络)\)", r"(\1)", cleaned)
            data["date"] = format_date_str(cleaned)
        elif text.startswith("又名："):
            cleaned = text.replace("又名：", "", 1)
            data["alias"] = clean_ws(cleaned)

    span = _find_span_by_label(info_block, "评分：")
    if span:
        full_span_text = clean_ws(span.get_text(" ", strip=True))
        has_platform_match = False
        for s in span.find_all("span"):
            t = clean_ws(s.get_text(" ", strip=True))
            if t:
                match = re.search(r"(豆瓣|IMDB)\s*([0-9.]+|--)", t, re.IGNORECASE)
                if match:
                    platform = match.group(1)
                    if platform.upper() == "IMDB":
                        platform = "IMDB"
                    score = match.group(2)
                    if score != "--":
                        data["评分"][platform] = score
                        has_platform_match = True

        if not has_platform_match and full_span_text:
            num_match = re.search(r"评分：\s*([0-9.]+)", full_span_text)
            if num_match:
                data["评分"]["豆瓣"] = num_match.group(1)

    detail_year = ""
    if data.get("date"):
        ym = re.match(r"(\d{4})", data["date"])
        if ym:
            detail_year = ym.group(1)
    if not detail_year:
        detail_year = list_year

    candidate_scores = []
    for platform in ("豆瓣", "IMDB"):
        val = data["评分"].get(platform, "")
        if val and val != "--":
            try:
                candidate_scores.append(float(val))
            except ValueError:
                pass
    has_rating = len(candidate_scores) > 0
    max_score = max(candidate_scores) if candidate_scores else 0.0
    is_erotic = any("情色" in t for t in data.get("类型", []))
    region = data.get("地区", "")
    is_current_year = (detail_year == CURRENT_YEAR)
    movie_region_mode = (cat_name == "Movie" and sort_type in ("hits", "time"))

    if movie_region_mode:
        if not is_erotic:
            if is_current_year:
                if region in FILTER_REGIONS:
                    if (not has_rating) or (max_score < OLD_VIDEO_MIN_SCORE):
                        log(f"     ⚠️[跳过-过滤地区新片评分不达标] {name} (最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})", force=True)
                        return None
                else:
                    if has_rating and max_score < OLD_VIDEO_MIN_SCORE:
                        log(f"     ⚠️[跳过-非过滤地区新片评分过低] {name} (最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})", force=True)
                        return None
            else:
                if max_score < OLD_VIDEO_MIN_SCORE:
                    log(f"     ⚠️[跳过-老片评分过低] {name} (年份: {detail_year}, 最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})", force=True)
                    return None
    else:
        should_check_score = False
        if detail_year:
            if detail_year != CURRENT_YEAR:
                should_check_score = True
            elif not skip_score_filter:
                should_check_score = True

        if should_check_score:
            if max_score < OLD_VIDEO_MIN_SCORE and not is_erotic:
                log(f"     ⚠️[跳过-评分过低] {name} (最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})", force=True)
                return None

    img_url = ""
    pic_img = soup.select_one("div.vod-info .pic img")
    if pic_img:
        img_url = (pic_img.get("data-original")
                   or pic_img.get("data-src")
                   or pic_img.get("src")
                   or "").strip()
        if img_url.startswith("//"):
            img_url = "https:" + img_url

    data["_img_url"] = img_url
    data["image"] = ""

    intro_box = soup.select_one("div.more-box.zksq-content")
    if intro_box:
        for a in intro_box.find_all("a"):
            a.decompose()
        intro_text = intro_box.get_text(" ", strip=True)
        intro_text = re.sub(r"^剧情介绍[:：]", "", intro_text)
        data["intro"] = clean_ws(intro_text)

    return data


def merge_and_sort_playlist(old_playlist: list[dict], new_playlist: list[dict],
                            cat_name: str, info_text: str) -> tuple[list[dict], bool, list[str]]:
    if not old_playlist:
        return new_playlist, True, ["初始化播放源列表"]

    old_map = {p["name"]: p for p in old_playlist}
    old_max_ep = max((len(p.get("episodes", {})) for p in old_playlist), default=0)

    is_qiangxian = any(kw.upper() in info_text.upper() for kw in QIANGXIAN_KEYWORDS)

    front_channels = []
    back_channels = []
    updated_channel_names = set()
    details = []

    for new_p in new_playlist:
        name = new_p["name"]
        new_eps = new_p.get("episodes", {})
        new_ep_count = len(new_eps)

        has_ep_qiangxian = any(any(kw.upper() in ep_name.upper() for kw in QIANGXIAN_KEYWORDS)
                               for ep_name in new_eps.keys())

        if name not in old_map:
            if cat_name == "Movie":
                if not (is_qiangxian or has_ep_qiangxian):
                    front_channels.append(new_p)
                    details.append(f"新增播放源 [{name}] (共 {new_ep_count} 集并置顶)")
                else:
                    back_channels.append(new_p)
                    details.append(f"新增抢先播放源 [{name}] (共 {new_ep_count} 集追加末尾)")
            else:
                if new_ep_count >= old_max_ep:
                    front_channels.append(new_p)
                    details.append(f"新增播放源 [{name}] (共 {new_ep_count} 集 >= 原最大 {old_max_ep} 集并置顶)")
                else:
                    back_channels.append(new_p)
                    details.append(f"新增播放源 [{name}] (共 {new_ep_count} 集 < 原最大 {old_max_ep} 集追加末尾)")
            updated_channel_names.add(name)
        else:
            old_p = old_map[name]
            old_eps = old_p.get("episodes", {})

            if cat_name != "Movie" and len(new_eps) < len(old_eps):
                new_p["episodes"] = old_eps
                new_eps = old_eps
                new_ep_count = len(old_eps)

            if old_eps != new_eps:
                old_ep_count = len(old_eps)
                ep_change_desc = (f"集数 {old_ep_count} -> {new_ep_count}"
                                  if old_ep_count != new_ep_count else "播放链接更新")

                if cat_name == "Movie":
                    if not (is_qiangxian or has_ep_qiangxian):
                        front_channels.append(new_p)
                        details.append(f" [{name}] 更新 ({ep_change_desc}并置顶)")
                    else:
                        back_channels.append(new_p)
                        details.append(f" [{name}] 更新 ({ep_change_desc})")
                else:
                    if new_ep_count >= old_max_ep:
                        front_channels.append(new_p)
                        details.append(f" [{name}] 更新 ({ep_change_desc}并置顶)")
                    else:
                        back_channels.append(new_p)
                        details.append(f" [{name}] 更新 ({ep_change_desc})")
                updated_channel_names.add(name)

    final_playlist = []
    for p in front_channels:
        if p not in final_playlist:
            final_playlist.append(p)

    for old_p in old_playlist:
        if old_p["name"] not in updated_channel_names:
            final_playlist.append(old_p)
        elif old_p["name"] in [p["name"] for p in back_channels]:
            match_back = next((p for p in back_channels if p["name"] == old_p["name"]), None)
            if match_back and match_back not in final_playlist:
                final_playlist.append(match_back)

    for p in back_channels:
        if p not in final_playlist:
            final_playlist.append(p)

    has_changed = (final_playlist != old_playlist)
    if has_changed and not details:
        details.append("播放源顺序重排")

    return final_playlist, has_changed, details


def build_list_url(cat_id: int, page: int, year: str, sort_type: str) -> str:
    if sort_type == "score":
        return (f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---{year}.html"
                if year else f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---.html")
    elif sort_type == "hits":
        return f"{LIST_BASE_URL}/ms/{cat_id}--hits------{page}---.html"
    elif sort_type == "time":
        return (f"{LIST_BASE_URL}/ms/{cat_id}--time------{page}---{year}.html"
                if year else f"{LIST_BASE_URL}/ms/{cat_id}--time------{page}---.html")
    else:
        raise ValueError(f"未知的 sort_type: {sort_type}")


def process_item(item: dict, cat_name: str,
                 all_data: dict, global_index: dict,
                 detail_base_url: str = DETAIL_BASE_URL,
                 skip_score_filter: bool = False,
                 idx_i: int = 0, total: int = 0,
                 sort_type: str = "") -> str:
    if cat_name == "Show":
        if item["year"] != CURRENT_YEAR:
            log(f"  ({idx_i}/{total}) [跳过-年份不符] {item['name']} (年份: '{item['year']}' != '{CURRENT_YEAR}')")
            return "skipped"
        if item["region"] in FILTER_REGIONS:
            log(f"  ({idx_i}/{total}) [跳过-黑名单地区] {item['name']} (地区: '{item['region']}')")
            return "skipped"

    elif cat_name == "Drama":
        if (not skip_score_filter) and item["score"] < MIN_SCORE_LIMIT:
            log(f"  ({idx_i}/{total}) [跳过-评分过低] {item['name']} (当前评分: {item['score']} < {MIN_SCORE_LIMIT})")
            return "skipped"
        if item["region"] in FILTER_REGIONS:
            if item["score"] > 7.0:
                log(f"  ({idx_i}/{total}) [破格放行-高分黑名单地区] {item['name']} (地区: '{item['region']}', 评分: {item['score']} > 7.0)", force=True)
            else:
                log(f"  ({idx_i}/{total}) [跳过-黑名单地区] {item['name']} (地区: '{item['region']}')")
                return "skipped"

    elif cat_name == "Anime":
        if (not skip_score_filter) and item["score"] < MIN_SCORE_LIMIT:
            log(f"  ({idx_i}/{total}) [跳过-评分过低] {item['name']} (评分: {item['score']} < {MIN_SCORE_LIMIT})")
            return "skipped"
        if item["region"] in FILTER_REGIONS:
            if item["score"] > 7.0:
                log(f"  ({idx_i}/{total}) [破格放行-高分黑名单地区] {item['name']} (地区: '{item['region']}', 评分: {item['score']} > 7.0)", force=True)
            else:
                log(f"  ({idx_i}/{total}) [跳过-黑名单地区] {item['name']} (地区: '{item['region']}')")
                return "skipped"

    else:
        if (not skip_score_filter) and 0 < item["score"] < MIN_SCORE_LIMIT:
            log(f"  ({idx_i}/{total}) [跳过-评分过低] {item['name']} (当前评分: {item['score']} < {MIN_SCORE_LIMIT})")
            return "skipped"

    item_path = get_url_path(item["url"])

    key = (item["name"], item_path)
    old_data = global_index.get(key)
    matched_by_path_only = False
    matched_by_name_only = False

    if old_data is None:
        for idx_key, idx_val in global_index.items():
            if idx_val.get("real_path") == item_path:
                old_data = idx_val
                key = idx_key
                matched_by_path_only = True
                break

    if old_data is None:
        for cat, existing_list in all_data.items():
            if not isinstance(existing_list, list):
                continue
            for list_idx, existing_item in enumerate(existing_list):
                if not isinstance(existing_item, dict):
                    continue
                if existing_item.get("name") == item["name"]:
                    old_url_keys = get_all_url_keys(existing_item)
                    first_url_val = existing_item.get(old_url_keys[0], "") if old_url_keys else ""
                    old_data = {
                        "info": existing_item.get("info", ""),
                        "update": existing_item.get("update", ""),
                        "image": existing_item.get("image", ""),
                        "real_name": existing_item.get("name", ""),
                        "real_path": get_url_path(first_url_val) if first_url_val else "",
                        "category": cat,
                        "list_idx": list_idx
                    }
                    key = (existing_item.get("name", item["name"]),
                           get_url_path(first_url_val) if first_url_val else item_path)
                    matched_by_name_only = True
                    break
            if matched_by_name_only:
                break

    is_update = (old_data is not None)

    detail_html = fetch(item["url"])
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not detail_html:
        log(f"  ({idx_i}/{total}) [跳过-请求详情页失败] {item['name']}", force=True)
        return "skipped"

    try:
        detail = parse_detail_page(detail_html, item["name"], item["url"],
                                   info=item["info"], base_url=detail_base_url,
                                   list_year=item.get("year", ""),
                                   skip_score_filter=skip_score_filter,
                                   cat_name=cat_name, sort_type=sort_type)
        if detail is None:
            return "skipped"

        if detail.get("playlist"):
            max_episodes = max(len(p.get("episodes", {})) for p in detail["playlist"])
            video_name = item["name"]
            if video_name not in EPISODE_WHITELIST:
                if cat_name == "Drama" and max_episodes > DRAMA_MAX_EPISODES_LIMIT:
                    log(f"  ({idx_i}/{total}) [跳过-剧集数超限] {video_name} (最大集数: {max_episodes} > {DRAMA_MAX_EPISODES_LIMIT})", force=True)
                    return "skipped"
                elif cat_name == "Anime" and max_episodes > ANIME_MAX_EPISODES_LIMIT:
                    log(f"  ({idx_i}/{total}) [跳过-剧集数超限] {video_name} (最大集数: {max_episodes} > {ANIME_MAX_EPISODES_LIMIT})", force=True)
                    return "skipped"

        img_url = detail.pop("_img_url", "")
        if is_update and old_data and old_data.get("image"):
            detail["image"] = old_data.get("image")
        else:
            if img_url:
                video_id = extract_video_id(item["url"], item["name"])
                detail["image"] = download_cover(img_url, video_id, log_prefix=f"  ({idx_i}/{total})")
                time.sleep(SLEEP_BETWEEN_REQUESTS)

        old_entry = None
        old_category = None
        target_list_idx = None

        if is_update:
            detail["name"] = key[0]
            old_category = old_data.get("category")
            target_list_idx = old_data.get("list_idx")
            if old_category and old_category in all_data:
                existing_list = all_data[old_category]
                if target_list_idx is not None and target_list_idx < len(existing_list):
                    old_entry = existing_list[target_list_idx]

        change_reasons: list[str] = []

        if is_update and old_entry:
            old_pl = old_entry.get("playlist", [])
            new_pl = detail.get("playlist", [])
            merged_playlist, pl_changed, pl_details = merge_and_sort_playlist(
                old_pl, new_pl, cat_name, item["info"])
            detail["playlist"] = merged_playlist
            if pl_changed:
                change_reasons.extend(pl_details)

            old_info_val = old_entry.get("info", "")
            new_info_val = detail.get("info", "")
            old_is_qx = any(kw.upper() in old_info_val.upper() for kw in QIANGXIAN_KEYWORDS)

            if cat_name == "Movie":
                new_info_is_qx = any(kw.upper() in new_info_val.upper() for kw in QIANGXIAN_KEYWORDS)
                new_ep_has_qx = False
                for p in new_pl:
                    for ep_name in p.get("episodes", {}).keys():
                        if any(kw.upper() in ep_name.upper() for kw in QIANGXIAN_KEYWORDS):
                            new_ep_has_qx = True
                            break
                    if new_ep_has_qx:
                        break

                if old_is_qx and (not new_info_is_qx) and (not new_ep_has_qx) and new_info_val:
                    detail["info"] = new_info_val
                    change_reasons.append(f"Info更新 (抢先转正片): '{old_info_val}' -> '{new_info_val}'")
                else:
                    detail["info"] = old_info_val
            else:
                def _get_max_ep_num(pl_list):
                    max_num = 0
                    for p in pl_list:
                        eps = p.get("episodes", {})
                        for ep_name in eps.keys():
                            max_num = max(max_num, extract_episode_num(ep_name))
                        max_num = max(max_num, len(eps))
                    return max_num

                old_max_ep = _get_max_ep_num(old_pl)
                new_max_ep = _get_max_ep_num(new_pl)

                if new_max_ep > old_max_ep:
                    formatted_info = f"更新至第{new_max_ep}集"
                    if formatted_info != old_info_val:
                        detail["info"] = formatted_info
                        change_reasons.append(f"Info更新 (集数增加): '{old_info_val}' -> '{formatted_info}'")
                    else:
                        detail["info"] = old_info_val
                else:
                    detail["info"] = old_info_val

            detail["update"] = old_entry.get("update", detail.get("update", ""))

            for field in ["导演", "编剧", "主演", "类型", "地区"]:
                old_val = old_entry.get(field)
                new_val = detail.get(field)
                if not old_val and new_val:
                    detail[field] = new_val
                    change_reasons.append(f"补全字段 [{field}]: {new_val}")
                else:
                    detail[field] = old_val

            for field in ["date", "alias"]:
                old_val = str(old_entry.get(field, "") or "")
                new_val = str(detail.get(field, "") or "")
                if not old_val and new_val:
                    detail[field] = new_val
                    change_reasons.append(f"补全字段 [{field}]: {new_val}")
                elif new_val and len(new_val) > len(old_val):
                    detail[field] = new_val
                    change_reasons.append(f" [{field}] (长度: {len(old_val)} -> {len(new_val)})")
                else:
                    detail[field] = old_val

            old_intro = str(old_entry.get("intro", "") or "").strip()
            new_intro = str(detail.get("intro", "") or "").strip()

            if not old_intro and new_intro:
                detail["intro"] = new_intro
                change_reasons.append(f"补全字段 [intro]: (长度: {len(new_intro)})")
            elif old_intro and new_intro and old_intro != new_intro:
                old_has_zh = has_chinese(old_intro)
                new_has_zh = has_chinese(new_intro)

                if not old_has_zh and new_has_zh:
                    detail["intro"] = new_intro
                    change_reasons.append(f" [intro] (以中文简介替换原英文简介)")
                elif old_has_zh and not new_has_zh:
                    detail["intro"] = old_intro
                elif len(new_intro) > len(old_intro):
                    detail["intro"] = new_intro
                    change_reasons.append(f" [intro] (长度: {len(old_intro)} -> {len(new_intro)})")
                else:
                    detail["intro"] = old_intro
            else:
                detail["intro"] = old_intro

            old_rating = old_entry.get("评分", {})
            if not isinstance(old_rating, dict):
                old_rating = {"豆瓣": "", "IMDB": ""}
            new_rating = detail.get("评分", {})
            final_rating = {}
            for platform in ["豆瓣", "IMDB"]:
                old_score = old_rating.get(platform, "")
                new_score = new_rating.get(platform, "")
                if (not old_score or old_score == "--") and (new_score and new_score != "--"):
                    final_rating[platform] = new_score
                    change_reasons.append(f"补全评分 [{platform}]: (空) -> {new_score}")
                else:
                    final_rating[platform] = old_score
            detail["评分"] = final_rating

        ordered_detail = {}
        ordered_detail["name"] = detail["name"]

        if is_update and old_entry:
            ordered_detail["url"] = old_entry.get("url", "")
        else:
            ordered_detail["url"] = detail["url"]

        if matched_by_name_only and old_entry:
            new_url = detail.get("url", "")
            added_key = append_new_url_fields(old_entry, ordered_detail, new_url)
            if added_key:
                change_reasons.append(f"同名合并追加 URL 为 {added_key}: {new_url}")
        elif old_entry:
            for k, v in old_entry.items():
                if k.startswith("url") and k != "url":
                    ordered_detail[k] = v

        if "info" in detail:
            ordered_detail["info"] = detail["info"]
        if "update" in detail:
            ordered_detail["update"] = detail["update"]

        for k, v in detail.items():
            if k not in ordered_detail:
                ordered_detail[k] = v

        detail = ordered_detail

        if is_update and not change_reasons:
            log(f"  ({idx_i}/{total}) [无变化] {item['name']} (详情页所有字段及播放源完全一致)", force=True)
            return "skipped"

        tag = "[更新]" if is_update else "[新增]"
        log(f"   ✅{tag} {item['name']}  {item['url']}  info={detail.get('info', '')}", force=True)

        if is_update:
            for reason in change_reasons:
                log(f"     ↳ [变更] {reason}", force=True)

        write_category = old_category if (is_update and old_category) else cat_name
        if write_category not in all_data:
            all_data[write_category] = []

        if is_update:
            if target_list_idx is not None and target_list_idx < len(all_data[write_category]):
                all_data[write_category][target_list_idx] = detail
            else:
                replaced = False
                for i, old in enumerate(all_data[write_category]):
                    old_path = get_url_path(old.get("url", ""))
                    if old.get("name") == key[0] or old_path == item_path:
                        all_data[write_category][i] = detail
                        replaced = True
                        break
                if not replaced:
                    all_data[write_category].append(detail)
            result = "updated"
        else:
            all_data[write_category].append(detail)
            result = "new"

        global_index.clear()
        global_index.update(build_index(all_data))

        if not save_data(all_data):
            print("     ⚠️ [注意] 本条变更未能写入磁盘（详见上方原因）")
        return result

    except Exception as e:
        import traceback
        print(f"     [解析失败] {e}")
        traceback.print_exc()
        return "skipped"


def crawl_category(cat_name: str, cat_cfg: dict,
                   all_data: dict, global_index: dict,
                   year: str, sort_type: str) -> tuple[int, int]:
    print(f"\n=== 开始抓取分类: {cat_name} "
          f"(sort={sort_type}, id={cat_cfg['id']}, pages={cat_cfg['pages']}, year={year or '无'}) ===")
    new_count = 0
    updated_count = 0

    for page in range(1, cat_cfg["pages"] + 1):
        list_url = build_list_url(cat_cfg["id"], page, year, sort_type)
        log(f"\n[列表页] {list_url}", force=True)
        html = fetch(list_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if not html:
            continue

        items = parse_list_page(html)
        log(f"  -> 共找到 {len(items)} 部", force=True)

        for idx_i, item in enumerate(items, 1):
            result = process_item(
                item, cat_name, all_data, global_index,
                detail_base_url=DETAIL_BASE_URL,
                skip_score_filter=cat_cfg.get("skip_score_filter", False),
                idx_i=idx_i, total=len(items),
                sort_type=sort_type
            )
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

    return new_count, updated_count


def crawl_homepage(categories_cfg: dict, all_data: dict, global_index: dict):
    print(f"\n=== 开始抓取首页推荐: {INDEX_BASE_URL} ===")
    html = fetch(INDEX_BASE_URL + "/")
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not html:
        print("  [错误] 首页抓取失败，跳过")
        return

    sections = parse_homepage(html)

    for cat_name, items in sections.items():
        cat_cfg = categories_cfg.get(cat_name)
        if not cat_cfg or not cat_cfg.get("enabled"):
            continue

        if cat_name not in all_data:
            all_data[cat_name] = []

        print(f"\n--- [首页] 分类: {cat_name} 共找到 {len(items)} 部 ---")
        new_n = 0
        upd_n = 0
        for idx_i, item in enumerate(items, 1):
            result = process_item(
                item, cat_name, all_data, global_index,
                detail_base_url=INDEX_BASE_URL,
                skip_score_filter=True,
                idx_i=idx_i, total=len(items),
                sort_type="index"
            )
            if result == "new":
                new_n += 1
            elif result == "updated":
                upd_n += 1

        print(f"  -> [首页] 分类 {cat_name} 新增 {new_n} 条，更新 {upd_n} 条")


def clean_existing_data(data: dict):
    empty_pl = 0
    for cat in list(data.keys()):
        if not isinstance(data[cat], list):
            continue
        new_list = []
        for item in data[cat]:
            if not isinstance(item, dict):
                continue
            item.pop("update_pk", None)
            if item.get("playlist"):
                new_list.append(item)
            else:
                empty_pl += 1
                if not REMOVE_EMPTY_PLAYLIST_ITEMS:
                    new_list.append(item)
        data[cat] = new_list
    if empty_pl:
        action = "已删除" if REMOVE_EMPTY_PLAYLIST_ITEMS else "已保留(未删除)"
        print(f">>> [清理] 发现 {empty_pl} 条无 playlist 的旧数据，{action}")


# =============================================================
# CLI 命令行处理
# =============================================================
def parse_cli():
    global USE_CDP, HEADLESS, FAST_MODE, AUTO_CLICK_TURNSTILE
    args = [a.lower().lstrip("-") for a in sys.argv[1:]]

    if "open" in args or "launch" in args:
        launch_chrome_for_cdp()
        sys.exit(0)

    if "cdp" in args:
        USE_CDP = True
        AUTO_CLICK_TURNSTILE = False
        print(">>> [模式] CDP：将附着到你手动启动的 Chrome（不会关闭它）")
    if "headless" in args:
        HEADLESS = True
        print(">>> [模式] 无头（注意：可能无法通过 Cloudflare）")
    if "fast" in args:
        FAST_MODE = True
        print(">>> [模式] FAST：启用 curl_cffi 加速通道")
    if "click" in args:
        AUTO_CLICK_TURNSTILE = True
        print(">>> [模式] 允许脚本自动点击 Turnstile")


# =============================================================
# 主流程入口
# =============================================================
def main():
    setup_logging()
    parse_cli()
    start_caffeinate()

    # ---------- 数据安全检查 ----------
    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    final = load_existing(OUTPUT_FILE)
    snapshot_backup(OUTPUT_FILE)
    before_total = count_items(final)
    clean_existing_data(final)
    global_index = build_index(final)
    print(f">>> 已有数据分类数: {len(final)}；总条目数: {count_items(final)} (基线 {_BASELINE_TOTAL})")

    if os.path.exists(OUTPUT_FILE + ".tmp"):
        print(f">>> [提示] 发现残留临时文件 {OUTPUT_FILE}.tmp，可自行检查后删除")

    try:
        _fetcher.start()  # 预先连接 CDP / 启动浏览器 / 预热并同步 fast session

        # ---------- 开始抓取 ----------
        for task_group in TASKS:
            sort_type = task_group.get("sort_type", "")
            if not task_group.get("enabled"):
                print(f"\n⏭  跳过 {sort_type} 模式(总开关已关闭)")
                continue

            print(f"\n##################################################")
            print(f"🎯 进入抓取模式: {sort_type.upper()}")
            print(f"##################################################")

            for job in task_group.get("jobs", []):
                year = job.get("year", "")
                categories_cfg = job.get("categories", {})

                print(f"\n==================================================")
                print(f"🚀 [{sort_type}] 开始执行任务: year={year or '无'}")
                print(f"==================================================")

                if sort_type == "index":
                    for cat_name in categories_cfg:
                        if cat_name not in final:
                            final[cat_name] = []
                    crawl_homepage(categories_cfg, final, global_index)
                    continue

                for cat_name, cat_cfg in categories_cfg.items():
                    if cat_name not in final:
                        final[cat_name] = []

                    if not cat_cfg.get("enabled"):
                        continue

                    new_n, upd_n = crawl_category(
                        cat_name, cat_cfg,
                        final, global_index,
                        year, sort_type
                    )
                    print(f"  -> [{sort_type}] year={year or '无'} 分类 {cat_name} 新增 {new_n} 条,更新 {upd_n} 条")

        # ---------- 收尾保存 ----------
        save_data(final, quiet=False)
        after_total = count_items(final)
        print(f"\n✅ 全部抓取任务结束。条目数: {before_total} -> {after_total}")

    finally:
        _fetcher.close()


if __name__ == "__main__":
    main()