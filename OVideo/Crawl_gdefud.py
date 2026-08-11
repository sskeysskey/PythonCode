# -*- coding: utf-8 -*-
"""
gdefud.com 分类页（电影/电视剧/综艺/动漫）爬取脚本
—— Cloudflare Turnstile 版：推荐「手动过一次验证 + CDP 附着 + curl_cffi 高速通道」

【推荐用法（方案 2）】
    1) 彻底退出 Chrome：osascript -e 'quit app "Google Chrome"'
    2) python Crawl_gdefud.py open        # 用脚本 profile 启动带调试端口的 Chrome
    3) 在弹出的窗口里手动勾选过 Cloudflare 验证（一次就过）
    4) 窗口别关，另开终端： python Crawl_gdefud.py cdp fast

其它用法：
    python Crawl_gdefud.py                 # 正常抓取（自动弹出真实 Chrome 窗口）
    python Crawl_gdefud.py backfill        # 补全模式
    python Crawl_gdefud.py cdp             # 附着到你手动启动的 Chrome
    python Crawl_gdefud.py headless        # 无头模式（不推荐，容易被 CF 拦）
    python Crawl_gdefud.py fast            # 开启 curl_cffi 加速通道（失败会自动降级）
参数可组合，例如：python Crawl_gdefud.py cdp fast backfill
"""

import os
import re
import sys
import json
import time
import socket
import platform
import subprocess
import atexit
from urllib.parse import urljoin
from urllib.request import urlopen
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime

from curl_cffi import requests as cffi   # 仅在 FAST 模式下使用

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

# ============== 配置 ==============
DOMAIN        = "https://gdefud.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "gdefud"
SITE_KEY      = "gdefud"
REQUEST_TIMEOUT = 20
SLEEP_BETWEEN  = 1.0

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 5.0     # 第 n 次失败后等待 RETRY_BACKOFF * n 秒

# 落盘节流：每 N 条变更写一次磁盘（1 = 实时写盘）
SAVE_EVERY    = 1

# ============== 浏览器 / Cloudflare 相关配置 ==============
USER_DATA_DIR   = os.path.expanduser("~/.gdefud_chrome_profile")
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9222
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False
FAST_MODE       = False
NAV_TIMEOUT_MS  = 60000

# —— curl_cffi 指纹（按你实际 Chrome 大版本，从前往后自动降级尝试）——
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

# CDP 模式下默认不自动点（避免干扰用户手点导致 Turnstile 重置）
AUTO_CLICK_TURNSTILE   = True
AUTO_CLICK_FIRST_DELAY = 8
AUTO_CLICK_EVERY       = 15

# 判定「这是 Cloudflare 挑战页」的特征串（仅用于 FAST 通道的纯文本判定）
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
SITE_MARKERS = ("stui-", "vodshow", "vodplay", "stui-vodlist")

BLACKLIST_NAMES = ["天堂之剑", "定海神针：九尾三世劫",
                   "机甲少女破时空战记", "无名传奇", "魔彩王国历险记",
                   "阿松与阿暖", "红色珍珠", "飞越疯人院"]
# 白名单（在这里添加你要放行的名称，跳过地区屏蔽）
WHITELIST_NAMES = [
    "北斗神拳 拳王军杂兵们的挽歌", "麻辣教师第二季", "新攻壳机动队"
]

