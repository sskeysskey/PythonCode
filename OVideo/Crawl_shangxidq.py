# -*- coding: utf-8 -*-
"""
shangxidq.com 分类页（电影/电视剧/综艺/动漫）爬取脚本
—— Cloudflare Turnstile 版：推荐「手动过一次验证 + CDP 附着 + curl_cffi 高速通道」

【推荐用法（方案 2）】
    1) 彻底退出 Chrome：osascript -e 'quit app "Google Chrome"'
    2) python Crawl_shangxidq.py open        # 用脚本 profile 启动带调试端口的 Chrome
    3) 在弹出的窗口里手动勾选过 Cloudflare 验证（一次就过）
    4) 窗口别关，另开终端： python Crawl_shangxidq.py cdp fast

其它用法：
    python Crawl_shangxidq.py                 # 正常抓取（自动弹出真实 Chrome 窗口）
    python Crawl_shangxidq.py backfill        # 补全模式
    python Crawl_shangxidq.py cdp             # 附着到你手动启动的 Chrome
    python Crawl_shangxidq.py headless        # 无头模式（不推荐，容易被 CF 拦）
    python Crawl_shangxidq.py fast            # 开启 curl_cffi 加速通道（失败会自动降级）
参数可组合，例如：python Crawl_shangxidq.py cdp fast backfill
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
from urllib.parse import urljoin
from urllib.request import urlopen
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime

from curl_cffi import requests as cffi   # 仅在 FAST 模式下使用

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
    log_dir = os.path.join(os.path.dirname(JSON_PATH), "logs")
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
    """启动 caffeinate 以防止系统休眠 (仅限 macOS)"""
    global _caffeinate_proc
    if platform.system() == 'Darwin':
        try:
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-idmu"])
            print(">>> [系统] 已开启防休眠模式 (caffeinate)")
        except Exception as e:
            print(f">>> [系统] 无法启动 caffeinate: {e}")

def stop_caffeinate():
    """停止 caffeinate"""
    global _caffeinate_proc
    if _caffeinate_proc:
        try:
            _caffeinate_proc.terminate()
            print(">>> [系统] 已关闭防休眠模式")
        except Exception as e:
            print(f">>> [系统] 关闭 caffeinate 时出错: {e}")

atexit.register(stop_caffeinate)

# ============== 站点及业务配置 ==============
DOMAIN        = "https://shangxidq.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "shangxidq"
SITE_KEY      = "shangxidq"
REQUEST_TIMEOUT = 20
SLEEP_BETWEEN  = 1.0

# ============ 数据安全相关配置 ============
BACKUP_DIR = os.path.join(os.path.dirname(JSON_PATH), "backup")
BAK_FILE = JSON_PATH + ".bak"
REJECTED_FILE = JSON_PATH + ".rejected.json"
MAX_BACKUPS = 20                 # backup/ 目录里最多保留多少份启动快照
ALLOW_SHRINK_RATIO = 0.90        # 新数据条目数不得低于基线的 90%，否则拒绝写盘
SHRINK_GUARD_MIN_ITEMS = 20      # 基线条目少于这个数时不启用缩水保护
ALLOW_FRESH_START = False        # 只有确实想从零开始建库时才改 True

_BASELINE_TOTAL = 0              # 启动时加载到的条目总数（缩水保护基线）
_LOAD_OK = False                 # 是否成功加载了初始数据（未成功则禁止任何写盘）

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 5.0

# ============== 浏览器 / Cloudflare 相关配置 ==============
USER_DATA_DIR   = os.path.expanduser("~/.shangxidq_chrome_profile")
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9222
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False
FAST_MODE       = False
NAV_TIMEOUT_MS  = 60000

# —— curl_cffi 指纹自动降级 ——
FAST_IMPERSONATE_CANDIDATES = ["chrome131", "chrome124", "chrome120", "chrome116", "chrome"]
FAST_RESYNC_INTERVAL = 300      # 每 300 秒从浏览器重新同步一次 cookie
FAST_MAX_RESYNC_FAIL = 3        # 连续 N 次同步后仍 403，则本次运行不再用 FAST

# —— 人机验证等待策略 ——
CHALLENGE_WAIT        = 600    # 整体最长等待（秒）
CHALLENGE_GRACE       = 10     # 一旦检测到验证页，至少保留 10 秒给你点击
PASS_STABLE_HITS      = 3      # 连续 N 次都判定为"站点正常页"才算真的过了
POLL_INTERVAL         = 1.5    # 轮询间隔（秒）
SITE_READY_TIMEOUT    = 8      # 非挑战页时，最多等 8 秒等站点结构渲染出来
PAGE_SETTLE           = 1.0    # goto 之后静置秒数

AUTO_CLICK_TURNSTILE   = True
AUTO_CLICK_FIRST_DELAY = 8
AUTO_CLICK_EVERY       = 15

# 判定「这是 Cloudflare 挑战页」的特征串
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
# 针对 shangxidq 的 ewave 模板特征
SITE_MARKERS = ("ewave-", "stui-", "vodshow", "vodplay", "ewave-vodlist")

BLACKLIST_NAMES = [
    "天堂之剑", "定海神针：九尾三世劫", "机甲少女破时空战记",
    "无名传奇", "魔彩王国历险记", "阿松与阿暖", "欲望的陷阱", "轻松熊", "家1"
]
BLACKLIST_URLS = []
WHITELIST_NAMES = []

SITE_PRIORITY = {
    "huxitech":  0,
    "chnland":   1,
    "6vdy":      2,
    "shangxidq": 3,
}

LIST_PAGES = [
    # ("https://shangxidq.com/vodshow/4--time---------2026.html", "Anime", "动漫(4)"),
    # ("https://shangxidq.com/vodshow/3--time---------2026.html", "Show",  "综艺(3)"),
    # ("https://shangxidq.com/vodshow/2--time---------2026.html", "Drama", "电视剧(2)"),
    ("https://shangxidq.com/vodshow/1--time---------2026.html", "Movie", "电影(1)"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "日本"]

FILTER_REGIONS_OVERRIDE = {
    "https://shangxidq.com/vodshow/1--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "https://shangxidq.com/vodshow/2--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产",
         "泰国", "台湾", "中国台湾", "日本"],
    "https://shangxidq.com/vodshow/4--time---------2026.html":
        ["中国", "大陆", "内地", "国产", "中国大陆", "中国内地", "国产剧",
         "泰国", "台湾", "中国台湾", "日本"],
}

EMPTY_VALUES = {"未知", "内详", "暂无", "/"}
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}
MAX_EPISODES = 30


# ============== 网络异常类型 ==============
class FetchError(Exception):
    pass

class NoRetryFetchError(FetchError):
    """客户端错误（404 等），重试无意义"""
    pass


# ==========================================================
#              CDP：启动 / 探测 Chrome
# ==========================================================
def count_items(data: dict) -> int:
    if not isinstance(data, dict):
        return 0
    return sum(len(v) for v in data.values() if isinstance(v, list))

def _read_json_strict(path: str) -> dict:
    """严格读取：空文件 / 非 dict / 解析失败 都抛异常"""
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
    """每次启动把当前有效文件另存一份时间戳快照，并做轮转清理"""
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
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

def cdp_alive(port=CDP_PORT, timeout=1.0):
    """探测调试端口是否可用"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except Exception:
        return False
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
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
    """用脚本 profile 启动带调试端口的独立 Chrome 实例"""
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
            print(">>> 请在窗口里手动勾选过 Cloudflare 验证，然后另开终端执行：")
            print("        python Crawl_shangxidq.py cdp fast")
            return True

    print("!!! 等待调试端口超时。可能是已有 Chrome 实例占用了 profile。")
    print("    请先执行：osascript -e 'quit app \"Google Chrome\"'  再重试。")
    print("    或手动执行：\n" + cdp_launch_command())
    return False


