# -*- coding: utf-8 -*-
import json
import os
import sys
import glob
import shutil
import time
import re
import subprocess
import atexit
from urllib.parse import urljoin, urlparse

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup

from curl_cffi import requests as c_requests

AFTER_FETCH_SLEEP = 0.1

# 标准 requests 的 Session（图片代理兜底用）
_std_session = requests.Session()

# 日志配置
VERBOSE_LOG = False


def log(message: str, force: bool = False):
    if force or VERBOSE_LOG:
        print(message)


# =============================================================
# 基础配置
# =============================================================
TARGET_DOMAIN = "pys2.com"
LIST_BASE_URL = "https://www.pys2.com"
DETAIL_BASE_URL = "https://www.pys2.com"
INDEX_BASE_URL = "https://www.pys2.com"
OUTPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"

# ============ 数据安全相关配置（新增）============
BACKUP_DIR = os.path.join(os.path.dirname(OUTPUT_FILE), "backup")
BAK_FILE = OUTPUT_FILE + ".bak"
REJECTED_FILE = OUTPUT_FILE + ".rejected.json"
MAX_BACKUPS = 20                 # backup/ 目录里最多保留多少份启动快照
ALLOW_SHRINK_RATIO = 0.90        # 新数据条目数不得低于基线的 90%，否则拒绝写盘
SHRINK_GUARD_MIN_ITEMS = 20      # 基线条目少于这个数时不启用缩水保护（方便初期使用）
ALLOW_FRESH_START = False        # ⚠️ 只有你确实想从零开始建库时才改 True
REMOVE_EMPTY_PLAYLIST_ITEMS = False   # 是否删除没有 playlist 的历史条目（默认不删，防误删）

_BASELINE_TOTAL = 0              # 启动时加载到的条目总数（缩水保护基线）
_LOAD_OK = False                 # 是否成功加载了初始数据（未成功则禁止任何写盘）

MIN_SCORE_LIMIT = 6.3
OLD_VIDEO_MIN_SCORE = 6.3
CURRENT_YEAR = str(time.localtime().tm_year)

DRAMA_MAX_EPISODES_LIMIT = 25
ANIME_MAX_EPISODES_LIMIT = 25
EPISODE_WHITELIST = {"test"}

FILTER_REGIONS = {"中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"}
EXCLUDED_SOURCES = {"非凡", "牛牛", "无尽", "奇异", "猫眼", "ikun"}
QIANGXIAN_KEYWORDS = ['TC', 'TS', '抢先', 'HC']

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.pys2.com/",
}

REQUEST_TIMEOUT = 20
SLEEP_BETWEEN_REQUESTS = 1.0
RETRY_TIMES = 3
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

IMAGE_PROXY_TEMPLATES = [
    "https://images.weserv.nl/?url={host_and_path}",
    "https://wsrv.nl/?url={host_and_path}",
]

# ============ Cloudflare / 浏览器相关配置（按需修改）============
USE_BROWSER = True                 # 用真实 Chrome 作为“门卫”过 Cloudflare
FORCE_BROWSER_ALWAYS = False       # True = 所有页面都用浏览器抓（最稳最慢）
BROWSER_HEADLESS = False           # 必须 False 才能手动点人机验证
BROWSER_PORT = 9333                # 独立端口，不影响你日常 Chrome
BROWSER_PROFILE_DIR = os.path.expanduser("~/pys2_crawler_chrome_profile")
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MANUAL_VERIFY_TIMEOUT = 300        # 等你手动过验证的最长秒数
KEEP_BROWSER_OPEN = False          # True = 脚本结束后不关闭浏览器
IMPERSONATE = "chrome"             # curl_cffi 指纹（chrome = 当前库支持的最新版）
CLEARANCE_REFRESH_SEC = 20 * 60    # 超过这个时间未同步，主动回浏览器刷新一次

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
# Cloudflare 检测 + 浏览器门卫
# =============================================================
CHALLENGE_KEYWORDS = (
    "just a moment",
    "请稍候",
    "请稍後",
    "enable javascript and cookies to continue",
    "checking if the site connection is secure",
    "verifying you are human",
    "verify you are human",
    "cf-chl-bypass",
    'id="challenge-form"',
    "attention required! | cloudflare",
    "ddos protection by cloudflare",
    "/cdn-cgi/challenge-platform/h/",
)