# 分类页 -> 分组
LIST_PAGES = [
    ("https://gdefud.com/vodshow/1--time---------2026.html", "Movie", "电影"),
    ("https://gdefud.com/vodshow/2--time---------2026.html", "Drama", "电视剧"),
    ("https://gdefud.com/vodshow/3--time---------2026.html", "Show",  "综艺"),
    ("https://gdefud.com/vodshow/4--time---------2026.html", "Anime", "动漫"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "日本"]
FILTER_REGIONS_OVERRIDE = {
    "https://gdefud.com/vodshow/1--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "https://gdefud.com/vodshow/2--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "台湾", "中国台湾", "日本"],
}

EMPTY_VALUES = {"未知", "内详", "暂无", "/"}

INVALID_EPISODE_NAMES = {
    "立即播放", "收藏", "播放", "倒序", "正序", "排序",
    "下载", "分享", "报错", "举报", "评论",
}


# ============== 网络异常类型 ==============
class FetchError(Exception):
    pass


class NoRetryFetchError(FetchError):
    """客户端错误（404 等），重试无意义"""
    pass


# ==========================================================
#              CDP：启动 / 探测你手动开的 Chrome
# ==========================================================
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
    """用脚本的 profile 启动一个带调试端口的真实 Chrome（macOS: open -na）"""
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    if cdp_alive():
        print(f">>> [CDP] 端口 {CDP_PORT} 已在监听，无需重复启动。")
        print(">>> [CDP] 请在该 Chrome 窗口打开 https://gdefud.com/ 手动过一次验证。")
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
            print("        python Crawl_gdefud.py cdp fast")
            return True

    print("!!! 等待调试端口超时。可能是已有 Chrome 实例占用了 profile。")
    print("    请先执行：osascript -e 'quit app \"Google Chrome\"'  再重试。")
    print("    或手动执行：\n" + cdp_launch_command())
    return False


# ==========================================================
#                     真实浏览器抓取层
# ==========================================================
# 用 DOM 结构判定页面状态，比字符串匹配可靠得多
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
    # 挑战特征命中，但页面里同时有站点结构 -> 认为已经是正常页
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

    # ---------- 生命周期 ----------
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
                print("\n!!! 没有检测到可用的 Chrome 调试端口 "
                      f"{CDP_ENDPOINT}\n")
                print("请先执行：")
                print("    osascript -e 'quit app \"Google Chrome\"'")
                print("    python Crawl_gdefud.py open")
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
            # CDP 模式下页面已经是"真人环境"，不再注入任何脚本，避免额外指纹
            try:
                self._ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                )
            except Exception:
                pass

        # 优先复用一个已经打开在目标站点的标签页（CDP 模式下就是你手动过验证的那个）
        self._page = self._pick_page()

        try:
            self.ua = self._page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            self.ua = ""

        self._report_clearance()

        # 预热首页，一次性把 Cloudflare 验证过掉
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
                if "gdefud" in (p.url or ""):
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
                print("    建议：先在这个 Chrome 窗口打开 https://gdefud.com/ 手动过一次验证。")

    def close(self):
        try:
            if self._ctx and not USE_CDP:
                self._ctx.close()
            # USE_CDP 模式：绝不关闭用户的浏览器，保留 cf_clearance
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
        """返回 (state, html)，state ∈ {'site', 'challenge', 'unknown'}"""
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
        if info.get("len", 0) < 50:      # 白屏 / 还没渲染完
            return "unknown", html
        return "unknown", html

    # ---------- 人工过验证 ----------
    def _notify_challenge(self, url):
        print("\a", end="", flush=True)      # 响一声提醒
        print("\n" + "=" * 72)
        print("  ⚠️  检测到 Cloudflare 人机验证页面，脚本已暂停")
        print("  👉  请切到 Chrome 窗口，勾选 “确认您是真人 / Verify you are human”")
        print(f"  ⏳  脚本至少会等你 {CHALLENGE_GRACE} 秒，最长等待 {CHALLENGE_WAIT} 秒。")
        print(f"      URL: {url}")
        if not USE_CDP:
            print("-" * 72)
            print("  💡 如果反复转圈永远过不了（Playwright 启动的浏览器易被识别），")
            print("     强烈建议改用【手动过验证 + CDP 附着】：")
            print("       1) osascript -e 'quit app \"Google Chrome\"'")
            print("       2) python Crawl_gdefud.py open")
            print("       3) 在窗口里手动过验证（一次就过）")
            print("       4) python Crawl_gdefud.py cdp fast")
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
        """只在 Turnstile 的 iframe 内点复选框；不乱点 body/label，避免把验证点重置"""
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
        """
        一直等到页面变成真正的站点页面为止。
        """
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

            # ---- 已是正常站点页 ----
            if state == "site" and not (challenge_seen and time.time() < grace_until):
                stable += 1
                need = PASS_STABLE_HITS if challenge_seen else 1
                if stable >= need:
                    if challenge_seen:
                        print("    ✅ 人机验证已通过，继续抓取\n")
                        time.sleep(1.0)
                        cur = (self._page.url or "").split("#")[0].rstrip("/")
                        tgt = url.split("#")[0].rstrip("/")
                        # 有时验证完会落到首页，需要重新打开目标页
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

            # ---- 仍在验证页 ----
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
                    raise FetchError(f"等待 Cloudflare 人机验证超时: {url}")
            else:
                # 没检测到验证，但也没识别出站点结构：短等一会儿就放行，交给解析层
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
        html = self._wait_until_ready(url)      # 所有等待都在这里，绝不提前跳走

        if status >= 500 or status == 429:
            state, _ = self._page_state()
            if state != "site":                 # CF 挑战页常返回 403/503，过了就不算错误
                raise FetchError(f"HTTP {status}: {url}")

        return html

    # ---------- FAST 通道 ----------
    def _make_fast_session(self):
        """按候选指纹依次尝试创建 curl_cffi Session"""
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
        """把浏览器的 cookie + UA 同步给 curl_cffi，作为加速通道"""
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

        # 定期从浏览器刷新一次 cookie（cf_clearance 会被服务端轮换）
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
                    wait = max(wait, 15)   # 被 CF 拦过，多喘口气再来
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    raise last_err if last_err else FetchError(f"请求失败: {url}")