# ==========================================================
#                     真实浏览器抓取层
# ==========================================================
_STATE_JS = """
() => {
  const q = s => !!document.querySelector(s);
  const hasSite = q('ul.ewave-vodlist') || q('[class*="ewave-content_detail"]') ||
                  q('[class*="ewave-content__detail"]') || q('[class*="ewave-pannel_bd"]') ||
                  q('[class*="ewave-pannel__bd"]') || q('[class*="ewave-header"]') ||
                  q('ul.stui-vodlist') || q('[class*="stui-"]') ||
                  q('a[href*="/vodplay/"]') || q('a[href*="/voddetail/"]') ||
                  q('a[href*="/vodshow/"]');
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
    """用真实 Chrome 抓取；遇到 Cloudflare 挑战时暂停等待人工处理"""

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
                print("    python Crawl_shangxidq.py open")
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

        print(">>> [浏览器] 预热首页，检查 Cloudflare 状态 ...")
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
                if SITE_KEY in (p.url or ""):
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
            print(">>> [Cloudflare] 已检测到 cf_clearance cookie ✅（本次应无需再验证）")
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
            print("  💡 如果反复转圈永远过不了，强烈建议改用【手动过验证 + CDP 附着】：")
            print("       1) osascript -e 'quit app \"Google Chrome\"'")
            print("       2) python Crawl_shangxidq.py open")
            print("       3) 在窗口里手动过验证（一次就过）")
            print("       4) python Crawl_shangxidq.py cdp fast")
        print("=" * 72 + "\n")
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        if platform.system() == "Darwin":
            try:
                subprocess.run(
                    ["osascript", "-e", 'tell application "Google Chrome" to activate'],
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
                            self._page.goto(url, wait_until="domcontentloaded",
                                            timeout=NAV_TIMEOUT_MS)
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

        resp = self._page.goto(url, wait_until="domcontentloaded",
                               timeout=NAV_TIMEOUT_MS)
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
        candidates = ([self._impersonate] if self._impersonate else []) \
                     + FAST_IMPERSONATE_CANDIDATES
        for imp in candidates:
            if not imp:
                continue
            try:
                s = cffi.Session(impersonate=imp)
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
                       "image/avif,image/webp,*/*;q=0.8"),
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
            r = s.get(url, cookies=cookies, timeout=REQUEST_TIMEOUT,
                      allow_redirects=True)
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


def fetch(url, is_binary=False):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if is_binary:
                return _fetcher.get_bytes(url)
            return _fetcher.get_html(url)
        except NoRetryFetchError:
            raise
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                if "验证" in str(e) or "Cloudflare" in str(e):
                    wait = max(wait, 15)
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    raise last_err if last_err else FetchError(f"请求失败: {url}")


# ============== 工具函数 ==============
def extract_episode_number(info_text):
    """从 info 中提取纯数字集数"""
    if not info_text:
        return None
    match = re.search(r'(\d+)', info_text)
    return int(match.group(1)) if match else None

def _re_class(base):
    return re.compile(r"^" + base.replace("_", "_+") + r"$")

def is_garbled(value):
    if not value:
        return False
    v = str(value)
    if "\ufffd" in v:
        return True
    stripped = re.sub(r"[\s/·,，、|\-]", "", v)
    if not stripped:
        return False
    if re.fullmatch(r"[?？]+", stripped):
        return True
    return False

def normalize_info_text(info_str):
    if not info_str:
        return ""
    num_match = re.search(r"(\d+)", info_str)
    if not num_match:
        return normalize_text(info_str)
    num = int(num_match.group(1))
    return f"更新至第{num}集"

def normalize_text(s):
    if not s:
        return ""
    entity_map = {
        "&middot": "·", "&mdash": "—", "&ndash": "–",
        "&ldquo": "\u201c", "&rdquo": "\u201d", "&lsquo": "\u2018", "&rsquo": "\u2019",
        "&iacute": "í", "&nbsp": " ", "&lrm": "", "&rlm": "",
    }
    for ent, ch in entity_map.items():
        s = s.replace(ent + ";", ch).replace(ent + "；", ch)
    s = s.replace("\u200e", "").replace("\u200f", "")
    s = s.replace("・", "·").replace("‧", "·").replace("·", "·")
    s = s.replace("\xa0", " ")
    s = re.sub(r"[，；;]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·•")
    return s

def num_to_chinese(num_str):
    try:
        num = int(num_str)
    except ValueError:
        return num_str

    chinese_digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    if num < 10:
        return chinese_digits[num]
    elif num == 10:
        return "十"
    elif num < 20:
        return f"十{chinese_digits[num % 10]}"
    elif num < 100:
        tens = num // 10
        ones = num % 10
        return f"{chinese_digits[tens]}十" + (chinese_digits[ones] if ones != 0 else "")
    return num_str

def split_name_info(raw_title):
    raw_title = raw_title.strip()
    base_name = raw_title
    base_info = ""

    bracket_match = re.search(r"^(.*?)[\[［](.*?)[\]］]$", raw_title)
    if bracket_match:
        base_name = bracket_match.group(1).strip()
        base_info = bracket_match.group(2).strip()
    else:
        season_match = re.search(r"^(.*?)\s+((?:第[0-9一二三四五六七八九十百\-]+季)(?:全)?)$", raw_title)
        if season_match:
            base_name = season_match.group(1).strip()
            base_info = season_match.group(2).strip()

    def replace_season(match):
        prefix = match.group(1)
        num = match.group(2)
        suffix = match.group(3)
        return f"{prefix}{num_to_chinese(num)}{suffix}"

    base_name = re.sub(r"(第)(\d+)(季)", replace_season, base_name)
    base_info = re.sub(r"(第)(\d+)(季)", replace_season, base_info)

    if not base_info:
        return base_name, ""

    if base_info == "全集":
        return base_name, "全集"
    elif base_info.endswith("季全"):
        if re.search(r"[\-\d~至]", base_info):
            return base_name, base_info
        else:
            season_clean = base_info[:-1]
            name = f"{base_name} {season_clean}"
            return name, base_info
    elif base_info.endswith("季"):
        name = f"{base_name} {base_info}"
        info = ""
        return name, info

    return base_name, base_info

def safe_filename(url):
    return os.path.basename(url.split("?")[0])

def download_and_localize_image(img_url):
    if not img_url:
        return ""
    fn = safe_filename(img_url)
    if not fn:
        return ""
    local_path = os.path.join(IMG_DIR, fn)
    if not os.path.exists(local_path):
        try:
            content = fetch(img_url, is_binary=True)
            os.makedirs(IMG_DIR, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            print(f"  [图片] 已下载 -> {fn}")
        except Exception as e:
            print(f"  [图片下载失败] {img_url}: {e}")
            return ""
    return fn

def extract_info_date(info):
    if not info:
        return None
    m = re.search(r"(20\d{6})", info)
    return m.group(1) if m else None

def get_max_episode_number(episodes):
    if not episodes:
        return 0

    # 1. 匹配 SxxExx 格式
    se_pairs = []
    for name in episodes.keys():
        m = re.search(r'S(\d+)E(\d+)', str(name), re.IGNORECASE)
        if m:
            se_pairs.append((int(m.group(1)), int(m.group(2))))
    if se_pairs:
        max_season = max(s for s, e in se_pairs)
        max_ep_in_latest_season = max(e for s, e in se_pairs if s == max_season)
        return max_ep_in_latest_season

    # 2. 匹配 第X季...第Y集 格式
    season_ep_pairs = []
    for name in episodes.keys():
        m = re.search(r'第\s*(\d+)\s*季.*?第\s*(\d+)\s*[集期话話]', str(name))
        if m:
            season_ep_pairs.append((int(m.group(1)), int(m.group(2))))
    if season_ep_pairs:
        max_season = max(s for s, e in season_ep_pairs)
        max_ep_in_latest_season = max(e for s, e in season_ep_pairs if s == max_season)
        return max_ep_in_latest_season

    # 3. 常规集数提取
    max_num = 0
    for name in episodes.keys():
        m = re.search(r'(\d+)\s*[集期话話]', str(name))
        if not m:
            m = re.search(r'第\s*(\d+)', str(name))
        if not m:
            m = re.search(r'(\d+)', str(name))
        if m:
            max_num = max(max_num, int(m.group(1)))
            
    return max_num

def _url_keys_sorted(existing):
    return sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

def _ensure_site_url(existing, sub_url, force_new=False):
    url_keys = _url_keys_sorted(existing)
    if not force_new:
        for k in url_keys:
            v = existing.get(k, "") or ""
            if SITE_KEY in v or v == sub_url:
                return k

    max_num = 0
    for k in url_keys:
        m = re.match(r"^url(\d+)$", k)
        if m:
            max_num = max(max_num, int(m.group(1)))
    new_url_key = f"url{max_num + 1}"

    last_url_key = url_keys[-1] if url_keys else None
    new_ordered = {}
    inserted = False
    for k, v in existing.items():
        new_ordered[k] = v
        if k == last_url_key:
            new_ordered[new_url_key] = sub_url
            inserted = True
    if not inserted:
        new_ordered[new_url_key] = sub_url

    existing.clear()
    existing.update(new_ordered)
    return new_url_key

def append_site_channel(existing, new_episodes, sub_url):
    new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
    existing.setdefault("playlist", []).append(
        {"name": PLAYLIST_NAME, "episodes": new_episodes}
    )
    return new_url_key

def promote_site_to_pos(existing, new_episodes, sub_url, insert_pos=0):
    playlist = existing.setdefault("playlist", [])
    site_index = next(
        (i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME),
        None
    )

    if site_index is not None:
        pl = playlist.pop(site_index)
        pl["episodes"] = new_episodes
        target = insert_pos - 1 if site_index < insert_pos else insert_pos
        target = max(0, min(target, len(playlist)))
        playlist.insert(target, pl)
        _ensure_site_url(existing, sub_url)
        return None, ("in_place" if target == site_index else "moved")

    new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
    playlist = existing.setdefault("playlist", [])
    pos = max(0, min(insert_pos, len(playlist)))
    playlist.insert(pos, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return new_url_key, "inserted"

def extract_episode_count_from_info(info):
    if not info:
        return None
    m = re.search(r"更新[至到]\D*?(\d+)", info)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*[集期话話]\s*$", info)
    if m:
        return int(m.group(1))
    return None

def is_valid_episode_name(name):
    if not name:
        return False
    if name in INVALID_EPISODE_NAMES:
        return False
    if re.match(r"^更新[至到]", name):
        return False
    return True

def filter_episodes(eps):
    return {k: v for k, v in eps.items() if is_valid_episode_name(k)}

def detect_group_by_episodes(episodes):
    names = list(episodes.keys())
    count = len(names)
    has_ji = any("集" in n or re.search(r"S\d+E\d+", n, re.I) for n in names)
    if has_ji and count > 2:
        return "Drama"
    return "Movie"

def insert_playlist_by_priority(playlist, new_pl):
    new_prio = SITE_PRIORITY.get(new_pl.get("name"), 99)
    pos = len(playlist)
    for i, pl in enumerate(playlist):
        if new_prio < SITE_PRIORITY.get(pl.get("name"), 99):
            pos = i
            break
    playlist.insert(pos, new_pl)
    return pos

def merge_missing_fields(existing, rec, log=print):
    changed = False
    for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]:
        old_val = existing.get(field)
        new_val = rec.get(field)
        if isinstance(new_val, str) and is_garbled(new_val):
            continue
        if isinstance(new_val, list):
            new_val = [x for x in new_val if not is_garbled(x)]
        if (not old_val) and new_val:
            existing[field] = new_val
            changed = True
            log(f"      [字段更新] 补充缺失字段「{field}」: {new_val}")

    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if new_date and (not old_date or len(str(new_date)) > len(str(old_date))):
        existing["date"] = new_date
        changed = True
        log(f"      [字段更新] 更新「date」字段: 「{old_date}」 -> 「{new_date}」")

    existing.setdefault("评分", {"豆瓣": "", "IMDB": ""})
    return changed

# ============== 列表页与详情页解析 ==============
def get_list(list_url):
    html = fetch(list_url)
    soup = BeautifulSoup(html, "lxml")
    items = []
    for li in soup.select("ul.ewave-vodlist li"):
        detail = li.find(class_=_re_class("ewave-vodlist_detail"))
        h4a = None
        if detail:
            h4a = detail.select_one("h4.title a[href]")
        if not h4a:
            h4a = li.select_one("h4.title a[href]")
        if not h4a:
            continue
        href = h4a.get("href", "")
        title = (h4a.get("title") or h4a.get_text(strip=True)).strip()
        if not href or not title:
            continue

        thumb = li.find(class_=_re_class("ewave-vodlist_thumb"))
        info = ""
        img = ""
        if thumb:
            pic = thumb.select_one("span.pic-text")
            if pic:
                info = pic.get_text(strip=True)
            img = thumb.get("data-original", "") or thumb.get("data-src", "") or ""
            if not img:
                img_tag = thumb.select_one("img[data-original]")
                if img_tag:
                    img = img_tag.get("data-original", "")
                if not img:
                    img_tag = thumb.select_one("img")
                    if img_tag:
                        img = img_tag.get("data-original", "") or img_tag.get("src", "") or ""

        info = normalize_text(info)
        img = urljoin(DOMAIN, img) if img else ""

        name, _ = split_name_info(title)
        if not name:
            name = title
        items.append((name, info, urljoin(DOMAIN, href), img))
    return items

def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES or is_garbled(v):
        return ""
    return v

def parse_detail_fields(detail_div):
    result = {"类型": [], "地区": "", "date": "", "主演": [], "导演": []}
    if detail_div is None:
        return result

    def assign(field, value):
        value = _clean_val(value)
        if not value:
            return
        if field in ("类型", "主演", "导演"):
            if value not in result[field]:
                result[field].append(value)
        elif field == "地区":
            if not result["地区"]:
                result["地区"] = value
        elif field == "date":
            if not result["date"]:
                result["date"] = value

    def detect_field(text):
        if not text:
            return None
        if re.search(r"类\s*型", text):
            return "类型"
        if re.search(r"地\s*区", text):
            return "地区"
        if re.search(r"年\s*份", text):
            return "date"
        if re.search(r"主\s*演|演\s*员", text):
            return "主演"
        if re.search(r"导\s*演", text):
            return "导演"
        return None

    p_tags = detail_div.select("p.data")
    if not p_tags:
        p_tags = detail_div.select("p")

    for p in p_tags:
        current = None
        for node in p.children:
            if isinstance(node, Tag):
                if node.name == "span":
                    classes = node.get("class", []) or []
                    if "split-line" in classes:
                        current = None
                        continue
                    text = node.get_text(strip=True)
                    matched = detect_field(text)
                    if matched:
                        current = matched
                    elif "text-muted" in classes:
                        current = None
                elif node.name == "a":
                    if current:
                        assign(current, node.get_text(strip=True))
            elif isinstance(node, NavigableString):
                if current:
                    val = _clean_val(str(node))
                    if val:
                        assign(current, val)
    return result

def parse_intro(soup):
    desc = soup.find(id="desc")
    if not desc:
        return ""
    bd = desc.find(class_=_re_class("ewave-pannel_bd"))
    p = bd.find("p") if bd else None
    if not p:
        p = desc.select_one("p.col-pd")
    if not p:
        return ""
    text = normalize_text(p.get_text(" ", strip=True))
    if not text or is_garbled(text):
        return ""
    m = re.search(r"剧情简介[：:]\s*(.+)", text)
    if m:
        result = normalize_text(m.group(1))
        return "" if is_garbled(result) else result
    return text

def extract_episodes(soup):
    best = {}
    for ul in soup.find_all("ul", class_=_re_class("ewave-content_playlist")):
        eps = {}
        for a in ul.select("li a[href]"):
            name = normalize_text(a.get_text(strip=True))
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
        if len(eps) > len(best):
            best = eps

    if best:
        return filter_episodes(best)

    exclude_pat = re.compile(r"ewave-content_+thumb|play-btn|ewave-vodlist_+thumb")
    pannel_bd = soup.find_all(class_=_re_class("ewave-pannel_bd"))
    eps = {}
    for bd in pannel_bd:
        for a in bd.select('a[href*="/vodplay/"]'):
            if a.find_parent(class_=exclude_pat):
                continue
            name = normalize_text(a.get_text(strip=True))
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
    if eps:
        return filter_episodes(eps)

    eps = {}
    for a in soup.select('a[href*="/vodplay/"]'):
        if a.find_parent(class_=exclude_pat):
            continue
        name = normalize_text(a.get_text(strip=True))
        href = a.get("href", "")
        if name and href:
            eps[name] = urljoin(DOMAIN, href)
    return filter_episodes(eps)

def parse_real_name(soup, default_name):
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    if not detail:
        return default_name
    h1 = detail.find("h1", class_="title")
    if not h1:
        return default_name
    for sp in h1.find_all("span"):
        classes = sp.get("class", []) or []
        if any(("score" in c) or ("raty" in c) for c in classes):
            sp.extract()
    t = normalize_text(h1.get_text(strip=True))
    t = re.sub(r"\s*\d+(\.\d+)?\s*$", "", t).strip() or t
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t

def extract_image_from_detail(soup):
    thumb = soup.find(class_=_re_class("ewave-vodlist_thumb"))
    if not thumb:
        return ""
    img_tag = thumb.select_one("img[data-original]")
    if img_tag:
        return img_tag.get("data-original", "")
    img_tag = thumb.select_one("img")
    if img_tag:
        return img_tag.get("data-original", "") or img_tag.get("src", "") or ""
    return thumb.get("data-original", "") or ""

def extract_info_from_detail(soup):
    thumb = soup.find(class_=_re_class("ewave-vodlist_thumb"))
    if thumb:
        pic = thumb.select_one("span.pic-text")
        if pic:
            return normalize_text(pic.get_text(strip=True))
    return ""

def parse_subpage(sub_url, default_name, default_info, list_img=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    info = default_info
    if not info:
        info = extract_info_from_detail(soup)

    img_url = list_img
    if not img_url:
        img_url = extract_image_from_detail(soup)
    if img_url:
        img_url = urljoin(DOMAIN, img_url)

    playlist = []
    if episodes:
        playlist.append({"name": PLAYLIST_NAME, "episodes": episodes})

    director_str = " / ".join(fields["导演"]) if fields["导演"] else ""

    return {
        "name":   real_name,
        "url":    sub_url,
        "info":   info,
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   director_str,
        "编剧":   [],
        "主演":   fields["主演"],
        "类型":   fields["类型"],
        "地区":   fields["地区"],
        "date":   fields["date"],
        "alias":  "",
        "intro":  intro or "",
        "评分":   {"豆瓣": "", "IMDB": ""},
        "playlist": playlist,
    }

# ============== JSON 读写与核心逻辑 ==============
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

    # 尝试从备份恢复
    if main_exists:
        for cand in _backup_candidates():
            if not os.path.exists(cand) or os.path.getsize(cand) == 0:
                continue
            try:
                data = _read_json_strict(cand)
            except Exception:
                continue
            n = count_items(data)
            _BASELINE_TOTAL = n
            _LOAD_OK = True
            print(f"✅ [恢复] 已从备份恢复数据: {cand} ({n} 条)")
            save_json(data, force=True, quiet=False)
            return data

        if not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print("脚本已终止：为防止用空数据覆盖你的历史库，本次不会写入任何内容。")
            print("请从备份恢复可用的 JSON 后再重试。")
            print("!" * 70 + "\n")
            sys.exit(1)
        _BASELINE_TOTAL = 0
        _LOAD_OK = True
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

    _BASELINE_TOTAL = 0
    _LOAD_OK = True
    return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

def save_json(data: dict, force: bool = False, quiet: bool = True) -> bool:
    global _BASELINE_TOTAL
    if not _LOAD_OK:
        print("  [拒绝保存] 初始数据未成功加载，禁止写盘")
        return False
    if not isinstance(data, dict):
        return False

    total = count_items(data)
    if (not force) and _BASELINE_TOTAL >= SHRINK_GUARD_MIN_ITEMS and total < _BASELINE_TOTAL * ALLOW_SHRINK_RATIO:
        print(f"\n  ⛔ [拒绝保存] 条目数异常缩水：{_BASELINE_TOTAL} -> {total} (低于 {ALLOW_SHRINK_RATIO:.0%} 阈值)")
        try:
            with open(REJECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"  [提示] 可疑数据已另存到 {REJECTED_FILE}，主文件未被修改\n")
        except Exception:
            pass
        return False

    try:
        payload = json.dumps(data, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"  [错误] JSON 序列化失败: {e}")
        return False

    if len(payload.strip()) < 10:
        return False

    tmp_file = JSON_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
        if os.path.exists(JSON_PATH) and os.path.getsize(JSON_PATH) > 0:
            try:
                shutil.copy2(JSON_PATH, BAK_FILE)
            except Exception:
                pass

        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

        _read_json_strict(tmp_file)
        os.replace(tmp_file, JSON_PATH)
        _BASELINE_TOTAL = max(_BASELINE_TOTAL, total)
        if not quiet:
            print(f"  [已保存] 共 {total} 条")
        return True
    except Exception as e:
        print(f"  [错误] 实时保存失败: {e}")
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        return False

def normalize_url(u):
    """去除协议头、www、尾部斜杠，确保 URL 格式统一"""
    if not u:
        return ""
    u = str(u).strip()
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    u = re.sub(r"^www\.", "", u, flags=re.IGNORECASE)
    return u.rstrip("/")

def clean_season_one(s):
    """将'第一季'、'第1季'后缀剥离，用于基础名称比对"""
    if not s:
        return ""
    return re.sub(r"(?:第[一1]季)$", "", s).strip()

def find_existing_global(data, name, sub_url, log=print):
    def normalize_name(s):
        return s.replace(" ", "").strip() if s else ""

    norm_name = normalize_name(name)
    base_name = clean_season_one(norm_name)
    norm_sub_url = normalize_url(sub_url)

    # 1. 优先通过 URL 匹配
    if norm_sub_url:
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                for k in item.keys():
                    if k == "url" or re.match(r"^url\d+$", k):
                        val = item.get(k, "")
                        if val and normalize_url(val) == norm_sub_url:
                            existing_name = item.get("name", "")
                            if existing_name != name:
                                log(f"      [URL匹配去重] 发现 URL 一致 (URL: {sub_url}, 已有:「{existing_name}」, 抓取:「{name}」)")
                            return group, item

    # 2. 其次通过名称匹配
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            existing_raw_name = item.get("name", "")
            existing_norm_name = normalize_name(existing_raw_name)
            
            if existing_norm_name == norm_name:
                log(f"      [名称去重（忽略空格）] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
                return group, item
            
            existing_base_name = clean_season_one(existing_norm_name)
            if base_name and existing_base_name and base_name == existing_base_name:
                log(f"      [季数兼容去重] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
                return group, item

    return None, None

def process_existing_record(existing, new_episodes, sub_url, rec, matched_group,
                           old_max_episodes, log=print):
    """处理已存在的记录：合并字段、更新播放源和 info"""
    fields_updated = merge_missing_fields(existing, rec, log)

    def update_time_if_needed():
        if matched_group in ("Drama", "Anime"):
            new_max = get_max_episode_number(new_episodes)
            if new_max > old_max_episodes:
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not new_episodes:
        return "updated" if fields_updated else "no_new"

    url_keys = _url_keys_sorted(existing)
    has_site_url = False
    for k in url_keys:
        val = existing.get(k, "") or ""
        if SITE_KEY in val or val == sub_url:
            has_site_url = True
            break

    playlist = existing.setdefault("playlist", [])
    site_max = get_max_episode_number(new_episodes)
    
    other_max = 0
    for pl in playlist:
        if pl.get("name") == PLAYLIST_NAME:
            continue
        other_max = max(other_max, get_max_episode_number(pl.get("episodes", {})))

    info_updated = False
    if matched_group in ("Drama", "Anime", "Show") and site_max > other_max and site_max > 0:
        candidate_info = f"更新至第{site_max}集"
        if existing.get("info") != candidate_info:
            old_info = existing.get("info", "")
            existing["info"] = candidate_info
            info_updated = True
            log(f"      ✅[info更新] 抓取最大集数 {site_max} > 其他渠道最大集数 {other_max}，info: 「{old_info}」 -> 「{candidate_info}」")

    if has_site_url:
        old_eps = {}
        old_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_eps = pl.get("episodes", {})
                old_idx = idx
                break

        if new_episodes == old_eps:
            if info_updated:
                update_time_if_needed()
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_episodes) < len(old_eps):
            return "updated" if (fields_updated or info_updated) else "decreased"

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        if old_idx != -1:
            playlist[old_idx] = new_pl
            if site_max > other_max and old_idx != 0:
                playlist.insert(0, playlist.pop(old_idx))
                log(f"      [排序调整] {SITE_KEY} 最大集数({site_max}) > 其他渠道最大集数({other_max})，已移动至第一位")
        else:
            if site_max > other_max:
                playlist.insert(0, new_pl)
                log(f"      [排序调整] {SITE_KEY} 最大集数({site_max}) > 其他渠道最大集数({other_max})，已直接插入至第一位")
            else:
                insert_playlist_by_priority(playlist, new_pl)

        update_time_if_needed()
        return "updated"

    else:
        new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        pos = insert_playlist_by_priority(playlist, new_pl)
        log(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}，并按优先级把播放源插入至第 {pos + 1} 位")
        update_time_if_needed()
        return "channel_added"

# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    filter_regions = FILTER_REGIONS_OVERRIDE.get(list_url, FILTER_REGIONS)
    try:
        items = get_list(list_url)
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        return 0, 0
    print(f"  共发现 {len(items)} 条")
    ok, fail = 0, 0

    for idx, (name, info, url, img) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在名称黑名单中，跳过]")
            continue

        if any(black_url in url for black_url in BLACKLIST_URLS if black_url):
            print(f"  ({idx}/{len(items)}) {name} [URL 在黑名单中，跳过: {url}]")
            continue

        header = f"  ({idx}/{len(items)}) {name}  [{info}]"
        buf = []

        def flush():
            print(header)
            for line in buf:
                print(line)

        try:
            rec = parse_subpage(url, name, info, list_img=img)
            real_name = rec["name"]

            new_eps = {}
            for pl in rec.get("playlist", []):
                if pl.get("name") == PLAYLIST_NAME:
                    new_eps = pl.get("episodes", {})
                    break

            if not new_eps:
                flush()
                print("    ! 无播放源，跳过")
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            current_group = group
            if group == "AUTO":
                current_group = detect_group_by_episodes(new_eps)
                buf.append(f"    [自动分类] 选集共 {len(new_eps)} 项，判定为「{current_group}」")

            if current_group in ("Drama", "Anime") and len(new_eps) > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」属于「{current_group}」，集数 {len(new_eps)} 超过 {MAX_EPISODES} 集(期) 上限 ")
                ok += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            matched_group, existing = find_existing_global(data, real_name, url, buf.append)
            if existing and matched_group != current_group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，将按「{matched_group}」规则处理")

            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            elif current_group in ("Anime", "Drama", "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = rec.get("地区", "").strip()
                if any(keyword == region for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    ok += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

                if region in ("", "未知"):
                    cn_type_keywords = ["国产", "中国", "大陆", "内地"]
                    type_text = " ".join(rec.get("类型", []) or [])
                    matched_kw = next((kw for kw in cn_type_keywords if kw in type_text), None)
                    if matched_kw:
                        flush()
                        print(f"    - 跳过：地区未知，但类型「{type_text}」含「{matched_kw}」，判定为国产内容")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

            if existing:
                old_max_episodes = 0
                for pl in existing.get("playlist", []):
                    old_max_episodes = max(old_max_episodes, get_max_episode_number(pl.get("episodes", {})))

                has_site_channel = any(pl.get("name") == PLAYLIST_NAME for pl in existing.get("playlist", []))
                new_max = get_max_episode_number(new_eps)

                promote = False
                insert_at = None
                if matched_group in ("Drama", "Anime"):
                    playlist_all = existing.get("playlist", [])
                    global_max = 0
                    idx_global_max = -1
                    for i, pl in enumerate(playlist_all):
                        if pl.get("name") == PLAYLIST_NAME:
                            continue
                        pl_max = get_max_episode_number(pl.get("episodes", {}))
                        if pl_max > global_max:
                            global_max = pl_max
                            idx_global_max = i
                    buf.append(f"    [{matched_group}] 其他渠道最大集数={global_max}, {SITE_KEY}新抓取max={new_max}")
                    if new_max > global_max:
                        promote = True
                        insert_at = 0
                        buf.append(f"    [{matched_group}] {SITE_KEY}({new_max}) > 其他最大({global_max})，目标位置 playlist[0]")
                    elif new_max == global_max and global_max > 0:
                        promote = True
                        insert_at = idx_global_max + 1 if idx_global_max >= 0 else 0
                        buf.append(f"    [{matched_group}] {SITE_KEY}({new_max}) == 其他最大({global_max})，目标下标 {insert_at}")
                    elif new_max > 0:
                        promote = True
                        insert_at = idx_global_max + 1 if idx_global_max >= 0 else 0
                        buf.append(f"    [{matched_group}] {SITE_KEY}({new_max}) < 其他最大({global_max})，目标下标 {insert_at}")

                if promote:
                    playlist = existing.setdefault("playlist", [])
                    site_index = next((i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME), None)
                    old_site_eps = (playlist[site_index].get("episodes", {}) if site_index is not None else {})

                    if site_index is not None and len(new_eps) < len(old_site_eps):
                        flush()
                        print(f"    - 忽略({matched_group})：本次抓取 {len(new_eps)} 集 少于已有 {len(old_site_eps)} 集，保留原有 playlist")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

                    eps_changed = (new_eps != old_site_eps)

                    if eps_changed:
                        url_key, action = promote_site_to_pos(existing, new_eps, url, insert_pos=insert_at)
                    else:
                        url_key = _ensure_site_url(existing, url, force_new=(site_index is None))
                        action = "in_place"

                    info_changed = False
                    if new_max > global_max and new_max > 0:
                        candidate_info = f"更新至第{new_max}集"
                        if existing.get("info") != candidate_info:
                            old_info = existing.get("info", "")
                            existing["info"] = candidate_info
                            info_changed = True
                            buf.append(f"    [info更新] {SITE_KEY}集数({new_max}) > 其他最大({global_max})，「{old_info}」 -> 「{candidate_info}」")

                    fields_changed = merge_missing_fields(existing, rec, buf.append)
                    actual_changed = (eps_changed or info_changed or fields_changed or action in ("moved", "inserted"))

                    if actual_changed:
                        if matched_group in ("Drama", "Anime"):
                            if new_max > old_max_episodes or info_changed:
                                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(data)
                    flush()

                    if not actual_changed:
                        print(f"    - 无变更({matched_group})：集数、info、字段均无变化，保持原有顺序")
                        ok += 1
                    elif action == "inserted":
                        print(f"    ✅ 更新({matched_group})：{SITE_KEY} 作为新渠道写入 {url_key}，已插入 playlist 下标 {insert_at}")
                        ok += 1
                    elif action == "moved":
                        print(f"    ✅ 更新({matched_group})：{SITE_KEY} 已更新集数({len(old_site_eps)} -> {len(new_eps)})，并移动到目标位置")
                        ok += 1
                    elif eps_changed:
                        print(f"    ✅ 更新({matched_group})：{SITE_KEY} 已更新集数({len(old_site_eps)} -> {len(new_eps)})，位置保持不变")
                        ok += 1
                    else:
                        print(f"    ✅ 更新({matched_group})：仅 info/字段更新，保持原有顺序")
                        ok += 1

                elif has_site_channel:
                    status = process_existing_record(existing, new_eps, url, rec,
                                                     matched_group, old_max_episodes,
                                                     buf.append)
                    if status == "updated":
                        buf.append(f"    ✅ 更新({matched_group})：{SITE_KEY} 渠道发现新内容，已覆盖更新")
                        save_json(data)
                        flush()
                        ok += 1
                    elif status == "channel_added":
                        buf.append(f"    ✅ 更新({matched_group})：成功作为新渠道插入到 playlist")
                        save_json(data)
                        flush()
                        ok += 1
                    elif status == "no_change":
                        ok += 1
                    elif status == "decreased":
                        flush()
                        print(f"    - 忽略({matched_group})：抓取集数少于已有集数")
                        ok += 1
                    else:
                        flush()
                        print(f"    ! 忽略({matched_group})：未成功更新")
                        fail += 1

                else:
                    can_add = False
                    playlist_len = len(existing.get("playlist", []))
                    episode_total = len(new_eps)

                    if matched_group == "Movie":
                        can_add = True
                        buf.append(f"    [Movie] 允许把 {SITE_KEY} 作为新渠道插入，现有渠道数 {playlist_len}")
                    elif matched_group == "Drama":
                        other_channels_max_eps = 0
                        for pl in existing.get("playlist", []):
                            if pl.get("name") == PLAYLIST_NAME:
                                continue
                            pl_eps = pl.get("episodes", {})
                            pl_max = get_max_episode_number(pl_eps)
                            if pl_max > other_channels_max_eps:
                                other_channels_max_eps = pl_max

                        cond_a = (playlist_len == 1 and episode_total < 20)
                        cond_b = (episode_total > other_channels_max_eps)

                        if cond_a:
                            can_add = True
                            buf.append(f"    [Drama] 现有单一渠道，总集数{episode_total}<20，允许追加{SITE_KEY}渠道至末尾")
                        elif cond_b:
                            can_add = True
                            buf.append(f"    [Drama] 本次抓取集数{episode_total} > 其它渠道最大集数{other_channels_max_eps}，允许追加{SITE_KEY}新渠道")

                    if can_add:
                        new_url_key = append_site_channel(existing, new_eps, url)
                        merge_missing_fields(existing, rec, buf.append)
                        
                        if matched_group in ("Drama", "Anime", "Show") and new_max > other_channels_max_eps and new_max > 0:
                            existing["info"] = f"更新至第{new_max}集"

                        if matched_group in ("Drama", "Anime"):
                            if new_max > old_max_episodes:
                                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(data)
                        flush()
                        print(f"    ✅ 更新({matched_group})：已把 {SITE_KEY} 作为新渠道写入 {new_url_key}，并追加到 playlist 末尾")
                        ok += 1
                    else:
                        flush()
                        print(f"    - 跳过({matched_group})：项目已存在但无 {SITE_KEY} 渠道，且不满足补充渠道条件，保持原样")
                        ok += 1
            else:
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                
                ep_cnt = get_max_episode_number(new_eps)
                if current_group in ("Drama", "Anime") and ep_cnt > 0:
                    rec["info"] = f"更新至第{ep_cnt}集"

                data.setdefault(current_group, []).append(rec)
                print(f"    ✅ 新增 -> {current_group} (共 {len(new_eps)} 集) [真实名称: {real_name}] [URL: {rec['url']}]")
                save_json(data)
                ok += 1

        except Exception as e:
            flush()
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    return ok, fail

# ============== 补全模式 ==============
def fetch_detail_data(url):
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    if detail is None:
        return None, None
    fields = parse_detail_fields(detail)
    fields["intro"] = parse_intro(soup)
    img_url = extract_image_from_detail(soup)
    if img_url:
        img_url = urljoin(DOMAIN, img_url)
    return fields, img_url

def fill_empty_fields(item, fields, img_url=""):
    changed = False
    if not item.get("导演") and fields.get("导演"):
        item["导演"] = " / ".join(fields["导演"]) if isinstance(fields["导演"], list) else fields["导演"]
        changed = True
    for f in ["主演", "类型", "地区", "date", "intro"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    if img_url and not item.get("image"):
        local = download_and_localize_image(img_url)
        if local:
            item["image"] = local; changed = True
    return changed

def backfill_existing(data):
    print(f"\n[补全模式] 扫描已有 {SITE_KEY} 记录中字段缺失的资源 ...")
    total, updated = 0, 0
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            url_keys = [k for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)]
            target_url = next((item.get(k, "") for k in url_keys if item.get(k, "") and SITE_KEY in item.get(k, "")), None)
            if not target_url:
                continue
            need = (not item.get("导演") and not item.get("主演")
                    and not item.get("类型") and not item.get("地区")
                    and not item.get("intro"))
            if not need:
                continue
            total += 1
            print(f"  [{group}] 补全: {item.get('name')}  <- {target_url}")
            try:
                fields, img_url = fetch_detail_data(target_url)
                if fields is None:
                    print("    ✗ 跳过：无详情内容")
                    time.sleep(SLEEP_BETWEEN)
                    continue
                if fill_empty_fields(item, fields, img_url):
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    save_json(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} 地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            time.sleep(SLEEP_BETWEEN)
    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")

# ============== 命令行解析 ==============
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

    return "backfill" in args

# ============== 主流程 ==============
def main():
    setup_logging()
    is_backfill = parse_cli()
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)

    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    data = load_existing(JSON_PATH)
    snapshot_backup(JSON_PATH)
    if os.path.exists(JSON_PATH + ".tmp"):
        print(f">>> [提示] 发现残留临时文件 {JSON_PATH}.tmp，可自行检查后删除")

    try:
        _fetcher.start()

        if is_backfill:
            backfill_existing(data)
            print("\n====================================")
            print(f"补全任务完成! 数据已保存在 {JSON_PATH}")
            return

        total_ok, total_fail = 0, 0
        for list_url, group, page_name in LIST_PAGES:
            ok, fail = process_list_page(data, list_url, group, page_name)
            total_ok += ok
            total_fail += fail

        print("\n====================================")
        print(f"所有抓取任务完成! 成功 {total_ok} 条，失败 {total_fail} 条。数据已实时保存在 {JSON_PATH}")
    finally:
        _fetcher.close()

if __name__ == "__main__":
    main()