def looks_like_challenge(html: str | None, status: int = 200, headers=None) -> bool:
    """判断返回内容是不是 Cloudflare 拦截页 / 挑战页"""
    if status in (403, 429, 503):
        return True
    if headers:
        try:
            mit = headers.get("cf-mitigated") or headers.get("Cf-Mitigated") or ""
        except Exception:
            mit = ""
        if str(mit).lower() == "challenge":
            return True
    if not html or len(html) < 800:
        return True
    head = html[:8000].lower()
    if "<title>just a moment" in head:
        return True
    for kw in CHALLENGE_KEYWORDS:
        if kw in head:
            if kw == "/cdn-cgi/challenge-platform/h/":
                if ("vod-list" in html) or ("vod-info" in html) or ("index-vod-" in html):
                    continue
            return True
    return False


def detect_local_chrome_ua() -> str:
    """读取本机 Chrome 版本号拼出真实 UA（兜底用）"""
    ver = ""
    p = os.path.expanduser("~/Library/Application Support/Google/Chrome/Last Version")
    try:
        with open(p, "r") as f:
            ver = f.read().strip()
    except Exception:
        pass
    if not ver:
        try:
            ver = subprocess.check_output(
                ["/usr/bin/defaults", "read",
                 "/Applications/Google Chrome.app/Contents/Info.plist",
                 "CFBundleShortVersionString"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            pass
    if ver:
        return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{ver} Safari/537.36")
    return HEADERS["User-Agent"]


class CFClient:
    """
    Cloudflare 网络层：
      - 主通道：curl_cffi（带浏览器 TLS 指纹 + 浏览器同步来的 UA/Cookie）
      - 门卫：DrissionPage 接管真实 Chrome，负责过人机验证 & 刷新 cf_clearance
    """

    def __init__(self):
        self._page = None
        self._browser_failed = False
        self.ua = detect_local_chrome_ua()
        self.cookies = {}
        self.session = self._make_session()
        self.last_sync = 0.0
        self.prefer_browser = FORCE_BROWSER_ALWAYS
        self._manual_hint_printed = False

    # ---------- curl_cffi ----------
    def _make_session(self):
        try:
            return c_requests.Session(impersonate=IMPERSONATE)
        except Exception:
            return c_requests.Session(impersonate="chrome120")

    def _client_hints(self) -> dict:
        m = re.search(r"Chrome/(\d+)", self.ua or "")
        major = m.group(1) if m else "140"
        return {
            "sec-ch-ua": f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not=A?Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
        }

    def headers(self, referer: str | None = None, for_image: bool = False) -> dict:
        h = dict(HEADERS)
        h["User-Agent"] = self.ua
        h.update(self._client_hints())
        if for_image:
            h["Accept"] = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
            h["sec-fetch-dest"] = "image"
            h["sec-fetch-mode"] = "no-cors"
            h.pop("sec-fetch-user", None)
            h.pop("Upgrade-Insecure-Requests", None)
        if referer:
            h["Referer"] = referer
        return h

    def _absorb(self, resp):
        try:
            for k, v in resp.cookies.items():
                self.cookies[k] = v
        except Exception:
            pass

    # ---------- 浏览器 ----------
    def ensure_browser(self):
        if self._page is not None:
            return self._page
        if self._browser_failed or not USE_BROWSER:
            return None
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except ImportError:
            print(">>> [浏览器] 未安装 DrissionPage，请执行:  pip install DrissionPage")
            self._browser_failed = True
            return None

        try:
            co = ChromiumOptions()
            if CHROME_PATH and os.path.exists(CHROME_PATH):
                co.set_browser_path(CHROME_PATH)
            co.set_paths(local_port=BROWSER_PORT, user_data_path=BROWSER_PROFILE_DIR)
            co.set_argument("--disable-blink-features=AutomationControlled")
            co.set_argument("--lang=zh-CN")
            co.set_argument("--window-size=1280,960")
            co.set_argument("--no-first-run")
            co.set_argument("--no-default-browser-check")
            if BROWSER_HEADLESS:
                co.headless(True)
            self._page = ChromiumPage(co)
        except Exception as e:
            print(f">>> [浏览器] 启动失败: {e}")
            self._browser_failed = True
            self._page = None
            return None

        try:
            ua = self._page.run_js("return navigator.userAgent")
            if ua:
                self.ua = ua
        except Exception:
            pass
        print(f">>> [浏览器] 已启动 (port={BROWSER_PORT}, profile={BROWSER_PROFILE_DIR})")
        print(f">>> [浏览器] 真实 UA = {self.ua}")
        return self._page

    def _page_html(self) -> str:
        try:
            return self._page.html or ""
        except Exception:
            return ""

    def _get_browser_cookies(self) -> dict:
        d = {}
        if self._page is None:
            return d
        try:
            try:
                cks = self._page.cookies(all_domains=True, all_info=False)
            except TypeError:
                cks = self._page.cookies()
            try:
                d = dict(cks.as_dict())
            except Exception:
                for c in cks:
                    if isinstance(c, dict) and c.get("name"):
                        d[c["name"]] = c.get("value", "")
        except Exception as e:
            log(f">>> [浏览器] 读取 cookie 失败: {e}", force=True)
        return d

    def sync_from_browser(self):
        ck = self._get_browser_cookies()
        if ck:
            self.cookies.update(ck)
            self.last_sync = time.time()
        try:
            ua = self._page.run_js("return navigator.userAgent")
            if ua:
                self.ua = ua
        except Exception:
            pass

    def _try_click_turnstile(self) -> bool:
        """尽力自动点一下 Cloudflare 复选框（失败就交给人工）"""
        page = self._page
        if page is None:
            return False
        for _ in range(3):
            time.sleep(2.5)
            # 策略 1：进入挑战 iframe 点 checkbox
            try:
                fr = None
                for expr in ('@src^https://challenges.cloudflare.com',
                             '@src:challenges.cloudflare.com',
                             '@title^Widget'):
                    try:
                        fr = page.get_frame(expr, timeout=2)
                    except Exception:
                        fr = None
                    if fr:
                        break
                if fr:
                    for sel in ('css:input[type=checkbox]', 'tag:input', 'css:label'):
                        try:
                            ele = fr.ele(sel, timeout=2)
                            if ele:
                                ele.click(by_js=None)
                                time.sleep(3)
                                if not looks_like_challenge(self._page_html()):
                                    return True
                        except Exception:
                            continue
            except Exception:
                pass
            # 策略 2：点容器（坐标点击）
            try:
                for sel in ('css:.cf-turnstile', 'css:#challenge-stage', 'css:#cf-please-wait'):
                    ele = page.ele(sel, timeout=1)
                    if ele:
                        try:
                            page.actions.move_to(ele).click()
                        except Exception:
                            ele.click()
                        time.sleep(3)
                        if not looks_like_challenge(self._page_html()):
                            return True
            except Exception:
                pass
            if not looks_like_challenge(self._page_html()):
                return True
        return False

    def _wait_manual_pass(self, url: str) -> str:
        """打印提示，轮询等待人工完成验证"""
        if not self._manual_hint_printed:
            print("\n" + "=" * 66)
            print("🛡  检测到 Cloudflare 人机验证！")
            print("👉 请在弹出的 Chrome 窗口中点击那个复选框 / 完成验证。")
            print("   （通过后无需任何操作，脚本会自动继续；本次通行证会被记住）")
            print(f"   当前页面: {url}")
            print(f"   最长等待 {MANUAL_VERIFY_TIMEOUT} 秒 ...")
            print("=" * 66 + "\n")
            self._manual_hint_printed = True
        else:
            print(f"🛡  再次触发验证，请到 Chrome 窗口点一下：{url}")

        deadline = time.time() + MANUAL_VERIFY_TIMEOUT
        while time.time() < deadline:
            time.sleep(2)
            html = self._page_html()
            if not looks_like_challenge(html):
                print("✅ 人机验证已通过，继续抓取。\n")
                return html
        print("❌ 等待超时，仍未通过验证。\n")
        return self._page_html()

    def browser_get(self, url: str) -> str | None:
        page = self.ensure_browser()
        if page is None:
            return None
        try:
            page.get(url, retry=1, timeout=40)
        except Exception as e:
            log(f">>> [浏览器] 打开失败 {url}: {e}", force=True)
            return None
        try:
            page.wait.doc_loaded(timeout=20)
        except Exception:
            pass
        html = self._page_html()
        if looks_like_challenge(html):
            if not self._try_click_turnstile():
                html = self._wait_manual_pass(url)
            else:
                html = self._page_html()
        self.sync_from_browser()
        time.sleep(AFTER_FETCH_SLEEP)
        return html

    def warm_up(self):
        """开跑前先用浏览器过一次首页，拿到有效 cf_clearance"""
        if not USE_BROWSER:
            print(">>> [提示] USE_BROWSER=False，将直接用 curl_cffi 抓取（可能被 CF 拦）")
            return
        html = self.browser_get(LIST_BASE_URL + "/")
        if html and not looks_like_challenge(html):
            print(">>> [预热] 站点可正常访问，通行证已就绪 ✅")
        else:
            print(">>> [预热] 首页仍未通过验证，请检查浏览器窗口 ⚠️")

    def _need_refresh(self) -> bool:
        return USE_BROWSER and (time.time() - self.last_sync > CLEARANCE_REFRESH_SEC)

    # ---------- 对外统一入口 ----------
    def get(self, url: str, referer: str | None = None) -> str | None:
        time.sleep(AFTER_FETCH_SLEEP)
        if self.prefer_browser:
            html = self.browser_get(url)
            if html and not looks_like_challenge(html):
                return html

        if self._need_refresh():
            log(">>> [维护] 通行证可能过期，先用浏览器刷新一次 ...", force=True)
            self.browser_get(LIST_BASE_URL + "/")

        for attempt in range(RETRY_TIMES):
            try:
                resp = self.session.get(
                    url,
                    headers=self.headers(referer),
                    cookies=self.cookies,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
                    try:
                        resp.encoding = resp.apparent_encoding or "utf-8"
                    except Exception:
                        resp.encoding = "utf-8"
                html = resp.text
                if not looks_like_challenge(html, resp.status_code, resp.headers):
                    self._absorb(resp)
                    return html
            except Exception as e:
                log(f"  [请求异常] {url} -> {e}", force=True)

            html = self.browser_get(url)
            if html and not looks_like_challenge(html):
                return html
            time.sleep(2)

        log(f"  [请求失败] {url} （多次尝试仍被拦截）", force=True)
        return None

    def close(self):
        if self._page is not None and not KEEP_BROWSER_OPEN:
            try:
                self._page.quit()
                print(">>> [浏览器] 已关闭")
            except Exception:
                pass


CF = CFClient()
atexit.register(CF.close)


def fetch(url: str) -> str | None:
    return CF.get(url)


# =============================================================
# URL 辅助函数
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


# =============================================================
# 工具函数
# =============================================================
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
    """判断字符串中是否包含中文字符"""
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
# ★★★ 数据持久化：安全读 / 安全写 / 备份 ★★★
# =============================================================
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
    """返回可用于恢复的候选文件，越靠前越新"""
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
        print(f">>> [备份] 创建启动快照失败（不影响抓取）: {e}")


def load_existing(path: str) -> dict:
    """
    安全加载：
      1) 主文件可读 -> 用主文件
      2) 主文件坏/空 -> 依次尝试 .bak 和 backup/ 目录里的历史快照
      3) 全部失败且主文件确实存在 -> 终止脚本（绝不用空数据覆盖）
      4) 主文件根本不存在（真·首次运行）-> 返回 {}
    """
    global _BASELINE_TOTAL, _LOAD_OK

    main_exists = os.path.exists(path)
    main_size = os.path.getsize(path) if main_exists else -1

    # ---- 1) 主文件 ----
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

    # ---- 2) 尝试从备份恢复 ----
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
            # 立刻把恢复结果写回主文件，避免后续再走恢复流程
            save_data(data, force=True, quiet=False)
            return data

        # ---- 3) 主文件存在但彻底救不回来 ----
        if not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print("脚本已终止：为防止用空数据覆盖你的历史库，本次不会写入任何内容。")
            print("请手动处理后再运行：")
            print(f"  1. 检查 {path}")
            print(f"  2. 检查备份目录 {BACKUP_DIR}")
            print(f"  3. 检查是否有残留临时文件 {path}.tmp")
            print("  4. 从 Time Machine / 其他备份恢复一份可用的 JSON 覆盖回主文件")
            print("  5. 若你确实要从零重建数据库，把 ALLOW_FRESH_START 改成 True")
            print("!" * 70 + "\n")
            sys.exit(1)
        print(">>> [警告] ALLOW_FRESH_START=True，将从空数据开始（历史数据会被覆盖）")
        _BASELINE_TOTAL = 0
        _LOAD_OK = True
        return {}

    # ---- 4) 真·首次运行 ----
    print(f">>> [读取] 主文件不存在，视为首次运行: {path}")
    _BASELINE_TOTAL = 0
    _LOAD_OK = True
    return {}


def save_data(data: dict, force: bool = False, quiet: bool = True) -> bool:
    """
    安全写入：
      - 未成功加载初始数据 -> 拒绝写
      - 条目数相比基线缩水过多 -> 拒绝写，并把可疑数据另存 .rejected.json
      - 先序列化到内存 -> 备份旧文件到 .bak -> 写 tmp + fsync -> 回读校验 -> 原子替换
    """
    global _BASELINE_TOTAL

    if not _LOAD_OK:
        print("  [拒绝保存] 初始数据未成功加载，禁止写盘（防止覆盖历史库）")
        return False

    if not isinstance(data, dict):
        print("  [拒绝保存] 待写数据不是 dict")
        return False

    total = count_items(data)

    # ---- 缩水保护 ----
    if (not force) and _BASELINE_TOTAL >= SHRINK_GUARD_MIN_ITEMS \
            and total < _BASELINE_TOTAL * ALLOW_SHRINK_RATIO:
        print(f"\n  ⛔ [拒绝保存] 条目数异常缩水：{_BASELINE_TOTAL} -> {total} "
              f"(低于 {ALLOW_SHRINK_RATIO:.0%} 阈值)")
        try:
            with open(REJECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"  [提示] 可疑数据已另存到 {REJECTED_FILE}，主文件未被修改\n")
        except Exception as e:
            print(f"  [提示] 可疑数据另存失败: {e}\n")
        return False

    # ---- 序列化（先在内存里完成，失败就不动磁盘）----
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"  [错误] JSON 序列化失败，本次不写盘: {e}")
        return False

    if len(payload.strip()) < 10:
        print("  [拒绝保存] 序列化结果异常过短")
        return False

    tmp_file = OUTPUT_FILE + ".tmp"
    try:
        ensure_dir(os.path.dirname(OUTPUT_FILE))

        # 旧文件有效则先备份成 .bak（滚动一份"上一次成功状态"）
        if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
            try:
                shutil.copy2(OUTPUT_FILE, BAK_FILE)
            except Exception as e:
                print(f"  [警告] 生成 .bak 失败（继续写入）: {e}")

        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

        # 回读校验，确保 tmp 是完整合法 JSON
        _read_json_strict(tmp_file)

        os.replace(tmp_file, OUTPUT_FILE)

        _BASELINE_TOTAL = max(_BASELINE_TOTAL, total)
        if not quiet:
            print(f"  [已保存] {OUTPUT_FILE} 共 {total} 条")
        return True
    except Exception as e:
        print(f"  [错误] 实时保存失败（主文件保持原样）: {e}")
        try:
            if os.path.exists(tmp_file):
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

    img_headers = CF.headers(referer=DETAIL_BASE_URL + "/", for_image=True)

    for url in url_candidates:
        try:
            resp = CF.session.get(url, headers=img_headers, cookies=CF.cookies,
                                  timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200 and _save(resp.content):
                _print(f"[封面已下载|curl_cffi] {filename}")
                return filename
        except Exception:
            pass

    _print("[快速降级] 直接走第三方图片代理...")
    parsed = urlparse(img_url)
    host_and_path = parsed.netloc + parsed.path
    if parsed.query:
        host_and_path += "?" + parsed.query
    proxy_headers = {"User-Agent": CF.ua}

    for proxy_tpl in IMAGE_PROXY_TEMPLATES:
        proxy_url = proxy_tpl.format(host_and_path=host_and_path)
        for use_curl in (True, False):
            try:
                if use_curl:
                    resp = c_requests.get(proxy_url, headers=proxy_headers,
                                          timeout=REQUEST_TIMEOUT * 2,
                                          impersonate=IMPERSONATE, verify=False)
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
# 已有数据索引
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


# =============================================================
# 解析列表
# =============================================================
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


# =============================================================
# 解析详情页
# =============================================================
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

    # 评分过滤
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
        # 修改前: data["intro"] = re.sub(r"\s+", "", intro_text)
        # 修改后: 保留单词间的正常空格
        data["intro"] = clean_ws(intro_text)

    return data


# =============================================================
# Playlist 排序与合并逻辑
# =============================================================
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

            # 【保护】非电影类，若新源集数明显少于旧源，忽略这种错误缩减，保留旧 episodes
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


# =============================================================
# URL 构造
# =============================================================
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


# =============================================================
# 处理单个条目
# =============================================================
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
    if detail_html is not None:
        time.sleep(AFTER_FETCH_SLEEP)
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

            # 1. 基础字段处理 (date, alias)
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

            # 2. 简介 (intro) 智能更新策略
            old_intro = str(old_entry.get("intro", "") or "").strip()
            new_intro = str(detail.get("intro", "") or "").strip()

            if not old_intro and new_intro:
                detail["intro"] = new_intro
                change_reasons.append(f"补全字段 [intro]: (长度: {len(new_intro)})")
            elif old_intro and new_intro and old_intro != new_intro:
                old_has_zh = has_chinese(old_intro)
                new_has_zh = has_chinese(new_intro)

                # 情况 A: 旧的是纯英文，新抓到了中文 -> 坚决用中文替换
                if not old_has_zh and new_has_zh:
                    detail["intro"] = new_intro
                    change_reasons.append(f" [intro] (以中文简介替换原英文简介)")

                # 情况 B: 旧的是中文，新的是纯英文 -> 策略可选：
                elif old_has_zh and not new_has_zh:
                    # 【选项 1】直接忽略英文，保留中文（最纯粹）：
                    detail["intro"] = old_intro
                    
                    # 【选项 2】如果你想“中英文共存/双语”，取消下面两行注释：
                    # detail["intro"] = f"{old_intro}\n\n[EN]\n{new_intro}"
                    # change_reasons.append(f" [intro] (追加英文简介)")

                # 情况 C: 两者都有中文，或两者都是英文 -> 按内容长度决定
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


# =============================================================
# 抓取分类
# =============================================================
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
        if html is not None:
            time.sleep(AFTER_FETCH_SLEEP)
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
    if html is not None:
        time.sleep(AFTER_FETCH_SLEEP)
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
    """
    非破坏性清理：
      - 只移除历史遗留字段 update_pk
      - 默认不再删除没有 playlist 的条目（REMOVE_EMPTY_PLAYLIST_ITEMS=False）
    """
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


_caffeinate_proc = None


def start_caffeinate():
    global _caffeinate_proc
    try:
        _caffeinate_proc = subprocess.Popen(["caffeinate", "-idmu"])
        print(">>> [系统] 已开启防休眠模式 (caffeinate)")
    except Exception as e:
        print(f">>> [系统] 无法启动 caffeinate: {e}")


def stop_caffeinate():
    global _caffeinate_proc
    if _caffeinate_proc:
        _caffeinate_proc.terminate()
        print(">>> [系统] 已关闭防休眠模式")


atexit.register(stop_caffeinate)


def main():
    start_caffeinate()

    # ---------- ① 先安全加载 & 备份，再动网络 ----------
    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    final = load_existing(OUTPUT_FILE)      # 读不到会直接退出，绝不清库
    snapshot_backup(OUTPUT_FILE)            # 留一份启动快照
    before_total = count_items(final)
    clean_existing_data(final)
    global_index = build_index(final)
    print(f">>> 已有数据分类数: {len(final)}；总条目数: {count_items(final)} "
          f"(基线 {_BASELINE_TOTAL})")

    if os.path.exists(OUTPUT_FILE + ".tmp"):
        print(f">>> [提示] 发现残留临时文件 {OUTPUT_FILE}.tmp（说明上次写盘被中断），"
              f"可自行检查后删除")

    # ---------- ② 过 Cloudflare ----------
    CF.warm_up()
    print(">>> [预热等待] Cloudflare验证完成，休眠数秒后正式开始抓取...")
    time.sleep(5)

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

    # ---------- ③ 收尾再存一次 ----------
    save_data(final, quiet=False)
    after_total = count_items(final)
    print(f"\n✅ 全部抓取任务结束。条目数: {before_total} -> {after_total}")


if __name__ == "__main__":
    main()