# ============== 工具函数 ==============

def has_existing_site_url(item, target_url):
    """检查item中是否已经存在目标url（匹配url/url1/url2...）"""
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
    else:
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


def promote_gdefud_to_front(existing, new_episodes, sub_url):
    url_key  = _attach_url(existing, sub_url)
    playlist = existing.setdefault("playlist", [])
    gd_index = next((i for i, pl in enumerate(playlist)
                     if pl.get("name") == PLAYLIST_NAME), None)
    if gd_index is not None:
        pl = playlist.pop(gd_index)
        pl["episodes"] = new_episodes
        playlist.insert(0, pl)
        return url_key, "moved"

    playlist.insert(0, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return url_key, "inserted"


def upsert_gdefud_channel(existing, new_episodes, sub_url):
    url_key  = _attach_url(existing, sub_url)
    playlist = existing.setdefault("playlist", [])
    for pl in playlist:
        if pl.get("name") == PLAYLIST_NAME:
            pl["episodes"] = new_episodes
            return url_key, "updated"

    playlist.append({"name": PLAYLIST_NAME, "episodes": new_episodes})
    return url_key, "appended"


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
    has_ji = any("集" in n for n in names)
    if has_ji and count > 2:
        return "Drama"
    return "Movie"


# ============== 列表页解析 ==============
def get_list(list_url):
    """返回 [(name, info, detail_url, img_url), ...]"""
    html = fetch(list_url)
    soup = BeautifulSoup(html, "lxml")
    items = []
    for li in soup.select("ul.stui-vodlist li"):
        detail = li.find(class_=_re_class("stui-vodlist_detail"))
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

        thumb = li.find(class_=_re_class("stui-vodlist_thumb"))
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

        name, _ = split_name_info(title)
        if not name:
            name = title
        items.append((name, info, urljoin(DOMAIN, href), img))
    return items


# ============== 详情页解析 ==============
def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES:
        return ""
    if is_garbled(v):
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

    if not any([result["类型"], result["地区"], result["date"], result["主演"], result["导演"]]):
        for span in detail_div.find_all("span"):
            classes = span.get("class", []) or []
            if "split-line" in classes:
                continue
            text = span.get_text(strip=True)
            field = detect_field(text)
            if not field:
                continue
            parent = span.parent
            if not parent:
                continue
            found_span = False
            for sibling in parent.children:
                if sibling is span:
                    found_span = True
                    continue
                if not found_span:
                    continue
                if isinstance(sibling, Tag):
                    if sibling.name == "span":
                        sib_classes = sibling.get("class", []) or []
                        if "split-line" in sib_classes:
                            break
                        sib_text = sibling.get_text(strip=True)
                        if detect_field(sib_text):
                            break
                    elif sibling.name == "a":
                        assign(field, sibling.get_text(strip=True))

    return result


def parse_intro(soup):
    desc = soup.find(id="desc")
    if not desc:
        return ""
    bd = desc.find(class_=_re_class("stui-pannel_bd"))
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
    """只抓取【云播资源】下面的选集，返回 {集名: 播放url}"""
    exclude_pat = re.compile(r"stui-content_+thumb|play-btn|stui-vodlist_+thumb")

    best = {}

    target_playlist_ul = None
    for head_div in soup.select(".stui-pannel_head.bottom-line.active"):
        h3_title = head_div.select_one("h3.title")
        if not h3_title:
            continue
        title_text = normalize_text(h3_title.get_text(strip=True))
        if "云播资源" in title_text:
            parent_box = head_div.find_parent(class_=_re_class("stui-pannel-box"))
            if parent_box:
                target_playlist_ul = parent_box.select_one("ul.stui-content_playlist")
            break

    if target_playlist_ul:
        eps = {}
        for a in target_playlist_ul.select("li a[href]"):
            href = a.get("href", "")
            if "/vodplay/" not in href:
                continue
            if a.find_parent(class_=exclude_pat):
                continue
            name = a.get_text(strip=True)
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
        if len(eps) > len(best):
            best = eps

    if best:
        return filter_episodes(best)

    pannel_bd = soup.find_all(class_=_re_class("stui-pannel_bd"))
    eps = {}
    for bd in pannel_bd:
        for a in bd.select('a[href*="/vodplay/"]'):
            if a.find_parent(class_=exclude_pat):
                continue
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
    if eps:
        return filter_episodes(eps)

    eps = {}
    for a in soup.select('a[href*="/vodplay/"]'):
        if a.find_parent(class_=exclude_pat):
            continue
        name = a.get_text(strip=True)
        href = a.get("href", "")
        if name and href:
            eps[name] = urljoin(DOMAIN, href)
    return filter_episodes(eps)


def parse_real_name(soup, default_name):
    detail = soup.find(class_=_re_class("stui-content_detail"))
    if not detail:
        return default_name
    h1 = detail.find("h1", class_="title")
    if not h1:
        return default_name
    for sp in h1.find_all("span"):
        classes = sp.get("class", []) or []
        if any(("score" in c) or ("raty" in c) for c in classes):
            sp.extract()
    t = h1.get_text(strip=True)
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t


def extract_image_from_detail(soup):
    thumb = soup.find(class_=_re_class("stui-vodlist_thumb"))
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
    thumb = soup.find(class_=_re_class("stui-vodlist_thumb"))
    if thumb:
        pic = thumb.select_one("span.pic-text")
        if pic:
            return pic.get_text(strip=True)
    return ""


def parse_subpage(sub_url, default_name, default_info, list_img=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    detail = soup.find(class_=_re_class("stui-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    info = default_info
    if not info:
        info = extract_info_from_detail(soup)

    img_url = list_img
    if not img_url:
        img_url = extract_image_from_detail(soup)

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
            existing_norm_name = normalize_name(existing_raw_name)
            if existing_norm_name != norm_name:
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
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        return 0, 0, 0
    print(f"  共发现 {len(items)} 条")
    ok, fail, skipped = 0, 0, 0

    for idx, (name, info, url, img) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在黑名单中，跳过]")
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
                time.sleep(SLEEP_BETWEEN)
                continue

            current_group = group
            if group == "AUTO":
                current_group = detect_group_by_episodes(new_eps)
                buf.append(f"    [自动分类] 选集共 {len(new_eps)} 项，判定为「{current_group}」")

            MAX_EPISODES = 20
            if current_group in ("Drama", "Anime") and len(new_eps) > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」属于「{current_group}」，"
                      f"集数 {len(new_eps)} 超过 {MAX_EPISODES} 集(期) 上限 ")
                skipped += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            matched_group, existing = find_existing_global(
                data, real_name, url, rec_date=rec.get("date"), log=buf.append
            )

            effective_group = matched_group if existing else current_group
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
                    time.sleep(SLEEP_BETWEEN)
                    continue

                if region_clean in ("", "未知"):
                    cn_type_keywords = ["国产", "中国", "大陆", "内地"]
                    type_text = " ".join(rec.get("类型", []) or [])
                    matched_kw = next(
                        (kw for kw in cn_type_keywords if kw in type_text),
                        None
                    )
                    if matched_kw:
                        flush()
                        print(f"    - 跳过：地区未知，但类型「{type_text}」含"
                              f"「{matched_kw}」，判定为国产内容")
                        skipped += 1
                        time.sleep(SLEEP_BETWEEN)
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
                    existing_max = max(existing_max,
                                       episode_progress(pl.get("episodes", {})))

                old_info = existing.get("info", "")

                if matched_group in ("Drama", "Anime", "Show"):
                    if new_max >= existing_max:
                        new_info_text = build_progress_info(new_eps, old_info) or old_info

                        eps_changed  = (gd_index is None) or (old_eps != new_eps)
                        pos_changed  = (gd_index is not None and gd_index != 0)
                        info_changed = not same_progress_info(new_info_text, old_info)

                        if not (eps_changed or pos_changed or info_changed
                                or fields_changed or url_missing):
                            flush()
                            print(f"    - 无字段变更，跳过：{real_name}")
                            skipped += 1
                            time.sleep(SLEEP_BETWEEN)
                            continue

                        url_key, action = promote_gdefud_to_front(existing, new_eps, url)
                        if info_changed:
                            existing["info"] = new_info_text
                            buf.append(f"    [info更新] 「{old_info}」 -> 「{new_info_text}」")

                        if matched_group in ("Drama", "Anime") and new_max <= existing_max:
                            pass
                        else:
                            existing["update"] = now_str

                        buf.append(f"    [{matched_group}] 新抓取集数 {new_max} >= 其它渠道最大 "
                                   f"{existing_max}，插入并置顶")
                        mark_dirty(data)
                        flush()
                        if action == "moved":
                            print(f"    ✅ 更新({matched_group})：gdefud 已更新并置顶到 playlist 首位"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        else:
                            print(f"    ✅ 更新({matched_group})：gdefud 作为新渠道写入 "
                                  f"{url_key or '(已有URL)'}，并置顶到 playlist 首位")
                        ok += 1
                    else:
                        eps_changed = (gd_index is None) or (old_eps != new_eps)
                        if not (eps_changed or fields_changed or url_missing):
                            flush()
                            print(f"    - 无字段变更，跳过：{real_name}")
                            skipped += 1
                            time.sleep(SLEEP_BETWEEN)
                            continue

                        url_key, action = upsert_gdefud_channel(existing, new_eps, url)

                        if matched_group not in ("Drama", "Anime"):
                            existing["update"] = now_str

                        buf.append(f"    [{matched_group}] 新抓取集数 {new_max} < 其它渠道最大 "
                                   f"{existing_max}，插入但不置顶")
                        mark_dirty(data)
                        flush()
                        if action == "updated":
                            print(f"    ✅ 更新({matched_group})：gdefud 渠道已就地更新（位置不变）"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        else:
                            print(f"    ✅ 更新({matched_group})：gdefud 作为新渠道写入 "
                                  f"{url_key or '(已有URL)'}，追加到 playlist 末尾")
                        ok += 1

                else:
                    scraped_info = rec.get("info", "")

                    new_info_text = build_progress_info(new_eps, old_info)
                    if new_info_text:
                        final_info = new_info_text
                    elif not old_info and scraped_info:
                        final_info = scraped_info
                    else:
                        final_info = old_info

                    eps_changed  = (gd_index is None) or (old_eps != new_eps)
                    pos_changed  = (gd_index is not None and gd_index != 0)
                    info_changed = not same_progress_info(final_info, old_info)

                    if not (eps_changed or pos_changed or info_changed
                            or fields_changed or url_missing):
                        flush()
                        print(f"    - 无字段变更，跳过：{real_name}")
                        skipped += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

                    url_key, action = promote_gdefud_to_front(existing, new_eps, url)
                    if info_changed:
                        existing["info"] = final_info
                        buf.append(f"    [info更新] 「{old_info}」 -> 「{final_info}」")
                    existing["update"] = now_str
                    mark_dirty(data)
                    flush()
                    if action == "moved":
                        print(f"    ✅ 更新(Movie)：gdefud 已更新并置顶到 playlist 首位"
                              f"{f'（补写 {url_key}）' if url_key else ''}")
                    else:
                        print(f"    ✅ 更新(Movie)：gdefud 作为新渠道写入 "
                              f"{url_key or '(已有URL)'}，并置顶到 playlist 首位")
                    ok += 1

            else:
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                data.setdefault(current_group, []).append(rec)
                print(f"    ✅ 新增 -> {current_group} (共 {len(new_eps)} 集) "
                      f"[真实名称: {real_name}] [URL: {rec['url']}]")
                mark_dirty(data)
                ok += 1

        except Exception as e:
            flush()
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

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

    img_url = extract_image_from_detail(soup)
    return fields, img_url


def fill_empty_fields(item, fields, img_url=""):
    changed = False
    if not item.get("导演") and fields.get("导演"):
        item["导演"] = fields["导演"]; changed = True
    for f in ["主演", "类型"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    for f in ["地区", "date", "intro"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    if img_url and not item.get("image"):
        local = download_and_localize_image(img_url)
        if local:
            item["image"] = local; changed = True
    return changed


def backfill_existing(data):
    print("\n[补全模式] 扫描已有 gdefud 记录中字段缺失的资源 ...")
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
                    time.sleep(SLEEP_BETWEEN)
                    continue
                if fill_empty_fields(item, fields, img_url):
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    mark_dirty(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} 地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            time.sleep(SLEEP_BETWEEN)

    mark_dirty(data, force=True)
    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")


# ============== 主流程 ==============
def parse_cli():
    global USE_CDP, HEADLESS, FAST_MODE, AUTO_CLICK_TURNSTILE
    args = [a.lower().lstrip("-") for a in sys.argv[1:]]

    if "open" in args or "launch" in args:
        launch_chrome_for_cdp()
        sys.exit(0)

    if "cdp" in args:
        USE_CDP = True
        AUTO_CLICK_TURNSTILE = False   # 你手动点更稳，脚本不去干扰
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


def main():
    is_backfill = parse_cli()
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)
    data = load_json()

    try:
        _fetcher.start()   # 提前把浏览器和 Cloudflare 状态搞定

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
    finally:
        flush_pending()
        _fetcher.close()


if __name__ == "__main__":
    main()