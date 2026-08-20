# -*- coding: utf-8 -*-
"""
azhfds.com 分类页（电影/电视剧/综艺/动漫）爬取脚本  —— 双引擎版 + 反封锁强化版

【引擎开关】
    ENGINE = "simple"   纯 HTTP（curl_cffi 真实 TLS 指纹），速度最快
    ENGINE = "browser"  真实 Chrome / CDP 附着 / Turnstile 人工过验证
    AUTO_FALLBACK_TO_BROWSER = True  轻量模式被挑战页拦住时自动热切换到浏览器引擎

【常用用法】
    python Crawl_azhfds.py                 # 默认轻量引擎抓取
    python Crawl_azhfds.py pages=3         # 每个分类抓 3 页
    python Crawl_azhfds.py backfill        # 补全模式
    python Crawl_azhfds.py browser         # 强制浏览器引擎
    python Crawl_azhfds.py simple nofallback   # 强制轻量且禁止降级
    python Crawl_azhfds.py cdp slow        # ★推荐：附着手动 Chrome + 慢速拟人节奏
    python Crawl_azhfds.py cdp fast slow   # 附着 + 快速通道（会自动体检，没 cookie 不启用）
    python Crawl_azhfds.py cdp proxy=http://127.0.0.1:7890   # 走代理换出口 IP

【站点上了 Cloudflare 时的最佳路径】
    1) osascript -e 'quit app "Google Chrome"'
    2) python Crawl_azhfds.py open         # 用脚本 profile 启动带调试端口(9223)的 Chrome
    3) 在窗口里手动打开站点，若有验证就过一次
    4) python Crawl_azhfds.py cdp slow

【关于 Cloudflare Error 1020（Sorry, you have been blocked）】
    这不是人机验证，页面上没有任何可点的复选框，等待也不会自动解除。
    它是站点 WAF 自定义规则按「IP 信誉 + 请求指纹 + 请求节奏 + 缺失 cookie」直接拒绝。
    解决办法只有三条：换出口 IP、降速拟人化、带上真实浏览器 cookie。
    本脚本检测到该页面会立刻停止等待、进入冷却退避，并给出处置建议。
"""

import os
import re
import sys
import gzip
import json
import time
import socket
import random
import platform
import subprocess
import atexit
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime

from bs4 import BeautifulSoup, NavigableString, Tag

# ---- 可选依赖：能装就用，装不上自动降级 ----
try:
    from curl_cffi import requests as cffi
except Exception:
    cffi = None

try:
    import requests as pyrequests
except Exception:
    pyrequests = None


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
    global _caffeinate_proc
    if _caffeinate_proc:
        try:
            _caffeinate_proc.terminate()
            print(">>> [系统] 已关闭防休眠模式")
        except Exception as e:
            print(f">>> [系统] 关闭 caffeinate 时出错: {e}")


atexit.register(stop_caffeinate)


# ============== 站点配置 ==============
DOMAIN        = "https://azhfds.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "azhfds"
SITE_KEY      = "azhfds"

REQUEST_TIMEOUT = 20
SLEEP_BETWEEN   = 2.0          # 每条详情之间的基准间隔（会被 slow / 封锁退避动态调大）
SIMPLE_JITTER   = (0.4, 1.2)   # 轻量模式的随机抖动，降低被风控概率

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 5.0

# 落盘节流：每 N 条变更写一次磁盘（1 = 实时写盘）
SAVE_EVERY    = 1

# 列表页最多翻几页（1 = 只抓第一页；可用 CLI pages=N 覆盖）
LIST_MAX_PAGES = 1

# 代理（也可用环境变量 AZHFDS_PROXY，或 CLI proxy=http://127.0.0.1:7890）
PROXY = os.environ.get("AZHFDS_PROXY", "").strip()


# ============== 引擎开关 ==============
ENGINE = "simple"                  # "simple" | "browser"
AUTO_FALLBACK_TO_BROWSER = True    # 轻量模式被挑战页拦时自动切浏览器

# —— 轻量引擎（simple）——
SIMPLE_IMPERSONATE_CANDIDATES = ["chrome131", "chrome124", "chrome120", "chrome116", "chrome"]
SIMPLE_MAX_CHALLENGE_HITS = 3      # 连续 N 次被拦 -> 触发自动降级
DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": DOMAIN + "/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

# —— 浏览器引擎（browser）——
USER_DATA_DIR   = os.path.expanduser("~/.azhfds_chrome_profile")
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9223            # 故意与 gdefud(9222) 区分，两站可同时开
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False
FAST_MODE       = False
FAST_FORCE      = False           # fastforce：即使没 cookie 也强开 FAST（不推荐）
NAV_TIMEOUT_MS  = 60000

FAST_IMPERSONATE_CANDIDATES = SIMPLE_IMPERSONATE_CANDIDATES
FAST_RESYNC_INTERVAL = 300
FAST_MAX_RESYNC_FAIL = 3

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
SITE_MARKERS = ("stui-", "vodshow", "vodplay", "voddetail", "stui-vodlist")

# ★ 硬封锁（Cloudflare WAF Block / Error 1020 等）标志：这类页面没有任何可点的验证控件
BLOCK_MARKERS = (
    "Sorry, you have been blocked",
    "You are unable to access",
    "You have been blocked",
    "Why have I been blocked",
    "Error 1020",
    "error code: 1020",
    "Error code 1020",
    "Access denied",
    "Attention Required! | Cloudflare",
    "cf-error-details",
    "抱歉，您已被阻止",
    "您无法访问",
)
# 只有同时出现 Ray ID / cloudflare 字样才算，避免误判正文里出现的普通词
BLOCK_CONFIRM_MARKERS = (
    "Cloudflare Ray ID",
    "Ray ID:",
    "cloudflare.com/5xx-error-landing",
    "cf-error-details",
    "Performance & security by Cloudflare",
)

# 硬封锁冷却退避（秒）：第 1/2/3 次…被封分别等这么久
BLOCK_COOLDOWN_STEPS = [120, 300, 600, 900]
MAX_BLOCK_EVENTS     = 4        # 超过这个次数就优雅终止本轮（数据已保存）
BLOCK_SLOWDOWN_FACTOR = 2.0     # 每次被封后把 SLEEP_BETWEEN 乘以这个系数
BLOCK_SLEEP_CEILING   = 20.0    # SLEEP_BETWEEN 上限


# ============== 业务过滤配置 ==============
BLACKLIST_NAMES = [
    "黄眼鬼",
]

# URL 黑名单（包含这些字串的 URL 将被跳过）
BLACKLIST_URLS = [
    # "https://azhfds.com/voddetail/xxxx.html",
]

# 白名单（跳过地区屏蔽）
WHITELIST_NAMES = [
    "北斗神拳 拳王军杂兵们的挽歌", "麻辣教师第二季", "新攻壳机动队",
]

LIST_PAGES = [
    ("https://azhfds.com/vodshow/dianying--time---------2026.html",  "Movie", "电影"),
    # ("https://azhfds.com/vodshow/dianshiju--time---------2026.html", "Drama", "电视剧"),
    # ("https://azhfds.com/vodshow/zongyi--time---------2026.html",    "Show",  "综艺"),
    # ("https://azhfds.com/vodshow/dongman--time---------2026.html",   "Anime", "动漫"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "日本"]
FILTER_REGIONS_OVERRIDE = {
    "https://azhfds.com/vodshow/dianying--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "https://azhfds.com/vodshow/dianshiju--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "台湾", "中国台湾", "日本"],
}

EMPTY_VALUES = {"未知", "内详", "暂无", "/", "未填写", "其他"}

INVALID_EPISODE_NAMES = {
    "立即播放", "收藏", "播放", "倒序", "正序", "排序",
    "下载", "分享", "报错", "举报", "评论", "播放列表",
}

# 选集面板标题关键词（越靠前优先级越高）
EPISODE_PANEL_KEYWORDS = ("高清云播", "云播资源", "云播", "在线播放", "播放地址", "线路", "播放列表")

MAX_EPISODES = 20   # Drama / Anime 超过这个集数则跳过


# ============== 异常类型 ==============
class FetchError(Exception):
    pass


class NoRetryFetchError(FetchError):
    """客户端错误（404 等），重试无意义"""
    pass


class ChallengeError(FetchError):
    """疑似被人机验证拦截（可以过的那种：Turnstile / Just a moment）"""
    pass


class BlockedError(FetchError):
    """★ 硬封锁：Cloudflare WAF Block / Error 1020，没有验证入口，等待无用"""
    pass


class HardBlockAbort(Exception):
    """连续硬封锁，放弃本轮抓取（数据已保存）"""
    pass


# ==========================================================
#                     通用小工具
# ==========================================================
def _re_class(base):
    """把 stui-xxx_yyy 这类类名变成对 - 和 _ 都宽容的正则"""
    parts = re.split(r"[-_]+", base)
    return re.compile(r"^" + r"[-_]+".join(re.escape(p) for p in parts) + r"$")


def _host(url):
    m = re.match(r"^https?://([^/:]+)", (url or "").strip(), re.I)
    return m.group(1).lower() if m else ""


_seen_hosts = set()


def note_host(url):
    """记录站点实际使用的域名（含随机镜像域名），供 cookie 同步使用"""
    h = _host(url)
    if not h or h in _seen_hosts:
        return
    _seen_hosts.add(h)
    base = _host(DOMAIN)
    if base and base not in h and h not in base:
        print(f">>> [注意] 站点跳转到镜像域名：{h}")
        print( "    （Cloudflare 防护实际挂在这个域名上，cookie 也存在这个域名下）")


def cookie_hosts():
    hosts = {_host(DOMAIN)} | set(_seen_hosts)
    return {h for h in hosts if h}


def _looks_like_challenge(html: str) -> bool:
    if not html or len(html) < 200:
        return True
    head = html[:8000]
    if not any(m in head for m in CHALLENGE_MARKERS):
        return False
    if any(m in html for m in SITE_MARKERS):
        return False
    return True


def _looks_like_block(html: str) -> bool:
    """★ 判定是否为 Cloudflare 硬封锁页（1020 / WAF Block / Access denied）"""
    if not html:
        return False
    head = html[:20000]
    if any(m in head for m in SITE_MARKERS):
        return False          # 正常站点页面，不是封锁页
    hit = any(m in head for m in BLOCK_MARKERS)
    if not hit:
        return False
    # 强特征直接判定
    if "Sorry, you have been blocked" in head or "1020" in head:
        return True
    return any(m in head for m in BLOCK_CONFIRM_MARKERS)


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def _proxies():
    if not PROXY:
        return None
    return {"http": PROXY, "https": PROXY}


def polite_sleep(base=None):
    """拟人化随机间隔（读取当前全局 SLEEP_BETWEEN，可被封锁退避动态调大）"""
    b = SLEEP_BETWEEN if base is None else base
    time.sleep(b + random.uniform(0, max(0.5, b * 0.6)))


# ==========================================================
#           ★ 硬封锁冷却退避（核心新增逻辑）
# ==========================================================
_block_events = 0


def _print_block_banner(url, err):
    print("\a", end="", flush=True)
    print("\n" + "#" * 76)
    print("  🚫 命中 Cloudflare 防火墙【硬封锁】（Error 1020 / WAF Block）")
    print(f"     URL : {url}")
    print(f"     信息: {err}")
    print("-" * 76)
    print("  这不是人机验证：页面写着 “Sorry, you have been blocked”，")
    print("  上面没有任何可勾选的复选框，等待也【不会】自动解除。")
    print("  它是站点自定义 WAF 规则按下列特征直接拒绝你的请求：")
    print("     · 出口 IP 信誉分低（机房 IP / 常见 VPN 节点 / 近期请求过密）")
    print("     · 请求指纹不像真人（无 cookie 的裸 HTTP 请求最容易命中）")
    print("     · 请求节奏机械（固定间隔、连续高频）")
    print("-" * 76)
    print("  ✅ 处置建议（按有效性排序）：")
    print("     ① 换出口 IP：手机热点 / 换 VPN 节点 / 重启光猫（家宽、蜂窝优于机房 IP）")
    print("     ② 降速：python Crawl_azhfds.py cdp slow")
    print("     ③ 关掉 FAST 通道，只用真实浏览器：去掉 fast 参数")
    print("     ④ 先在 Chrome 里手动打开站点确认能访问，再跑脚本")
    print("     ⑤ 走代理：python Crawl_azhfds.py cdp proxy=http://127.0.0.1:7890")
    print("#" * 76 + "\n")


def cooldown_for_block(url, err):
    """
    命中硬封锁后的处理：
      1) 打印诊断  2) 关闭 FAST 通道  3) 全局降速  4) 冷却等待  5) 首页探活
    超过 MAX_BLOCK_EVENTS 次则抛 HardBlockAbort 终止本轮。
    """
    global _block_events, FAST_MODE, SLEEP_BETWEEN

    _block_events += 1
    _print_block_banner(url, err)

    if FAST_MODE:
        FAST_MODE = False
        try:
            _fetcher.browser._fast_ok = False
            _fetcher.browser._fast_disabled = True
        except Exception:
            pass
        print(">>> [FAST] 已自动关闭快速通道（被封期间只走真实浏览器，降低指纹特征）")

    old_sleep = SLEEP_BETWEEN
    SLEEP_BETWEEN = min(SLEEP_BETWEEN * BLOCK_SLOWDOWN_FACTOR, BLOCK_SLEEP_CEILING)
    if SLEEP_BETWEEN != old_sleep:
        print(f">>> [降速] 请求间隔 {old_sleep:.1f}s -> {SLEEP_BETWEEN:.1f}s")

    if _block_events > MAX_BLOCK_EVENTS:
        raise HardBlockAbort(
            f"已连续 {_block_events} 次命中 Cloudflare 硬封锁，继续请求只会加重封禁。"
            "请更换出口 IP 后重跑（已抓取的数据均已保存）。"
        )

    idx = min(_block_events - 1, len(BLOCK_COOLDOWN_STEPS) - 1)
    wait = BLOCK_COOLDOWN_STEPS[idx]
    print(f">>> [冷却] 第 {_block_events} 次被封，静默等待 {wait}s（可 Ctrl-C 安全终止）")
    slept = 0
    while slept < wait:
        time.sleep(5)
        slept += 5
        if slept % 60 == 0:
            print(f"    ... 冷却中，剩余 {wait - slept}s")

    # 冷却结束后用真实浏览器探活首页
    try:
        if ENGINE == "browser":
            _fetcher.browser.get_html(DOMAIN + "/", warmup=True)
            print(">>> [恢复] 首页可正常访问，继续抓取 ✅\n")
        else:
            _fetcher.simple.get_html(DOMAIN + "/")
            print(">>> [恢复] 首页可正常访问，继续抓取 ✅\n")
    except BlockedError:
        print(">>> [恢复] 首页仍处于封锁状态 ❌（强烈建议先换 IP 再继续）\n")
    except Exception as e:
        print(f">>> [恢复] 首页探活异常（不致命）：{e}\n")


# ==========================================================
#                  引擎一：轻量 HTTP 抓取
# ==========================================================
class SimpleFetcher:
    """纯 HTTP 抓取：curl_cffi(带 TLS 指纹) > requests > urllib"""

    def __init__(self):
        self._s = None
        self._kind = None
        self._impersonate = None
        self.challenge_hits = 0

    def start(self):
        if self._s is not None or self._kind == "urllib":
            return
        if cffi is not None:
            for imp in SIMPLE_IMPERSONATE_CANDIDATES:
                try:
                    self._s = cffi.Session(impersonate=imp)
                    self._kind = "curl_cffi"
                    self._impersonate = imp
                    break
                except Exception:
                    continue
        if self._s is None and pyrequests is not None:
            try:
                self._s = pyrequests.Session()
                self._kind = "requests"
            except Exception:
                self._s = None
        if self._s is not None:
            try:
                self._s.headers.update(DEFAULT_HEADERS)
            except Exception:
                pass
            if PROXY:
                try:
                    self._s.proxies = _proxies()
                    print(f">>> [代理] 轻量引擎使用代理：{PROXY}")
                except Exception:
                    pass
            extra = f"（TLS 指纹 {self._impersonate}）" if self._impersonate else ""
            print(f">>> [引擎] 轻量 HTTP 模式：{self._kind}{extra}")
        else:
            self._kind = "urllib"
            print(">>> [引擎] 轻量 HTTP 模式：urllib（建议 pip install curl_cffi 以获得更好兼容性）")

    def close(self):
        try:
            if self._s is not None and hasattr(self._s, "close"):
                self._s.close()
        except Exception:
            pass
        self._s = None

    # ---------- 内部请求 ----------
    def _raw_get(self, url):
        """返回 (status, content_bytes, text_or_None, final_url)"""
        if self._kind == "urllib":
            headers = {k: v for k, v in DEFAULT_HEADERS.items() if k != "Connection"}
            headers["Accept-Encoding"] = "gzip"
            req = Request(url, headers=headers)
            try:
                with urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                    status = getattr(r, "status", r.getcode())
                    raw = r.read()
                    if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                        try:
                            raw = gzip.decompress(raw)
                        except Exception:
                            pass
                    return status, raw, None, getattr(r, "url", url)
            except HTTPError as e:
                raw = b""
                try:
                    raw = e.read() or b""
                except Exception:
                    pass
                return e.code, raw, None, url
            except URLError as e:
                raise FetchError(f"网络错误: {e}")

        r = self._s.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        status = r.status_code
        text = None
        try:
            if not getattr(r, "encoding", None) or str(r.encoding).lower() == "iso-8859-1":
                try:
                    r.encoding = r.apparent_encoding or "utf-8"
                except Exception:
                    r.encoding = "utf-8"
            text = r.text
        except Exception:
            text = None
        final_url = getattr(r, "url", url) or url
        return status, r.content, text, final_url

    def get_html(self, url):
        self.start()
        status, raw, text, final_url = self._raw_get(url)
        note_host(final_url)
        html = text if text is not None else _decode_bytes(raw)

        if status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")

        # ★ 先判硬封锁（可能伴随 403，也可能是 200 的错误页）
        if _looks_like_block(html):
            raise BlockedError(f"Cloudflare 硬封锁页 (HTTP {status}): {final_url}")

        if status in (403, 429, 503):
            self.challenge_hits += 1
            raise ChallengeError(f"HTTP {status}（疑似反爬）: {url}")
        if status >= 400:
            raise FetchError(f"HTTP {status}: {url}")

        if _looks_like_challenge(html):
            self.challenge_hits += 1
            raise ChallengeError(f"疑似人机验证 / 空白页: {url}")

        self.challenge_hits = 0
        lo, hi = SIMPLE_JITTER
        time.sleep(random.uniform(lo, hi))
        return html

    def get_bytes(self, url):
        self.start()
        status, raw, text, final_url = self._raw_get(url)
        note_host(final_url)

        if status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")

        if status >= 400:
            preview = text if text is not None else _decode_bytes(raw[:20000])
            if _looks_like_block(preview):
                raise BlockedError(f"Cloudflare 硬封锁页 (HTTP {status}): {final_url}")
            if status in (403, 429, 503):
                self.challenge_hits += 1
                raise ChallengeError(f"HTTP {status}（疑似反爬）: {url}")
            raise FetchError(f"HTTP {status}: {url}")

        if not raw:
            raise FetchError(f"空响应: {url}")
        self.challenge_hits = 0
        return raw


# ==========================================================
#         引擎二：真实浏览器（Playwright / CDP）抓取
# ==========================================================
def cdp_alive(port=CDP_PORT, timeout=1.0):
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
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    if cdp_alive():
        print(f">>> [CDP] 端口 {CDP_PORT} 已在监听，无需重复启动。")
        print(f">>> [CDP] 请在该 Chrome 窗口打开 {DOMAIN}/ 手动确认能访问（若有验证就过一次）。")
        return True

    print(">>> [CDP] 正在启动 Chrome（若已有 Chrome 在运行，请先 ⌘Q 完全退出！）")
    args = [
        f"--user-data-dir={USER_DATA_DIR}",
        f"--remote-debugging-port={CDP_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if PROXY:
        args.append(f"--proxy-server={PROXY}")
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
            print(">>> 请在窗口里确认站点能正常打开（有验证就过一次），然后另开终端执行：")
            print("        python Crawl_azhfds.py cdp slow")
            return True

    print("!!! 等待调试端口超时。可能是已有 Chrome 实例占用了 profile。")
    print("    请先执行：osascript -e 'quit app \"Google Chrome\"'  再重试。")
    print("    或手动执行：\n" + cdp_launch_command())
    return False


# ★ JS 侧状态判定：新增 blocked（硬封锁）识别
_STATE_JS = """
() => {
  const q = s => !!document.querySelector(s);
  const hasSite = q('ul.stui-vodlist') || q('[class*="stui-content_detail"]') ||
                  q('[class*="stui-content__detail"]') || q('[class*="stui-pannel_bd"]') ||
                  q('[class*="stui-pannel__bd"]') || q('[class*="stui-header"]') ||
                  q('a[href*="/vodplay/"]') || q('a[href*="/voddetail/"]') ||
                  q('a[href*="/vodshow/"]');
  const cfFrame = Array.from(document.querySelectorAll('iframe'))
                       .some(f => (f.src || '').includes('challenges.cloudflare.com'));
  const hasChl  = cfFrame || q('#challenge-form') || q('#challenge-running') ||
                  q('#cf-challenge-running') || q('.cf-turnstile') ||
                  q('#turnstile-wrapper') || q('#challenge-stage');
  const title   = document.title || '';
  const titleChl = /just a moment|checking your browser|请稍候|稍等|安全检查/i.test(title);
  const bodyTxt = (document.body && document.body.innerText)
                    ? document.body.innerText.slice(0, 6000) : '';
  const blockedDom = q('#cf-error-details') || q('.cf-error-details') ||
                     q('#cf-wrapper .cf-error-overview') || q('.cf-error-overview');
  const blockedTxt = /sorry,?\\s*you have been blocked|you are unable to access|why have i been blocked|error\\s*(code:?)?\\s*1020|access denied/i.test(bodyTxt);
  const rayId      = /cloudflare ray id|ray id:/i.test(bodyTxt);
  const blocked    = (!hasSite) && (blockedDom || blockedTxt || rayId) && !hasChl;
  const len = bodyTxt.length;
  return { hasSite, hasChl, titleChl, blocked, len, title };
}
"""


class BrowserFetcher:
    """用真实 Chrome 抓取；人机验证时等待人工处理；硬封锁时立刻抛错不死等"""

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

    # ---------- 生命周期 ----------
    def start(self):
        if self._ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("!!! 未安装 playwright，请先执行：pip install playwright && playwright install chromium")
            raise

        self._pw = sync_playwright().start()

        if USE_CDP:
            if not cdp_alive():
                print(f"\n!!! 没有检测到可用的 Chrome 调试端口 {CDP_ENDPOINT}\n")
                print("请先执行：")
                print("    osascript -e 'quit app \"Google Chrome\"'")
                print("    python Crawl_azhfds.py open")
                print("或手动执行：")
                print(cdp_launch_command())
                raise FetchError("CDP 端口不可用")

            print(f">>> [浏览器] 正在附着到已运行的 Chrome：{CDP_ENDPOINT}")
            if PROXY:
                print(">>> [代理] 注意：CDP 模式下代理由那个 Chrome 自己的启动参数决定，"
                      "proxy= 只作用于 FAST 通道")
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
            if PROXY:
                launch_kwargs["proxy"] = {"server": PROXY}
                print(f">>> [代理] 浏览器使用代理：{PROXY}")
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

        try:
            note_host(self._page.url or "")
        except Exception:
            pass

        self._report_clearance()

        print(">>> [浏览器] 预热首页 ...")
        try:
            self.get_html(DOMAIN + "/", warmup=True)
            print(">>> [浏览器] 已可正常访问站点 ✅")
        except BlockedError as e:
            _print_block_banner(DOMAIN + "/", e)
            raise HardBlockAbort(
                "站点当前对你的出口 IP 处于 Cloudflare 硬封锁状态，脚本不再继续请求。"
                "请先换 IP / 稍后再试，并先在 Chrome 里手动确认站点能打开。"
            )
        except Exception as e:
            print(f">>> [浏览器] 预热异常（不致命，继续）：{e}")

        if FAST_MODE:
            self._sync_fast_session()

    def _pick_page(self):
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        for p in pages:
            try:
                u = p.url or ""
                if SITE_KEY in u or any(h and h in u for h in _seen_hosts):
                    return p
            except Exception:
                continue
        if pages:
            return pages[0]
        return self._ctx.new_page()

    def _all_site_cookies(self):
        """★ 收集站点主域 + 镜像域名下的全部 cookie（原来只取主域，跳转后会拿到 0 个）"""
        jar = {}
        try:
            raw = self._ctx.cookies()
        except Exception:
            raw = []
        hosts = cookie_hosts()
        for c in raw or []:
            dom = (c.get("domain") or "").lstrip(".").lower()
            if not dom:
                continue
            if any(dom.endswith(h) or h.endswith(dom) for h in hosts):
                jar[c.get("name")] = c.get("value")
        if not jar:
            # 兜底：直接按当前页面 URL 取
            try:
                for c in self._ctx.cookies([DOMAIN, self._page.url or DOMAIN]):
                    jar[c.get("name")] = c.get("value")
            except Exception:
                pass
        return {k: v for k, v in jar.items() if k}

    def _report_clearance(self):
        cookies = self._all_site_cookies()
        if "cf_clearance" in cookies:
            print(f">>> [Cloudflare] 已检测到 cf_clearance cookie ✅（共 {len(cookies)} 个 cookie）")
        else:
            print(f">>> [Cloudflare] 未检测到 cf_clearance cookie"
                  f"（当前站点 cookie 共 {len(cookies)} 个；若站点无 CF 挑战属正常）")

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

    # ---------- 页面状态判定 ----------
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
            note_host(self._page.url or "")
        except Exception:
            pass
        try:
            cf_frame = any("challenges.cloudflare.com" in (f.url or "")
                           for f in self._page.frames)
        except Exception:
            cf_frame = False

        if info.get("hasSite"):
            return "site", html
        # ★ 硬封锁优先判定（DOM 判定 + HTML 兜底判定）
        if info.get("blocked") or (html and _looks_like_block(html)):
            return "blocked", html
        if info.get("hasChl") or info.get("titleChl") or cf_frame:
            return "challenge", html
        if info.get("len", 0) < 50:
            return "unknown", html
        return "unknown", html

    # ---------- 人工过验证 ----------
    def _notify_challenge(self, url):
        print("\a", end="", flush=True)
        print("\n" + "=" * 72)
        print("  ⚠️  检测到【可通过的人机验证】页面，脚本已暂停")
        print("  👉  请切到 Chrome 窗口，勾选 “确认您是真人 / Verify you are human”")
        print(f"  ⏳  脚本至少会等你 {CHALLENGE_GRACE} 秒，最长等待 {CHALLENGE_WAIT} 秒。")
        print(f"      URL: {url}")
        if not USE_CDP:
            print("-" * 72)
            print("  💡 如果反复转圈永远过不了，改用【手动过验证 + CDP 附着】：")
            print("       1) osascript -e 'quit app \"Google Chrome\"'")
            print("       2) python Crawl_azhfds.py open")
            print("       3) 手动过验证")
            print("       4) python Crawl_azhfds.py cdp slow")
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

            # ★ 硬封锁：立刻返回，绝不死等
            if state == "blocked":
                cur = ""
                try:
                    cur = self._page.url or url
                except Exception:
                    cur = url
                raise BlockedError(f"Cloudflare 硬封锁页（无验证入口）: {cur}")

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
                        print("    [自动] 已尝试点击 Turnstile 复选框（你也可以自己点）")
                    next_click_at = time.time() + AUTO_CLICK_EVERY

            if challenge_seen:
                if time.time() - last_tip > 20:
                    print(f"    ... 仍在等待人机验证（剩余 {int(hard_deadline - time.time())}s）")
                    last_tip = time.time()
                if time.time() > hard_deadline:
                    raise FetchError(f"等待人机验证超时: {url}")
            else:
                if time.time() > soft_deadline:
                    return html

            time.sleep(POLL_INTERVAL)

    # ---------- 对外接口 ----------
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

        # ★ 403 且页面是封锁页 -> 直接 BlockedError
        if status == 403:
            state, html = self._page_state()
            if state == "blocked":
                raise BlockedError(f"Cloudflare 硬封锁页 (HTTP 403): {self._page.url or url}")

        html = self._wait_until_ready(url)

        if status >= 500 or status == 429:
            state, _ = self._page_state()
            if state == "blocked":
                raise BlockedError(f"Cloudflare 硬封锁页 (HTTP {status}): {self._page.url or url}")
            if state != "site":
                raise FetchError(f"HTTP {status}: {url}")

        return html

    # ---------- FAST 通道 ----------
    def _make_fast_session(self):
        if cffi is None:
            print(">>> [FAST] 未安装 curl_cffi，FAST 通道不可用")
            return None
        last_err = None
        candidates = ([self._impersonate] if self._impersonate else []) \
                     + FAST_IMPERSONATE_CANDIDATES
        for imp in candidates:
            if not imp:
                continue
            try:
                s = cffi.Session(impersonate=imp)
                if PROXY:
                    try:
                        s.proxies = _proxies()
                    except Exception:
                        pass
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
        """★ 关键改动：没有 cookie 就不启用 FAST（裸请求最容易触发 WAF 1020）"""
        if self._fast_disabled or not FAST_MODE:
            return

        cookies = self._all_site_cookies()

        if not cookies and not FAST_FORCE:
            print(">>> [FAST] 浏览器里没拿到任何站点 cookie —— 这种“裸 HTTP 请求”极易触发")
            print("           Cloudflare WAF 封锁(Error 1020)，因此本轮【不启用】FAST 通道。")
            print("           想强开请加参数 fastforce（不推荐）；正常做法是先在 Chrome 里")
            print("           手动打开一次站点，让 cookie 落到 profile 里再跑。")
            self._fast_ok = False
            self._fast_disabled = True
            return

        s = self._make_fast_session()
        if s is None:
            self._fast_ok = False
            self._fast_disabled = True
            return

        try:
            cur = self._page.url or (DOMAIN + "/")
        except Exception:
            cur = DOMAIN + "/"
        ref_host = _host(cur) or _host(DOMAIN)

        s.headers.update({
            "User-Agent": self.ua or DEFAULT_UA,
            "Accept": DEFAULT_HEADERS["Accept"],
            "Accept-Language": DEFAULT_HEADERS["Accept-Language"],
            "Referer": f"https://{ref_host}/",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        })
        self._fast = (s, cookies)
        self._fast_ok = True
        self._fast_sync_at = time.time()
        if verbose:
            has_clr = "cf_clearance" in cookies
            print(f">>> [FAST] 已同步 {len(cookies)} 个 cookie 到快速通道 "
                  f"(cf_clearance: {'有 ✅' if has_clr else '无'})")

    def _fast_get(self, url, is_binary=False):
        if not FAST_MODE or self._fast_disabled:
            return None

        if self._fast_ok and (time.time() - self._fast_sync_at > FAST_RESYNC_INTERVAL):
            self._sync_fast_session(verbose=False)

        if not (self._fast_ok and self._fast):
            return None

        s, cookies = self._fast
        try:
            r = s.get(url, cookies=cookies, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            note_host(getattr(r, "url", url) or url)

            body_preview = ""
            try:
                body_preview = r.text[:20000]
            except Exception:
                try:
                    body_preview = _decode_bytes(r.content[:20000])
                except Exception:
                    body_preview = ""

            # ★ 命中硬封锁：立即关闭 FAST 并向上抛（触发冷却退避）
            if _looks_like_block(body_preview):
                self._fast_ok = False
                self._fast_disabled = True
                raise BlockedError(f"FAST 通道命中 Cloudflare 硬封锁 (HTTP {r.status_code}): {url}")

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

            try:
                if not r.encoding or str(r.encoding).lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding or "utf-8"
            except Exception:
                pass
            if _looks_like_challenge(r.text):
                print("    [FAST] 命中挑战页，重新同步 cookie 后本次降级浏览器通道")
                self._fast_ok = False
                self._sync_fast_session(verbose=False)
                return None

            self._fast_resync_fail = 0
            return r.text
        except (NoRetryFetchError, BlockedError):
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
            body = ""
            try:
                body = r.text()[:20000]
            except Exception:
                pass
            if _looks_like_block(body):
                raise BlockedError(f"Cloudflare 硬封锁页 (HTTP {r.status}): {url}")
            raise FetchError(f"HTTP {r.status}: {url}")
        return r.body()


# ==========================================================
#              引擎门面：统一入口 + 自动降级
# ==========================================================
class HybridFetcher:
    def __init__(self):
        self.simple = SimpleFetcher()
        self.browser = BrowserFetcher()
        self._started = False

    @property
    def engine(self):
        return ENGINE

    def start(self):
        if self._started:
            return
        if ENGINE == "browser":
            self.browser.start()
        else:
            self.simple.start()
        self._started = True

    def _switch_to_browser(self, reason):
        global ENGINE
        if ENGINE == "browser":
            return False
        if not AUTO_FALLBACK_TO_BROWSER:
            return False
        print("\n" + "!" * 68)
        print(f">>> [引擎切换] 轻量模式被拦：{reason}")
        print(">>> 自动切换到【浏览器引擎】继续抓取（如需彻底解决，请用 open + cdp slow）")
        print("!" * 68 + "\n")
        ENGINE = "browser"
        try:
            self.simple.close()
        except Exception:
            pass
        self.browser.start()
        return True

    def get_html(self, url):
        self.start()
        if ENGINE == "browser":
            return self.browser.get_html(url)
        try:
            return self.simple.get_html(url)
        except BlockedError:
            # 硬封锁换引擎也没用（同一出口 IP），直接上抛让冷却逻辑处理
            raise
        except ChallengeError as e:
            if (self.simple.challenge_hits >= SIMPLE_MAX_CHALLENGE_HITS
                    and self._switch_to_browser(str(e))):
                return self.browser.get_html(url)
            raise

    def get_bytes(self, url):
        self.start()
        if ENGINE == "browser":
            return self.browser.get_bytes(url)
        try:
            return self.simple.get_bytes(url)
        except BlockedError:
            raise
        except ChallengeError as e:
            if (self.simple.challenge_hits >= SIMPLE_MAX_CHALLENGE_HITS
                    and self._switch_to_browser(str(e))):
                return self.browser.get_bytes(url)
            raise

    def close(self):
        try:
            self.simple.close()
        except Exception:
            pass
        try:
            self.browser.close()
        except Exception:
            pass


_fetcher = HybridFetcher()
atexit.register(_fetcher.close)


def fetch(url, is_binary=False):
    """带重试 + 硬封锁冷却退避的统一抓取入口"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if is_binary:
                return _fetcher.get_bytes(url)
            return _fetcher.get_html(url)
        except NoRetryFetchError:
            raise
        except HardBlockAbort:
            raise
        except BlockedError as e:
            last_err = e
            # ★ 不做普通重试，进入冷却退避；超限会抛 HardBlockAbort 终止本轮
            cooldown_for_block(url, e)
            continue
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                if isinstance(e, ChallengeError) or "验证" in str(e):
                    wait = max(wait, 15)
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    raise last_err if last_err else FetchError(f"请求失败: {url}")


# ============== 工具函数 ==============
def has_existing_site_url(item, target_url):
    if not target_url:
        return False
    for k in item.keys():
        if k == "url" or re.match(r"^url\d+$", k):
            if item.get(k, "") == target_url:
                return True
    return False


def _url_keys_sorted(item):
    return sorted(
        [k for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )


def _attach_url(existing, sub_url):
    if not sub_url or has_existing_site_url(existing, sub_url):
        return None

    url_keys = _url_keys_sorted(existing)
    nums = [int(re.match(r"^url(\d+)$", k).group(1))
            for k in url_keys if re.match(r"^url(\d+)$", k)]
    new_key = f"url{(max(nums) if nums else 0) + 1}"

    last = url_keys[-1] if url_keys else None
    ordered, done = {}, False
    for k, v in existing.items():
        ordered[k] = v
        if k == last:
            ordered[new_key] = sub_url
            done = True
    if not done:
        ordered[new_key] = sub_url

    existing.clear()
    existing.update(ordered)
    return new_key


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
    raw_title = (raw_title or "").strip()

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
        return f"{match.group(1)}{num_to_chinese(match.group(2))}{match.group(3)}"

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
            return f"{base_name} {season_clean}", base_info
    elif base_info.endswith("季"):
        return f"{base_name} {base_info}", ""

    return base_name, base_info


def safe_filename(url):
    return os.path.basename((url or "").split("?")[0])


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
        except HardBlockAbort:
            raise
        except Exception as e:
            print(f"  [图片下载失败] {img_url}: {e}")
            return ""
    return fn


def episodes_are_numbered(episodes):
    if not episodes:
        return False
    cnt = 0
    for n in episodes:
        n = n.strip()
        if re.search(r"\d+\s*[集期话話]", n) or re.fullmatch(r"第?\s*\d{1,4}\s*", n):
            cnt += 1
    return cnt >= max(1, len(episodes) // 2)


def detect_episode_unit(episodes, fallback_info=""):
    text = " ".join(episodes.keys())
    if "期" in text:
        return "期"
    if "集" in text or "话" in text or "話" in text:
        return "集"
    m = re.search(r"[集期话話]", fallback_info or "")
    if m:
        return "期" if m.group(0) == "期" else "集"
    return "集"


def info_episode_number(info):
    if not info:
        return None
    for pat in (r"更新[至到]?\s*第?\s*(\d+)\s*[集期话話]",
                r"第\s*(\d+)\s*[集期话話]",
                r"(\d+)\s*[集期话話]",
                r"更新[至到]\D*?(\d+)"):
        m = re.search(pat, info)
        if m:
            return int(m.group(1))
    return None


def same_progress_info(a, b):
    na = info_episode_number(a)
    nb = info_episode_number(b)
    if na is not None and nb is not None:
        return na == nb
    return normalize_text(a or "") == normalize_text(b or "")


def get_max_episode_number(episodes):
    max_num = 0
    for name in episodes.keys():
        m = re.search(r'(\d+)\s*[集期话話]', name)
        if not m:
            m = re.search(r'第\s*(\d+)', name)
        if not m:
            m = re.search(r'(\d+)', name)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num


def episode_progress(episodes):
    if not episodes:
        return 0
    if episodes_are_numbered(episodes):
        n = get_max_episode_number(episodes)
        return n if n > 0 else len(episodes)
    return len(episodes)


def build_progress_info(episodes, old_info=""):
    if not episodes_are_numbered(episodes):
        return None
    n = get_max_episode_number(episodes)
    if n <= 0:
        return None
    old_n = info_episode_number(old_info)
    if old_n is not None and n < old_n:
        return None
    return f"更新至第{n}{detect_episode_unit(episodes, old_info)}"


def merge_missing_fields(existing, rec, log=print):
    changed = False
    for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro", "date"]:
        new_val = rec.get(field)
        if isinstance(new_val, str):
            new_val = "" if is_garbled(new_val) else new_val.strip()
        elif isinstance(new_val, list):
            new_val = [x for x in new_val if x and not is_garbled(x)]
        if not new_val:
            continue
        if not existing.get(field):
            existing[field] = new_val
            changed = True
            log(f"    [字段补全] {field}: {new_val}")
    return changed


def promote_site_to_front(existing, new_episodes, sub_url):
    url_key  = _attach_url(existing, sub_url)
    playlist = existing.setdefault("playlist", [])
    idx = next((i for i, pl in enumerate(playlist)
                if pl.get("name") == PLAYLIST_NAME), None)
    if idx is not None:
        pl = playlist.pop(idx)
        pl["episodes"] = new_episodes
        playlist.insert(0, pl)
        return url_key, "moved"

    playlist.insert(0, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return url_key, "inserted"


def upsert_site_channel(existing, new_episodes, sub_url):
    url_key  = _attach_url(existing, sub_url)
    playlist = existing.setdefault("playlist", [])

    idx = next((i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME), None)
    if idx is not None:
        playlist.pop(idx)

    max_idx, max_eps = 0, -1
    for i, pl in enumerate(playlist):
        cnt = episode_progress(pl.get("episodes", {}))
        if cnt > max_eps:
            max_eps = cnt
            max_idx = i

    insert_pos = (max_idx + 1) if playlist else 0
    playlist.insert(insert_pos, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return url_key, "inserted_after_max"


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
    if any("集" in n for n in names) and len(names) > 2:
        return "Drama"
    return "Movie"


# ============== 列表页解析 ==============
def _img_from_node(node):
    """从 a/div/img 节点里尽力抠出封面地址"""
    if node is None:
        return ""
    for attr in ("data-original", "data-src", "data-echo", "src"):
        v = node.get(attr, "") if hasattr(node, "get") else ""
        if v and not v.startswith("data:"):
            return v
    style = node.get("style", "") if hasattr(node, "get") else ""
    m = re.search(r"url\(\s*['\"]?(.*?)['\"]?\s*\)", style or "")
    if m:
        return m.group(1)
    img = node.select_one("img") if hasattr(node, "select_one") else None
    if img is not None:
        for attr in ("data-original", "data-src", "data-echo", "src"):
            v = img.get(attr, "")
            if v and not v.startswith("data:"):
                return v
    return ""


def _parse_list_soup(soup, base_url):
    items = []
    lis = soup.select("ul.stui-vodlist li")
    if not lis:
        lis = soup.select("[class*=stui-vodlist] li")

    for li in lis:
        thumb = li.find("a", class_=_re_class("stui-vodlist_thumb"))
        if thumb is None:
            thumb = li.find(class_=_re_class("stui-vodlist_thumb"))

        detail = li.find(class_=_re_class("stui-vodlist_detail"))
        h4a = detail.select_one("h4.title a[href]") if detail else None
        if not h4a:
            h4a = li.select_one("h4.title a[href]")

        href = ""
        title = ""
        if h4a is not None:
            href = h4a.get("href", "")
            title = (h4a.get("title") or h4a.get_text(strip=True) or "").strip()
        if (not href or not title) and thumb is not None and thumb.name == "a":
            href = href or thumb.get("href", "")
            title = title or (thumb.get("title") or "").strip()

        if not href or not title:
            continue
        if "/voddetail/" not in href:
            continue

        info = ""
        pic = (thumb.select_one("span.pic-text") if thumb is not None else None) \
            or li.select_one("span.pic-text")
        if pic is not None:
            info = normalize_text(pic.get_text(strip=True))

        img = _img_from_node(thumb) or _img_from_node(li)
        if img:
            img = urljoin(base_url, img)

        name, _ = split_name_info(title)
        if not name:
            name = title
        items.append((name, info, urljoin(base_url, href), img))
    return items


def _find_next_page(soup, cur_url):
    labels = {"下一页", "下页", "下一頁", ">", "»", "＞"}
    for a in soup.select("a[href]"):
        t = normalize_text(a.get_text(strip=True))
        if t in labels:
            href = a.get("href", "")
            if href and not href.startswith("#") and "javascript" not in href.lower():
                return urljoin(cur_url, href)
    return None


def get_list(list_url, max_pages=None):
    """返回 [(name, info, detail_url, img_url), ...]（支持翻页 + 跨页去重）"""
    if max_pages is None:
        max_pages = LIST_MAX_PAGES
    all_items, seen = [], set()
    url = list_url
    for page in range(1, max(1, max_pages) + 1):
        html = fetch(url)
        soup = BeautifulSoup(html, "lxml")
        page_items = _parse_list_soup(soup, url)
        if page > 1:
            print(f"  [第 {page} 页] 发现 {len(page_items)} 条 <- {url}")
        for it in page_items:
            if it[2] in seen:
                continue
            seen.add(it[2])
            all_items.append(it)
        if page >= max_pages:
            break
        nxt = _find_next_page(soup, url)
        if not nxt or nxt == url:
            break
        url = nxt
        polite_sleep()
    return all_items


# ============== 详情页解析 ==============
_BAD_VALUE_PAT = re.compile(r"[。；;…]|关键词|影片|本站|简介|剧情|http|www\.|全集|播放")


def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES:
        return ""
    if is_garbled(v):
        return ""
    return v


def _looks_like_sentence(v):
    """避免把 SEO 长句误当成 导演/主演/类型/地区"""
    return len(v) > 24 or bool(_BAD_VALUE_PAT.search(v))


def parse_detail_fields(detail_div):
    result = {"类型": [], "地区": "", "date": "", "主演": [], "导演": [], "编剧": [], "alias": ""}
    if detail_div is None:
        return result

    LIST_FIELDS = ("类型", "主演", "导演", "编剧")

    def assign(field, value):
        value = _clean_val(value)
        if not value:
            return
        if field in LIST_FIELDS or field in ("地区", "alias"):
            if _looks_like_sentence(value):
                return
        if field in LIST_FIELDS:
            for piece in re.split(r"[/、,，|]+", value):
                piece = piece.strip()
                if piece and piece not in EMPTY_VALUES and piece not in result[field]:
                    result[field].append(piece)
        elif field == "地区":
            if not result["地区"]:
                result["地区"] = value
        elif field == "alias":
            if not result["alias"]:
                result["alias"] = value
        elif field == "date":
            if not result["date"]:
                m = re.search(r"(19|20)\d{2}", value)
                result["date"] = m.group(0) if m else value

    def detect_field(text):
        if not text:
            return None
        if re.search(r"类\s*型", text):
            return "类型"
        if re.search(r"地\s*区|国\s*家|产\s*地", text):
            return "地区"
        if re.search(r"年\s*份|上\s*映", text):
            return "date"
        if re.search(r"主\s*演|演\s*员", text):
            return "主演"
        if re.search(r"导\s*演", text):
            return "导演"
        if re.search(r"编\s*剧", text):
            return "编剧"
        if re.search(r"又\s*名|别\s*名", text):
            return "alias"
        return None

    p_tags = detail_div.select("p.data") or detail_div.select("p")

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

    if not any([result["类型"], result["地区"], result["date"], result["主演"], result["导演"]]):
        for span in detail_div.find_all("span"):
            classes = span.get("class", []) or []
            if "split-line" in classes:
                continue
            field = detect_field(span.get_text(strip=True))
            if not field:
                continue
            parent = span.parent
            if not parent:
                continue
            found = False
            for sib in parent.children:
                if sib is span:
                    found = True
                    continue
                if not found:
                    continue
                if isinstance(sib, Tag):
                    if sib.name == "span":
                        if "split-line" in (sib.get("class", []) or []):
                            break
                        if detect_field(sib.get_text(strip=True)):
                            break
                    elif sib.name == "a":
                        assign(field, sib.get_text(strip=True))
                elif isinstance(sib, NavigableString):
                    v = _clean_val(str(sib))
                    if v:
                        assign(field, v)

    return result


INTRO_PREFIX_PATTERNS = [
    r"^.*?影片的关键词是[^，,。；;]*[，,。；;]\s*",   # azhfds 的 SEO 前缀
    r"^\s*剧情简介[：:]\s*",
    r"^\s*简介[：:]\s*",
]
INTRO_TAIL_PATTERNS = [
    r"如果您?觉得.*$",
    r"本站.*?(收集|整理|提供).*$",
]


def _clean_intro(text):
    text = normalize_text(text)
    if not text:
        return ""
    for pat in INTRO_PREFIX_PATTERNS:
        new = re.sub(pat, "", text, count=1, flags=re.S)
        if new != text:
            text = new
            break
    for pat in INTRO_TAIL_PATTERNS:
        text = re.sub(pat, "", text, flags=re.S)
    text = normalize_text(text)
    text = text.lstrip("。，,、;；:：")
    return "" if is_garbled(text) else normalize_text(text)


def parse_intro(soup):
    desc = soup.find(id="desc")
    if desc is None:
        # 兜底：找标题含“剧情简介/简介”的面板
        for h3 in soup.select("h3.title, h3"):
            t = normalize_text(h3.get_text(" ", strip=True))
            if "简介" in t:
                box = h3.find_parent(class_=_re_class("stui-pannel-box")) \
                      or h3.find_parent(class_=_re_class("stui-pannel"))
                if box is not None:
                    desc = box
                    break
    if desc is None:
        return ""

    bd = desc.find(class_=_re_class("stui-pannel_bd")) or desc
    ps = bd.select("p.detail, p.col-pd, p") or []
    best = ""
    for p in ps:
        txt = _clean_intro(p.get_text(" ", strip=True))
        if len(txt) > len(best):
            best = txt
    if not best:
        best = _clean_intro(bd.get_text(" ", strip=True))
    return best


def _playlist_label(ul):
    """向上找该选集列表所属面板的标题文字（如：高清云播）"""
    node = ul
    for _ in range(6):
        node = node.parent
        if node is None or not isinstance(node, Tag):
            break
        head = node.select_one("h3.title") or node.select_one(
            "[class*=stui-pannel_head] h3, [class*=stui-pannel_hd] h3")
        if head is not None:
            return normalize_text(head.get_text(" ", strip=True))
    return ""


def _collect_playlist_links(container, exclude_pat):
    eps = {}
    for a in container.select("a[href]"):
        href = a.get("href", "")
        if "/vodplay/" not in href:
            continue
        if a.find_parent(class_=exclude_pat):
            continue
        name = normalize_text(a.get_text(strip=True))
        if name and href:
            eps[name] = urljoin(DOMAIN, href)
    return filter_episodes(eps)


def extract_episodes(soup):
    """优先抓「高清云播」下的选集，其次取选集最多的面板；返回 {集名: 播放url}"""
    exclude_pat = re.compile(r"stui[-_]+content[-_]+thumb|play-btn|stui[-_]+vodlist[-_]+thumb")

    uls = soup.select("ul.stui-content_playlist") or soup.select("[class*=stui-content_playlist]")
    cands = []
    for ul in uls:
        eps = _collect_playlist_links(ul, exclude_pat)
        if not eps:
            continue
        label = _playlist_label(ul)
        score = 0
        for i, kw in enumerate(EPISODE_PANEL_KEYWORDS):
            if kw and kw in label:
                score = len(EPISODE_PANEL_KEYWORDS) - i
                break
        cands.append((score, len(eps), eps, label))

    if cands:
        cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return cands[0][2]

    for bd in soup.find_all(class_=_re_class("stui-pannel_bd")):
        eps = _collect_playlist_links(bd, exclude_pat)
        if eps:
            return eps

    return _collect_playlist_links(soup, exclude_pat)


def parse_real_name(soup, default_name):
    detail = soup.find(class_=_re_class("stui-content_detail")) or soup
    h1 = detail.find("h1", class_="title") or detail.find("h1")
    if h1 is None:
        return default_name
    for sp in h1.find_all(["span", "small", "em", "i"]):
        classes = " ".join(sp.get("class", []) or [])
        if any(k in classes for k in ("score", "raty", "text-muted", "hidden", "badge")):
            sp.extract()
    t = normalize_text(h1.get_text(" ", strip=True))
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t


def extract_image_from_detail(soup):
    thumb = soup.find(class_=_re_class("stui-content_thumb")) \
        or soup.find(class_=_re_class("stui-vodlist_thumb"))
    if thumb is not None:
        img = _img_from_node(thumb)
        if img:
            return urljoin(DOMAIN, img)
    img_tag = soup.select_one("img.lazyload[data-original], img[data-original]")
    if img_tag is not None:
        v = img_tag.get("data-original", "") or img_tag.get("src", "")
        if v:
            return urljoin(DOMAIN, v)
    return ""


def extract_info_from_detail(soup):
    for sel in (".stui-content_thumb span.pic-text",
                "[class*=stui-content_thumb] span.pic-text",
                "[class*=stui-vodlist_thumb] span.pic-text",
                "span.pic-text"):
        node = soup.select_one(sel)
        if node is not None:
            txt = normalize_text(node.get_text(strip=True))
            if txt:
                return txt
    return ""


def parse_subpage(sub_url, default_name, default_info, list_img=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    detail = soup.find(class_=_re_class("stui-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    info = default_info or extract_info_from_detail(soup)
    img_url = list_img or extract_image_from_detail(soup)

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
        "编剧":   fields.get("编剧", []),
        "主演":   fields["主演"],
        "类型":   fields["类型"],
        "地区":   fields["地区"],
        "date":   fields["date"],
        "alias":  fields.get("alias", ""),
        "intro":  intro or "",
        "评分":   {"豆瓣": "", "IMDB": ""},   # 该站评分不准，恒空
        "playlist": playlist,
    }


# ============== JSON 读写（原子写 + 节流） ==============
def load_json():
    if not os.path.exists(JSON_PATH):
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JSON_PATH)


_pending_changes = 0
_pending_data = None


def mark_dirty(data, force=False):
    global _pending_changes, _pending_data
    _pending_data = data
    _pending_changes += 1
    if force or _pending_changes >= SAVE_EVERY:
        save_json(data)
        _pending_changes = 0


def flush_pending():
    global _pending_changes
    if _pending_changes and _pending_data is not None:
        try:
            save_json(_pending_data)
            print(">>> [保存] 已写入未落盘的变更")
        except Exception as e:
            print(f">>> [保存失败] {e}")
        _pending_changes = 0


atexit.register(flush_pending)


# ============== 去重检索 ==============
def _year(v):
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


def find_existing_global(data, name, sub_url, rec_date=None, log=print):
    def normalize_name(s):
        return s.replace(" ", "").strip() if s else ""

    norm_name = normalize_name(name)
    new_year = _year(rec_date)

    if sub_url:
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                existing_urls = {item.get(k) for k in item.keys()
                                 if k == "url" or re.match(r"^url\d+$", k)}
                if sub_url in existing_urls:
                    existing_name = item.get("name", "")
                    if existing_name != name:
                        log(f"      [URL匹配去重] 发现 URL 一致但名称不同的记录 "
                            f"(URL: {sub_url}, 已有:「{existing_name}」, "
                            f"抓取:「{name}」, 所在分类:{group})")
                    return group, item

    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            existing_raw_name = item.get("name", "")
            if normalize_name(existing_raw_name) != norm_name:
                continue

            old_year = _year(item.get("date"))
            if old_year and new_year and abs(old_year - new_year) > 1:
                log(f"      [名称同名但年份不符] 「{existing_raw_name}」({old_year}) "
                    f"≠ 抓取「{name}」({new_year})，视为不同作品")
                continue

            log(f"      [名称去重（忽略空格）] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
            return group, item

    return None, None


# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    filter_regions = FILTER_REGIONS_OVERRIDE.get(list_url, FILTER_REGIONS)
    try:
        items = get_list(list_url)
    except HardBlockAbort:
        raise
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        return 0, 0, 0
    print(f"  共发现 {len(items)} 条")
    ok, fail, skipped = 0, 0, 0

    for idx, (name, info, url, img) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在名称黑名单中，跳过]")
            skipped += 1
            continue

        if any(bad_url in url for bad_url in BLACKLIST_URLS):
            print(f"  ({idx}/{len(items)}) {name} [URL在黑名单中，跳过] -> {url}")
            skipped += 1
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
                skipped += 1
                polite_sleep()
                continue

            current_group = group
            if group == "AUTO":
                current_group = detect_group_by_episodes(new_eps)
                buf.append(f"    [自动分类] 选集共 {len(new_eps)} 项，判定为「{current_group}」")

            if current_group in ("Drama", "Anime") and len(new_eps) > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」属于「{current_group}」，"
                      f"集数 {len(new_eps)} 超过 {MAX_EPISODES} 集(期) 上限 ")
                skipped += 1
                polite_sleep()
                continue

            matched_group, existing = find_existing_global(
                data, real_name, url, rec_date=rec.get("date"), log=buf.append
            )

            if existing and matched_group != current_group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，"
                           f"将按「{matched_group}」规则处理（当前抓取分类为「{current_group}」）")

            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            elif current_group in ("Anime", "Drama", "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = rec.get("地区", "")
                region_clean = region.strip()

                if any(keyword == region_clean for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    skipped += 1
                    polite_sleep()
                    continue

                if region_clean in ("", "未知"):
                    cn_type_keywords = ["国产", "中国", "大陆", "内地"]
                    type_text = " ".join(rec.get("类型", []) or [])
                    matched_kw = next((kw for kw in cn_type_keywords if kw in type_text), None)
                    if matched_kw:
                        flush()
                        print(f"    - 跳过：地区未知，但类型「{type_text}」含"
                              f"「{matched_kw}」，判定为国产内容")
                        skipped += 1
                        polite_sleep()
                        continue

            if existing:
                new_max  = episode_progress(new_eps)
                now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                fields_changed = merge_missing_fields(existing, rec, buf.append)

                if not existing.get("image") and rec.get("image"):
                    local = download_and_localize_image(rec["image"])
                    if local:
                        existing["image"] = local
                        fields_changed = True
                        buf.append(f"    [字段补全] image: {local}")

                playlist = existing.setdefault("playlist", [])
                gd_index = next(
                    (i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME),
                    None
                )
                old_eps = playlist[gd_index].get("episodes", {}) if gd_index is not None else None

                url_missing = not has_existing_site_url(existing, url)

                existing_max = 0
                for pl in playlist:
                    if pl.get("name") == PLAYLIST_NAME:
                        continue
                    existing_max = max(existing_max, episode_progress(pl.get("episodes", {})))

                old_info = existing.get("info", "")

                # ★ 只有选集真的变了，才允许调整 playlist 顺序（保护手动排序）
                eps_changed = (gd_index is None) or (old_eps != new_eps)

                if matched_group in ("Drama", "Anime", "Show"):
                    if new_max >= existing_max:
                        if eps_changed:
                            new_info_text = build_progress_info(new_eps, old_info) or old_info
                        else:
                            new_info_text = old_info

                        info_changed = not same_progress_info(new_info_text, old_info)

                        if not (eps_changed or info_changed or fields_changed or url_missing):
                            flush()
                            print(f"    - 无字段变更，跳过：{real_name}")
                            skipped += 1
                            polite_sleep()
                            continue

                        if eps_changed:
                            url_key, action = promote_site_to_front(existing, new_eps, url)
                        else:
                            url_key = _attach_url(existing, url)
                            action = "kept_order"

                        if info_changed:
                            existing["info"] = new_info_text
                            buf.append(f"    [info更新] 「{old_info}」 -> 「{new_info_text}」")

                        if matched_group in ("Drama", "Anime") and new_max <= existing_max:
                            pass
                        else:
                            existing["update"] = now_str

                        if eps_changed:
                            buf.append(f"    [{matched_group}] 新抓取集数 {new_max} >= 其它渠道最大 "
                                       f"{existing_max}，插入并置顶")
                        else:
                            buf.append(f"    [{matched_group}] 内容一致，保持原有 playlist 顺序"
                                       f"（仅补全字段/URL/info）")

                        mark_dirty(data)
                        flush()
                        if action == "moved":
                            print(f"    ✅ 更新({matched_group})：{PLAYLIST_NAME} 已更新并置顶到 playlist 首位"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        elif action == "inserted":
                            print(f"    ✅ 更新({matched_group})：{PLAYLIST_NAME} 作为新渠道写入 "
                                  f"{url_key or '(已有URL)'}，并置顶到 playlist 首位")
                        else:
                            print(f"    ✅ 更新({matched_group})：内容未变，保持 playlist 原有顺序"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        ok += 1
                    else:
                        if not (eps_changed or fields_changed or url_missing):
                            flush()
                            print(f"    - 无字段变更，跳过：{real_name}")
                            skipped += 1
                            polite_sleep()
                            continue

                        if eps_changed:
                            url_key, action = upsert_site_channel(existing, new_eps, url)
                        else:
                            url_key = _attach_url(existing, url)
                            action = "kept_order"

                        if matched_group not in ("Drama", "Anime"):
                            existing["update"] = now_str

                        if eps_changed:
                            buf.append(f"    [{matched_group}] 新抓取集数 {new_max} < 其它渠道最大 "
                                       f"{existing_max}，插入到最大集数渠道下方")
                        else:
                            buf.append(f"    [{matched_group}] 内容一致，保持原有 playlist 顺序"
                                       f"（仅补全字段/URL）")

                        mark_dirty(data)
                        flush()
                        if action == "kept_order":
                            print(f"    ✅ 更新({matched_group})：内容未变，保持 playlist 原有顺序"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        else:
                            print(f"    ✅ 更新({matched_group})：{PLAYLIST_NAME} 已插入/更新到最大集数渠道下方"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        ok += 1

                else:
                    scraped_info = rec.get("info", "")

                    if eps_changed:
                        new_info_text = build_progress_info(new_eps, old_info)
                        if new_info_text:
                            final_info = new_info_text
                        elif not old_info and scraped_info:
                            final_info = scraped_info
                        else:
                            final_info = old_info
                    else:
                        final_info = old_info if old_info else scraped_info

                    info_changed = not same_progress_info(final_info, old_info)

                    if not (eps_changed or info_changed or fields_changed or url_missing):
                        flush()
                        print(f"    - 无字段变更，跳过：{real_name}")
                        skipped += 1
                        polite_sleep()
                        continue

                    if eps_changed:
                        url_key, action = promote_site_to_front(existing, new_eps, url)
                    else:
                        url_key = _attach_url(existing, url)
                        action = "kept_order"

                    if info_changed:
                        existing["info"] = final_info
                        buf.append(f"    [info更新] 「{old_info}」 -> 「{final_info}」")
                    existing["update"] = now_str
                    mark_dirty(data)
                    flush()
                    if action == "moved":
                        print(f"    ✅ 更新(Movie)：{PLAYLIST_NAME} 已更新并置顶到 playlist 首位"
                              f"{f'（补写 {url_key}）' if url_key else ''}")
                    elif action == "inserted":
                        print(f"    ✅ 更新(Movie)：{PLAYLIST_NAME} 作为新渠道写入 "
                              f"{url_key or '(已有URL)'}，并置顶到 playlist 首位")
                    else:
                        print(f"    ✅ 更新(Movie)：内容未变，保持 playlist 原有顺序"
                              f"{f'（补写 {url_key}）' if url_key else ''}")
                    ok += 1

            else:
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                data.setdefault(current_group, []).append(rec)
                print(f"    ✅ 新增 -> {current_group} (共 {len(new_eps)} 集) "
                      f"[真实名称: {real_name}] [URL: {rec['url']}]")
                mark_dirty(data)
                ok += 1

        except HardBlockAbort:
            mark_dirty(data, force=True)
            raise
        except BlockedError as e:
            flush()
            print(f"    ✗ 被 Cloudflare 拒绝，跳过本条: {e}")
            fail += 1
        except Exception as e:
            flush()
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        polite_sleep()

    mark_dirty(data, force=True)
    return ok, fail, skipped


# ============== 补全模式 ==============
def fetch_detail_data(url):
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    detail = soup.find(class_=_re_class("stui-content_detail"))
    if detail is None:
        return None, None
    fields = parse_detail_fields(detail)
    fields["intro"] = parse_intro(soup)
    fields["导演"] = " / ".join(fields["导演"]) if fields["导演"] else ""
    img_url = extract_image_from_detail(soup)
    return fields, img_url


def fill_empty_fields(item, fields, img_url=""):
    changed = False
    if not item.get("导演") and fields.get("导演"):
        item["导演"] = fields["导演"]; changed = True
    for f in ["主演", "类型", "编剧"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    for f in ["地区", "date", "intro", "alias"]:
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
            target_url = None
            for k in url_keys:
                u = item.get(k, "")
                if u and SITE_KEY in u:
                    target_url = u
                    break
            if not target_url:
                continue

            need = (not item.get("导演") and not item.get("主演")
                    and not item.get("类型") and not item.get("地区")
                    and not item.get("intro")) or not item.get("image")
            if not need:
                continue

            total += 1
            print(f"  [{group}] 补全: {item.get('name')}  <- {target_url}")
            try:
                fields, img_url = fetch_detail_data(target_url)
                if fields is None:
                    print("    ✗ 跳过：无详情内容")
                    polite_sleep()
                    continue
                if fill_empty_fields(item, fields, img_url):
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    mark_dirty(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} "
                          f"地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except HardBlockAbort:
                mark_dirty(data, force=True)
                raise
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            polite_sleep()

    mark_dirty(data, force=True)
    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")


# ============== 启动预检 ==============
def preflight():
    """开跑前先探一次首页：被硬封锁就立刻给结论，不浪费时间"""
    print(">>> [预检] 探测站点可访问性 ...")
    try:
        fetch(DOMAIN + "/")
        print(">>> [预检] 站点可访问 ✅\n")
        return True
    except HardBlockAbort:
        raise
    except BlockedError as e:
        _print_block_banner(DOMAIN + "/", e)
        raise HardBlockAbort("预检即被 Cloudflare 硬封锁，请先换出口 IP 再重跑。")
    except Exception as e:
        print(f">>> [预检] 异常（不致命，继续）：{e}\n")
        return False


# ============== 主流程 ==============
def parse_cli():
    global USE_CDP, HEADLESS, FAST_MODE, FAST_FORCE, AUTO_CLICK_TURNSTILE
    global ENGINE, AUTO_FALLBACK_TO_BROWSER, LIST_MAX_PAGES
    global SLEEP_BETWEEN, SIMPLE_JITTER, PROXY

    raw_args = sys.argv[1:]
    args = [a.lstrip("-") for a in raw_args]
    low  = [a.lower() for a in args]

    # 代理参数需要保留大小写
    for a in args:
        m = re.match(r"^(?:proxy|代理)=(.+)$", a, re.I)
        if m:
            PROXY = m.group(1).strip()
            print(f">>> [配置] 使用代理：{PROXY}")

    if "open" in low or "launch" in low:
        launch_chrome_for_cdp()
        sys.exit(0)

    for a in low:
        m = re.match(r"^pages?=(\d+)$", a)
        if m:
            LIST_MAX_PAGES = max(1, int(m.group(1)))
            print(f">>> [配置] 每个分类最多抓 {LIST_MAX_PAGES} 页")
        m = re.match(r"^(?:sleep|delay)=([\d.]+)$", a)
        if m:
            SLEEP_BETWEEN = max(0.2, float(m.group(1)))
            print(f">>> [配置] 请求间隔基准 {SLEEP_BETWEEN:.1f}s")

    if "slow" in low:
        SLEEP_BETWEEN = max(SLEEP_BETWEEN, 5.0)
        SIMPLE_JITTER = (1.0, 2.5)
        print(f">>> [模式] SLOW：请求间隔基准 {SLEEP_BETWEEN:.1f}s + 随机抖动（抗 WAF 推荐）")

    if "simple" in low or "light" in low or "http" in low:
        ENGINE = "simple"
    if "browser" in low or "chrome" in low:
        ENGINE = "browser"
    if "cdp" in low:
        ENGINE = "browser"
        USE_CDP = True
        AUTO_CLICK_TURNSTILE = False   # 手动点更稳，脚本不干扰
        print(">>> [模式] CDP：将附着到你手动启动的 Chrome（不会关闭它）")
    if "headless" in low:
        ENGINE = "browser"
        HEADLESS = True
        print(">>> [模式] 无头（注意：可能无法通过人机验证）")
    if "fast" in low or "fastforce" in low:
        ENGINE = "browser"
        FAST_MODE = True
        print(">>> [模式] FAST：启用 curl_cffi 加速通道（无 cookie 时会自动禁用以防被封）")
    if "fastforce" in low:
        FAST_FORCE = True
        print(">>> [模式] FASTFORCE：即使没有 cookie 也强开 FAST（⚠️ 极易触发 1020 封锁）")
    if "nofast" in low:
        FAST_MODE = False
        FAST_FORCE = False
        print(">>> [配置] 已禁用 FAST 通道")
    if "click" in low:
        AUTO_CLICK_TURNSTILE = True
        print(">>> [模式] 允许脚本自动点击 Turnstile")
    if "nofallback" in low:
        AUTO_FALLBACK_TO_BROWSER = False
        print(">>> [配置] 已禁用「轻量 -> 浏览器」自动降级")

    print(f">>> [引擎] 当前使用：{ENGINE}"
          f"{'（自动降级已开启）' if ENGINE == 'simple' and AUTO_FALLBACK_TO_BROWSER else ''}")
    return "backfill" in low


def main():
    is_backfill = parse_cli()
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)
    data = load_json()

    try:
        _fetcher.start()
        preflight()

        if is_backfill:
            backfill_existing(data)
            print("\n====================================")
            print(f"补全任务完成! 数据已保存在 {JSON_PATH}")
            return

        total_ok, total_fail, total_skip = 0, 0, 0
        for list_url, group, page_name in LIST_PAGES:
            ok, fail, skipped = process_list_page(data, list_url, group, page_name)
            total_ok   += ok
            total_fail += fail
            total_skip += skipped

        flush_pending()
        print("\n====================================")
        print(f"所有抓取任务完成! 成功 {total_ok} 条，跳过 {total_skip} 条，失败 {total_fail} 条。"
              f"数据已保存在 {JSON_PATH}")

    except HardBlockAbort as e:
        flush_pending()
        print("\n" + "=" * 76)
        print(f"⛔ 本轮抓取已终止：{e}")
        print("   已抓取的数据都已安全写入 JSON，稍后换 IP 再跑即可接着补。")
        print("   建议命令：python Crawl_azhfds.py cdp slow")
        print("=" * 76)
    except KeyboardInterrupt:
        flush_pending()
        print("\n>>> 已手动中断，数据已保存。")
    finally:
        flush_pending()
        _fetcher.close()


if __name__ == "__main__":
    main()