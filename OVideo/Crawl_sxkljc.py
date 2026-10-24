# -*- coding: utf-8 -*-
"""
m.sxkljc.com 分类页爬取脚本（当前仅 Movie，已预留 Drama/Anime/Show 扩展）

【更新规则】ONLY_UPDATE_OWN_CHANNEL=True 时：
    JSON 中不存在的作品 → 新增
    JSON 中已存在、且 playlist 已有 sxkljc 渠道 → 正常更新
    JSON 中已存在、但没有 sxkljc 渠道 → 跳过，不做任何修改

【默认用法】
    python Crawl_sxkljc.py                 # curl_cffi 直连抓取；被拦截时自动降级真实 Chrome
    python Crawl_sxkljc.py pages=3         # 分类页向后翻 3 页（默认只抓第 1 页）
    python Crawl_sxkljc.py backfill        # 补全模式（补字段 + 补缺失封面）
    python Crawl_sxkljc.py nobrowser       # 禁用浏览器兜底（纯直连）
    python Crawl_sxkljc.py browser         # 强制全部走真实 Chrome
    python Crawl_sxkljc.py headless        # 浏览器无头（不推荐）
【若站点启用了 Cloudflare】
    1) osascript -e 'quit app "Google Chrome"'
    2) python Crawl_sxkljc.py open         # 启动带调试端口的 Chrome，手动过一次验证
    3) python Crawl_sxkljc.py cdp          # 附着该 Chrome，同步 cookie 后直连高速抓取
参数可组合，例如：python Crawl_sxkljc.py cdp pages=2
"""

import os
import re
import sys
import copy
import json
import time
import glob
import random
import shutil
import socket
import hashlib
import platform
import threading
import subprocess
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from urllib.parse import urljoin, urlparse, unquote, quote
from urllib.request import urlopen
from datetime import datetime
from bs4 import BeautifulSoup

import requests
import urllib3
from requests.adapters import HTTPAdapter
from curl_cffi import requests as cffi

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import fcntl
except ImportError:          # Windows 无 fcntl，锁功能自动失效
    fcntl = None


# ================= 日志双写控制器 =================
class DualLogger:
    """同时将输出写入终端和磁盘日志文件"""
    def __init__(self, log_filepath):
        self.terminal = sys.stdout
        self.log_file = open(log_filepath, "a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, message):
        with self._lock:
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
        _caffeinate_proc = None

atexit.register(stop_caffeinate)


# ============== 站点及业务配置 ==============
SCRIPT_NAME   = "Crawl_sxkljc.py"
DOMAIN        = "https://m.sxkljc.com"
SITE_HOST     = "sxkljc.com"               # 识别「本站线路」：m./www. 子域均算本站
SITE_KEY      = "sxkljc"                   # 用于 url/url1/url2 键中识别本站
PLAYLIST_NAME = "sxkljc"                   # 写入 JSON 的 playlist 名称（统一）
PREFERRED_LINE_KEYWORDS = ("云播资源",)     # 首选线路关键字（按顺序优先）
FALLBACK_LINE_KEYWORDS  = ("高清资源",)     # 首选都没有时，按顺序尝试这些备用线路
PLAYLIST_FALLBACK_FIRST = False            # True：找不到「云播资源」时退而取第一条线路
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
TARGET_COMPARE_CHANNEL = "shangxidq"       # 目标比对排序渠道
ENABLE_GDEFUD_RULE     = True              # 新增渠道时是否启用 gdefud 仲裁
REQUEST_TIMEOUT = 20
SLEEP_BETWEEN   = 1.0                      # 每条之间的基础间隔（会加随机抖动）

# —— 更新规则 ——
# True：已存在于 JSON 的作品，只有其 playlist 里已有本站渠道时才更新；否则跳过（只新增 JSON 里没有的新作品）
# False：恢复旧行为（已存在作品也会把本站作为新渠道追加）
ONLY_UPDATE_OWN_CHANNEL = True

# —— 年份过滤：只抓这些年份 ——
ALLOWED_YEARS        = {"2026"}
SKIP_IF_YEAR_UNKNOWN = True                # 详情页解析不到年份时是否跳过

# —— 列表页 ——
MAX_LIST_PAGES     = 1                     # 每个分类最多翻几页（命令行 pages=N 可覆盖）
DETAIL_URL_PATTERN = re.compile(r"/voddetail/\d+\.html", re.I)   # 只认这种详情页链接

# 分类页（Drama 等后续需要时取消注释即可）
LIST_PAGES = [
    ("https://m.sxkljc.com/vodshow/1-----------2026.html", "Movie", "电影(1)-2026"),
    # ("https://m.sxkljc.com/vodshow/2-----------2026.html", "Drama", "电视剧(2)-2026"),
    # ("https://m.sxkljc.com/vodshow/3-----------2026.html", "Show",  "综艺(3)-2026"),
    # ("https://m.sxkljc.com/vodshow/4-----------2026.html", "Anime", "动漫(4)-2026"),
]

SERIAL_GROUPS        = ("Drama", "Anime", "Show")   # 连载类：按集数规则处理
ADD_CHANNEL_GROUPS   = ("Movie", "Drama", "Anime")  # 已有记录允许追加本站渠道的分类（仅 ONLY_UPDATE_OWN_CHANNEL=False 时生效）
YEAR_CONFLICT_GROUPS = ("Movie",)                   # 名称去重时校验年份冲突的分类（防翻拍片误合并）

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "日本"]
FILTER_REGIONS_BY_GROUP = {
    "Movie": ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "Drama": ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产",
              "泰国", "台湾", "中国台湾", "日本"],
    "Anime": ["中国", "大陆", "内地", "国产", "中国大陆", "中国内地", "国产剧",
              "泰国", "台湾", "中国台湾", "日本"],
}

BLACKLIST_NAMES = [
    "天堂之剑", "定海神针：九尾三世劫", "机甲少女破时空战记", "永恒和一日",
    "无名传奇", "魔彩王国历险记", "阿松与阿暖", "欲望的陷阱", "轻松熊", "家1",
    "人生赢家", "判决", "判决墨西哥剧", "后门", "校规101", "校规", "无人区",
    "第二盘",
]
BLACKLIST_URLS = []
WHITELIST_NAMES = ["二十世纪电气目录", "茶啊二中 第六季", "猫与龙",
                   "骸骨骑士大人异世界冒险中Ⅱ", "炒翻天",
                   "超超超超超喜欢你的100个女朋友 第三季",
                   "虽然我不是完美恶女～雏宫蝶鼠替换传～",
                   "暗芝居 第十七季", "鬼之花嫁", "成长秀～向日葵马戏团～"]

QIANGXIAN_KEYWORDS = ['TC', 'TS', '抢先', 'HC']
TC_LOCK_NAMES = {"起义", "猛攻"}

EMPTY_VALUES = {"未知", "内详", "暂无", "/", "-", "无"}
INVALID_EPISODE_NAMES = {"立即播放", "收藏", "播放", "下载"}
MAX_EPISODES = 30

# ============ 封面下载配置 ============
IMG_CONNECT_TIMEOUT = 10        # 建立连接超时
IMG_READ_TIMEOUT    = 20        # 「卡死」判定：连续多少秒一个字节都没收到（慢速但持续传输不会被判超时）
IMG_TOTAL_BUDGET    = 90        # 首轮：单张图片所有并发方案的总时限
IMG_FINAL_BUDGET    = 300       # 收尾补抓：单张图片的总时限
IMG_RESUME_MAX      = 8         # 单方案断点续传最多次数
IMAGE_PROXY_TEMPLATES = [       # 第三方图片代理（自带带宽与缓存，源站很慢时往往最快）
    "https://wsrv.nl/?url={url}",
    "https://images.weserv.nl/?url={url}",
]
IMG_DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}

# ============ 数据安全相关配置 ============
BACKUP_DIR = os.path.join(os.path.dirname(JSON_PATH), "backup")
BAK_FILE = JSON_PATH + ".bak"
REJECTED_FILE = JSON_PATH + ".rejected.json"
LOCK_FILE = JSON_PATH + ".lock"
MAX_BACKUPS = 20
ALLOW_SHRINK_RATIO = 0.90
SHRINK_GUARD_MIN_ITEMS = 20
ALLOW_FRESH_START = False

_BASELINE_TOTAL = 0
_LOAD_OK = False
_LAST_SIG = None          # 上次读/写后主文件的 (mtime_ns, size)，用于检测外部并发修改
_LOCK_FH = None

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 5.0

# ============== 浏览器 / Cloudflare 兜底配置 ==============
USER_DATA_DIR   = os.path.expanduser("~/.sxkljc_chrome_profile")
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9224          # 与 shangxidq(9222)、jjztq(9223) 错开，可同时运行
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False
FORCE_BROWSER   = False
BROWSER_FALLBACK = True
NAV_TIMEOUT_MS  = 60000
IMPERSONATE_CANDIDATES = ["chrome", "chrome124", "chrome120", "chrome110"]
DIRECT_BLOCK_LIMIT = 3

CHALLENGE_WAIT   = 600
CHALLENGE_GRACE  = 10
PASS_STABLE_HITS = 3
POLL_INTERVAL    = 1.5
SITE_READY_TIMEOUT = 8
PAGE_SETTLE      = 1.0
AUTO_CLICK_TURNSTILE   = True
AUTO_CLICK_FIRST_DELAY = 8
AUTO_CLICK_EVERY       = 15

CHALLENGE_MARKERS = (
    "Just a moment", "challenges.cloudflare.com/turnstile", "__cf_chl", "cf_chl_opt",
    "cf-challenge", "challenge-platform", "Checking your browser", "Verifying you are human",
    "Enable JavaScript and cookies to continue", "需要先验证您是真人", "正在验证您是否是真人",
)
SITE_MARKERS = ("vod-list", "vod-info", "ewave-page", "ewave-playlist", "head-wrapper")


# ============== 异常类型 ==============
class FetchError(Exception):
    pass

class NoRetryFetchError(FetchError):
    pass

class ConcurrentWriteError(Exception):
    """检测到 JSON 被其他进程修改，必须中止，避免覆盖别人的数据"""
    pass


# ==========================================================
#                    数据安全：锁 / 备份
# ==========================================================
def acquire_run_lock():
    global _LOCK_FH
    if fcntl is None:
        return
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    _LOCK_FH = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(">>> [锁] ⏳ 另一个爬虫正在写入 OVideos.json，等待其结束 ...")
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX)
    print(">>> [锁] 已获得数据文件独占锁 🔒")

def _file_sig(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None

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

def _backup_candidates() -> list:
    cands = [BAK_FILE]
    try:
        cands.extend(sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")), reverse=True))
    except Exception:
        pass
    return cands

def snapshot_backup(path: str):
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

def _empty_db():
    return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

def load_existing(path: str) -> dict:
    global _BASELINE_TOTAL, _LOAD_OK, _LAST_SIG
    main_exists = os.path.exists(path)
    main_size = os.path.getsize(path) if main_exists else -1

    if main_exists and main_size > 0:
        try:
            data = _read_json_strict(path)
            _BASELINE_TOTAL = count_items(data)
            _LOAD_OK = True
            _LAST_SIG = _file_sig(path)
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
            except Exception:
                continue
            _BASELINE_TOTAL = count_items(data)
            _LOAD_OK = True
            print(f"✅ [恢复] 已从备份恢复数据: {cand} ({_BASELINE_TOTAL} 条)")
            try:
                if main_size > 0:
                    corrupt = f"{path}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}"
                    shutil.copy2(path, corrupt)
                    print(f"   [留档] 损坏的主文件已另存为: {corrupt}")
            except Exception:
                pass
            save_json(data, force=True, quiet=False, backup_main=False)
            return data

        if not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print("脚本已终止：为防止用空数据覆盖你的历史库，本次不会写入任何内容。")
            print("!" * 70 + "\n")
            sys.exit(1)
    else:
        has_backup = any(os.path.exists(c) and os.path.getsize(c) > 0 for c in _backup_candidates())
        if has_backup and not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print(f"主数据文件不存在：{path}")
            print("但检测到备份文件存在，可能是路径错误或文件被误删。脚本已终止。")
            print(f"请从 {BAK_FILE} 或 {BACKUP_DIR} 手动恢复，或将 ALLOW_FRESH_START 改为 True。")
            print("!" * 70 + "\n")
            sys.exit(1)

    _BASELINE_TOTAL = 0
    _LOAD_OK = True
    _LAST_SIG = _file_sig(path)
    return _empty_db()

def save_json(data: dict, force: bool = False, quiet: bool = True, backup_main: bool = True) -> bool:
    global _BASELINE_TOTAL, _LAST_SIG
    if not _LOAD_OK:
        print("  [拒绝保存] 初始数据未成功加载，禁止写盘")
        return False
    if not isinstance(data, dict):
        return False

    if not force and _file_sig(JSON_PATH) != _LAST_SIG:
        try:
            with open(REJECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        raise ConcurrentWriteError(
            f"检测到 {JSON_PATH} 在本脚本运行期间被其他进程修改（可能有其他爬虫同时在跑）。"
            f"为避免覆盖对方数据，已中止。本次内存数据已另存到 {REJECTED_FILE}")

    total = count_items(data)
    if (not force) and _BASELINE_TOTAL >= SHRINK_GUARD_MIN_ITEMS and total < _BASELINE_TOTAL * ALLOW_SHRINK_RATIO:
        print(f"\n  ⛔ [拒绝保存] 条目数异常缩水：{_BASELINE_TOTAL} -> {total}")
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
        if backup_main and os.path.exists(JSON_PATH) and os.path.getsize(JSON_PATH) > 0:
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
        _LAST_SIG = _file_sig(JSON_PATH)
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


# ==========================================================
#                    CDP：启动 / 探测 Chrome
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
    return ('open -na "Google Chrome" --args \\\n'
            f'  --user-data-dir="{USER_DATA_DIR}" \\\n'
            f'  --remote-debugging-port={CDP_PORT} \\\n'
            f'  {DOMAIN}/')

def launch_chrome_for_cdp(open_url=True):
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    if cdp_alive():
        print(f">>> [CDP] 端口 {CDP_PORT} 已在监听，无需重复启动。")
        return True
    print(">>> [CDP] 正在启动 Chrome（若已有 Chrome 在运行，请先 ⌘Q 完全退出！）")
    args = [f"--user-data-dir={USER_DATA_DIR}", f"--remote-debugging-port={CDP_PORT}",
            "--no-first-run", "--no-default-browser-check"]
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
            print(f">>> [CDP] Chrome 已就绪（端口 {CDP_PORT}）。如有验证请手动通过，然后执行：")
            print(f"        python {SCRIPT_NAME} cdp")
            return True
    print("!!! 等待调试端口超时。请先执行：osascript -e 'quit app \"Google Chrome\"' 再重试。")
    print("    或手动执行：\n" + cdp_launch_command())
    return False


# ==========================================================
#                   真实浏览器（兜底层）
# ==========================================================
_STATE_JS = """
() => {
  const q = s => !!document.querySelector(s);
  const hasSite = q('div.vod-list') || q('div.vod-info') || q('.ewave-page') ||
                  q('.ewave-playlist-content') || q('.head-wrapper') ||
                  q('a[href*="/voddetail/"]');
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
    if not html:
        return True
    if any(m in html for m in SITE_MARKERS):
        return False
    if any(m in html[:10000] for m in CHALLENGE_MARKERS):
        return True
    return len(html) < 500


class BrowserHelper:
    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None
        self._browser = None
        self.ua = ""

    @property
    def started(self):
        return self._ctx is not None

    def start(self):
        if self._ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise FetchError("需要浏览器兜底但未安装 playwright：pip install playwright && playwright install chromium")

        self._pw = sync_playwright().start()
        if USE_CDP:
            if not cdp_alive():
                print(f"\n!!! 没有检测到可用的 Chrome 调试端口 {CDP_ENDPOINT}")
                print(f"请先执行：python {SCRIPT_NAME} open   或手动执行：")
                print(cdp_launch_command())
                raise FetchError("CDP 端口不可用")
            print(f">>> [CDP] 正在附着到已运行的 Chrome：{CDP_ENDPOINT}")
            self._browser = self._pw.chromium.connect_over_cdp(CDP_ENDPOINT)
            self._ctx = (self._browser.contexts[0]
                         if self._browser.contexts else self._browser.new_context())
        else:
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            print(f">>> [浏览器] 启动真实 Chrome（profile: {USER_DATA_DIR}）")
            kw = dict(
                user_data_dir=USER_DATA_DIR, headless=HEADLESS, locale="zh-CN",
                timezone_id="Asia/Shanghai", viewport={"width": 1360, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                      "--no-default-browser-check", "--start-maximized"],
                ignore_default_args=["--enable-automation"],
            )
            if BROWSER_CHANNEL:
                kw["channel"] = BROWSER_CHANNEL
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**kw)
            except Exception as e:
                print(f">>> [浏览器] 用系统 Chrome 启动失败({e})，改用 Playwright 自带 Chromium")
                kw.pop("channel", None)
                self._ctx = self._pw.chromium.launch_persistent_context(**kw)
            try:
                self._ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except Exception:
                pass

        self._ctx.set_default_timeout(NAV_TIMEOUT_MS)
        self._ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self._page = self._pick_page()
        try:
            self.ua = self._page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            self.ua = ""

    def _pick_page(self):
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        for p in pages:
            try:
                if SITE_HOST in (p.url or ""):
                    return p
            except Exception:
                continue
        return pages[0] if pages else self._ctx.new_page()

    def cookies(self):
        if not self._ctx:
            return {}
        try:
            return {c["name"]: c["value"] for c in self._ctx.cookies(DOMAIN)}
        except Exception:
            return {}

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
            cf_frame = any("challenges.cloudflare.com" in (f.url or "") for f in self._page.frames)
        except Exception:
            cf_frame = False
        if info.get("hasSite"):
            return "site", html
        if info.get("hasChl") or info.get("titleChl") or cf_frame:
            return "challenge", html
        return "unknown", html

    def _notify_challenge(self, url):
        print("\a", end="", flush=True)
        print("\n" + "=" * 72)
        print("  ⚠️  检测到人机验证页面，脚本已暂停")
        print("  👉  请切到 Chrome 窗口完成验证")
        print(f"  ⏳  至少等 {CHALLENGE_GRACE} 秒，最长等 {CHALLENGE_WAIT} 秒。URL: {url}")
        if not USE_CDP:
            print("  💡 反复过不去时：osascript -e 'quit app \"Google Chrome\"' → "
                  f"python {SCRIPT_NAME} open → 手动过验证 → python {SCRIPT_NAME} cdp")
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
                for sel in ("input[type=checkbox]", "#challenge-stage input[type=checkbox]",
                            "label.ctp-checkbox-label", "#cf-stage input"):
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
        challenge_seen, grace_until, next_click_at, last_tip, stable = False, 0.0, 0.0, 0.0, 0
        html = ""
        while True:
            state, html = self._page_state()
            if state == "site" and not (challenge_seen and time.time() < grace_until):
                stable += 1
                if stable >= (PASS_STABLE_HITS if challenge_seen else 1):
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
                    return html
            else:
                stable = 0

            if state == "challenge":
                if not challenge_seen:
                    challenge_seen = True
                    self._notify_challenge(url)
                    grace_until = time.time() + CHALLENGE_GRACE
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
                    raise FetchError(f"等待人机验证超时: {url}")
            elif time.time() > soft_deadline:
                return html
            time.sleep(POLL_INTERVAL)

    def get_html(self, url):
        if not self._started:
            self.start()
        if FORCE_BROWSER or self._prefer_browser:
            return self.browser.get_html(url)
        try:
            r = self._direct_get(url, referer=DOMAIN + "/")
        except Exception as e:
            # 超时或连接异常：丢弃可能已失效的连接池，改走浏览器
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
            if BROWSER_FALLBACK:
                print(f"    [直连] 请求异常，切换真实浏览器: {e}")
                return self._browser_html(url)
            raise FetchError(f"网络请求异常: {e}")

    def get_bytes(self, url, timeout=None, referer=None):
        self.start()
        r = self._ctx.request.get(url, timeout=(timeout or REQUEST_TIMEOUT) * 1000,
                                  headers={"Referer": referer or (DOMAIN + "/")})
        if r.status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status >= 400:
            raise FetchError(f"HTTP {r.status}: {url}")
        return r.body()


# ==========================================================
#              抓取层：curl_cffi 直连 + 浏览器兜底
# ==========================================================
def decode_html(content: bytes, content_type: str = "") -> str:
    if not content:
        return ""
    enc = None
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w\-]+)', content[:4096], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    cands = []
    if enc:
        enc = enc.lower()
        if enc in ("gb2312", "gbk", "gb_2312-80"):
            enc = "gb18030"
        cands.append(enc)
    cands += ["utf-8", "gb18030"]
    for e in cands:
        try:
            return content.decode(e)
        except Exception:
            continue
    return content.decode("utf-8", "replace")


class Fetcher:
    def __init__(self):
        self.browser = BrowserHelper()
        self._session = None
        self._cookies = {}
        self._started = False
        self._prefer_browser = False
        self._blocked_after_sync = 0

    def _reset_session(self):
        try:
            if self._session:
                self._session.close()
        except Exception:
            pass
        self._session = None

    def _get_session(self):
        if self._session is not None:
            return self._session
        last_err = None
        for imp in IMPERSONATE_CANDIDATES:
            try:
                s = cffi.Session(impersonate=imp)
                s.headers.update({
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                })
                print(f">>> [直连] curl_cffi 使用 TLS 指纹: {imp}")
                self._session = s
                return s
            except Exception as e:
                last_err = e
        raise FetchError(f"无法创建 curl_cffi Session: {last_err}")

    def sync_from_browser(self):
        if not self.browser.started:
            return
        self._cookies = self.browser.cookies()
        s = self._get_session()
        if self.browser.ua:
            s.headers["User-Agent"] = self.browser.ua
        print(f">>> [同步] 已从浏览器同步 {len(self._cookies)} 个 cookie 到直连通道"
              f"（cf_clearance: {'有 ✅' if 'cf_clearance' in self._cookies else '无'}）")

    def start(self):
        if self._started:
            return
        self._started = True
        if FORCE_BROWSER or USE_CDP:
            self.browser.start()
            self.sync_from_browser()
        print(">>> [预热] 访问首页检查连通性 ...")
        try:
            self.get_html(DOMAIN + "/")
            print(">>> [预热] 站点可正常访问 ✅")
        except Exception as e:
            print(f">>> [预热] 异常（不致命，继续）：{e}")

    def close(self):
        self.browser.close()
        try:
            if self._session:
                self._session.close()
        except Exception:
            pass
        self._session = None

    def _direct_get(self, url, referer=None):
        s = self._get_session()
        headers = {"Referer": referer} if referer else None
        cookies = self._cookies if (self._cookies and SITE_HOST in url) else None
        return s.get(url, headers=headers, cookies=cookies,
                     timeout=REQUEST_TIMEOUT, allow_redirects=True)

    def _browser_html(self, url):
        html = self.browser.get_html(url)
        self.sync_from_browser()
        return html

    def get_html(self, url):
        if not self._started:
            self.start()
        if FORCE_BROWSER or self._prefer_browser:
            return self.browser.get_html(url)
        try:
            r = self._direct_get(url, referer=DOMAIN + "/")
        except Exception as e:
            self._reset_session()          # 销毁卡住的连接池，下一次重试是全新连接
            raise FetchError(f"网络请求异常: {e}")
        if r.status_code == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status_code == 429:
            raise FetchError(f"HTTP 429 请求过快: {url}")
        html = decode_html(r.content, r.headers.get("content-type", ""))
        blocked = r.status_code in (403, 503) or _looks_like_challenge(html)
        if not blocked:
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}: {url}")
            if self.browser.started:
                self._blocked_after_sync = 0
            return html

        if not BROWSER_FALLBACK:
            raise FetchError(f"疑似拦截/挑战页 (HTTP {r.status_code})，已禁用浏览器兜底: {url}")
        if self.browser.started:
            self._blocked_after_sync += 1
            if self._blocked_after_sync >= DIRECT_BLOCK_LIMIT:
                print("    [直连] 同步 cookie 后仍多次被拦，后续页面改为优先走浏览器")
                self._prefer_browser = True
        print(f"    [直连] 命中拦截/挑战页 (HTTP {r.status_code})，切换真实浏览器处理 ...")
        return self._browser_html(url)

    def get_bytes(self, url):
        if not self._started:
            self.start()
        if FORCE_BROWSER or self._prefer_browser:
            return self.browser.get_bytes(url)
        try:
            r = self._direct_get(url, referer=DOMAIN + "/")
        except Exception as e:
            if self.browser.started:
                return self.browser.get_bytes(url)
            raise FetchError(f"网络请求异常: {e}")
        if r.status_code == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status_code >= 400:
            if self.browser.started:
                return self.browser.get_bytes(url)
            raise FetchError(f"HTTP {r.status_code}: {url}")
        return r.content


_fetcher = Fetcher()
atexit.register(_fetcher.close)


def fetch(url, is_binary=False):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _fetcher.get_bytes(url) if is_binary else _fetcher.get_html(url)
        except NoRetryFetchError:
            raise
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                if "验证" in str(e) or "Cloudflare" in str(e) or "429" in str(e):
                    wait = max(wait, 15)
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    raise last_err if last_err else FetchError(f"请求失败: {url}")

def polite_sleep():
    time.sleep(SLEEP_BETWEEN * random.uniform(0.8, 1.5))


# ============== 通用工具函数 ==============
def clean_url(u):
    if not u:
        return ""
    return re.sub(r"\s+", "", str(u)).strip("'\"")

def has_tc_keyword(text: str) -> bool:
    if not text:
        return False
    upper = str(text).upper()
    return any(kw.upper() in upper for kw in QIANGXIAN_KEYWORDS)

def is_in_tc_lock_list(name: str) -> bool:
    if not name or not TC_LOCK_NAMES:
        return False
    clean = re.sub(r"\s+", "", str(name)).lower()
    return any(re.sub(r"\s+", "", str(x)).lower() == clean for x in TC_LOCK_NAMES)

def _norm_space(s):
    return re.sub(r"\s+", "", s or "")

def is_blacklisted_name(name):
    n = _norm_space(name)
    return any(_norm_space(b) == n for b in BLACKLIST_NAMES)

def is_whitelisted_name(name):
    n = _norm_space(name)
    return any(_norm_space(w) == n for w in WHITELIST_NAMES)

def is_garbled(value):
    if not value:
        return False
    v = str(value)
    if "\ufffd" in v:
        return True
    stripped = re.sub(r"[\s/·,，、|\-]", "", v)
    if not stripped:
        return False
    return bool(re.fullmatch(r"[?？]+", stripped))

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
    s = s.replace("・", "·").replace("‧", "·")
    s = s.replace("\xa0", " ").replace("\u3000", " ")
    s = re.sub(r"[，；;]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·•")
    return s

def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES or is_garbled(v):
        return ""
    return v

def num_to_chinese(num_str):
    try:
        num = int(num_str)
    except ValueError:
        return num_str
    d = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    if num < 10:
        return d[num]
    if num == 10:
        return "十"
    if num < 20:
        return f"十{d[num % 10]}"
    if num < 100:
        return f"{d[num // 10]}十" + (d[num % 10] if num % 10 else "")
    return num_str

def split_name_info(raw_title):
    raw_title = (raw_title or "").strip()
    base_name, base_info = raw_title, ""
    m = re.search(r"^(.*?)[\[［](.*?)[\]］]$", raw_title)
    if m:
        base_name, base_info = m.group(1).strip(), m.group(2).strip()
    else:
        m = re.search(r"^(.*?)\s+((?:第[0-9一二三四五六七八九十百\-]+季)(?:全)?)$", raw_title)
        if m:
            base_name, base_info = m.group(1).strip(), m.group(2).strip()

    def rep(mm):
        return f"{mm.group(1)}{num_to_chinese(mm.group(2))}{mm.group(3)}"
    base_name = re.sub(r"(第)(\d+)(季)", rep, base_name)
    base_info = re.sub(r"(第)(\d+)(季)", rep, base_info)

    if not base_info:
        return base_name, ""
    if base_info == "全集":
        return base_name, "全集"
    if base_info.endswith("季全"):
        if re.search(r"[\-\d~至]", base_info):
            return base_name, base_info
        return f"{base_name} {base_info[:-1]}", base_info
    if base_info.endswith("季"):
        return f"{base_name} {base_info}", ""
    return base_name, base_info

def get_episode_unit(group="", episodes=None, info_text=""):
    if episodes:
        names_str = " ".join(str(k) for k in episodes.keys())
        if "期" in names_str:
            return "期"
        if "话" in names_str or "話" in names_str:
            return "话"
        if "集" in names_str:
            return "集"
    if info_text:
        if "期" in info_text:
            return "期"
        if "话" in info_text or "話" in info_text:
            return "话"
        if "集" in info_text:
            return "集"
    return "期" if group == "Show" else "集"

def make_episode_info(num, unit="集"):
    return f"更新至第{num}{unit}"

def get_max_episode_number(episodes):
    if not episodes:
        return 0
    se = []
    for n in episodes.keys():
        m = re.search(r'S(\d+)E(\d+)', str(n), re.IGNORECASE)
        if m:
            se.append((int(m.group(1)), int(m.group(2))))
    if se:
        ms = max(s for s, _ in se)
        return max(e for s, e in se if s == ms)
    sp = []
    for n in episodes.keys():
        m = re.search(r'第\s*(\d+)\s*季.*?第\s*(\d+)\s*[集期话話]', str(n))
        if m:
            sp.append((int(m.group(1)), int(m.group(2))))
    if sp:
        ms = max(s for s, _ in sp)
        return max(e for s, e in sp if s == ms)
    mx = 0
    for n in episodes.keys():
        m = (re.search(r'(\d+)\s*[集期话話]', str(n)) or re.search(r'第\s*(\d+)', str(n))
             or re.search(r'(\d+)', str(n)))
        if m:
            mx = max(mx, int(m.group(1)))
    return mx

def get_effective_episode_count(episodes, group=""):
    if not episodes:
        return 0
    if group == "Movie":
        return len(episodes)
    num = get_max_episode_number(episodes)
    if num > 500:
        has_real = any(re.search(r'(\d+)\s*[集期话話]|S\d+E\d+|第\s*(\d+)', str(n)) for n in episodes.keys())
        if not has_real:
            return len(episodes)
    return num if num > 0 else len(episodes)

def is_valid_episode_name(name):
    if not name or name in INVALID_EPISODE_NAMES:
        return False
    return not re.match(r"^更新[至到]", name)

def filter_episodes(eps):
    return {k: v for k, v in eps.items() if is_valid_episode_name(k)}

def extract_year(*candidates):
    for c in candidates:
        if not c:
            continue
        m = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(c))
        if m:
            return m.group(0)
    return ""

def normalize_url(u):
    if not u:
        return ""
    u = str(u).strip()
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    u = re.sub(r"^www\.", "", u, flags=re.IGNORECASE)
    return u.rstrip("/")

def _is_site_url(u):
    try:
        host = urlparse(str(u)).netloc.lower().split(":")[0]
    except Exception:
        return False
    return host == SITE_HOST or host.endswith("." + SITE_HOST)


# ============== 本站线路块操作 ==============
def is_site_playlist(pl):
    """本站线路：名称为 PLAYLIST_NAME，或其播放链接属于本站域名（兼容旧数据）"""
    if not isinstance(pl, dict):
        return False
    if (pl.get("name") or "").strip().lower() == PLAYLIST_NAME.lower():
        return True
    eps = pl.get("episodes") or {}
    if not isinstance(eps, dict):
        return False
    return any(_is_site_url(v) for v in eps.values())

def has_own_channel(item):
    """该作品的 playlist 中是否已存在本站渠道"""
    return any(is_site_playlist(pl) for pl in (item.get("playlist") or []))

def site_playlist_indices(playlist):
    return [i for i, pl in enumerate(playlist) if is_site_playlist(pl)]

def remove_indices(playlist, indices):
    for i in sorted(indices, reverse=True):
        playlist.pop(i)

def playlist_signature(pls):
    return [(pl.get("name"), list((pl.get("episodes") or {}).items())) for pl in pls]

def total_episode_count(pls):
    return sum(len(pl.get("episodes") or {}) for pl in pls)

def _url_keys_sorted(existing):
    return sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

def has_site_url_key(existing, sub_url):
    for k in _url_keys_sorted(existing):
        v = existing.get(k, "") or ""
        if SITE_KEY in v or normalize_url(v) == normalize_url(sub_url):
            return True
    return False

def _ensure_site_url(existing, sub_url, force_new=False):
    url_keys = _url_keys_sorted(existing)
    if not force_new:
        for k in url_keys:
            v = existing.get(k, "") or ""
            if SITE_KEY in v or normalize_url(v) == normalize_url(sub_url):
                return k
    max_num = 0
    for k in url_keys:
        m = re.match(r"^url(\d+)$", k)
        if m:
            max_num = max(max_num, int(m.group(1)))
    new_key = f"url{max_num + 1}"
    last = url_keys[-1] if url_keys else None
    ordered, inserted = {}, False
    for k, v in existing.items():
        ordered[k] = v
        if k == last:
            ordered[new_key] = sub_url
            inserted = True
    if not inserted:
        ordered[new_key] = sub_url
    existing.clear()
    existing.update(ordered)
    return new_key

def resolve_insert_position_with_gdefud(playlist, new_episodes, default_insert_pos=None, group="", log=print):
    target = len(playlist) if default_insert_pos is None else max(0, min(default_insert_pos, len(playlist)))
    g_idx = next((i for i, pl in enumerate(playlist)
                  if pl.get("name", "").strip().lower() == TARGET_COMPARE_CHANNEL.lower()), None)
    if g_idx is None:
        return target
    cnt_g = get_effective_episode_count(playlist[g_idx].get("episodes", {}), group=group)
    cnt_s = get_effective_episode_count(new_episodes, group=group)
    if cnt_s >= cnt_g:
        if target > g_idx:
            log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) >= {TARGET_COMPARE_CHANNEL}({cnt_g})，"
                f"插入位置由第 {target + 1} 位提前至第 {g_idx + 1} 位")
            target = g_idx
        else:
            log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) >= {TARGET_COMPARE_CHANNEL}({cnt_g})，"
                f"目标位置第 {target + 1} 位已在其之前，符合规则")
    else:
        log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) < {TARGET_COMPARE_CHANNEL}({cnt_g})，保持第 {target + 1} 位")
    return target

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
    score = existing.setdefault("评分", {"豆瓣": "", "IMDB": ""})
    if not isinstance(score, dict):
        score = existing["评分"] = {"豆瓣": "", "IMDB": ""}
    new_score = (rec.get("评分") or {})
    for k in ("豆瓣", "IMDB"):
        if not score.get(k) and new_score.get(k):
            score[k] = new_score[k]
            changed = True
            log(f"      [字段更新] 补充评分「{k}」: {new_score[k]}")
    return changed

def region_blocked(region, filter_regions):
    region = (region or "").strip()
    if not region:
        return False
    if region in filter_regions:
        return True
    tokens = [t for t in re.split(r"[,，/、|\s]+", region) if t]
    return bool(tokens) and all(t in filter_regions for t in tokens)


# ==========================================================
#        图片下载：多方案并发竞速 + 断点续传 + 完整性校验
# ==========================================================
def safe_filename(url):
    return os.path.basename(unquote(url.split("?")[0].split("#")[0]))

def _cover_filename(img_url):
    fn = safe_filename(img_url)
    ext = os.path.splitext(fn)[1].lower()
    if fn and ext in ALLOWED_IMG_EXT:
        return fn
    h = hashlib.md5(img_url.encode("utf-8")).hexdigest()[:16]
    return f"{SITE_KEY}_{h}{ext if ext in ALLOWED_IMG_EXT else '.jpg'}"

def _looks_like_image(b: bytes) -> bool:
    if not b or len(b) < 512:
        return False
    return (b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n"
            or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")
            or b[:6] in (b"GIF87a", b"GIF89a")
            or b[:2] == b"BM"
            or b[4:12] in (b"ftypavif", b"ftypheic", b"ftypmif1"))

def _image_truncated(b: bytes) -> bool:
    """JPEG 必须有 EOI(FFD9)，PNG 必须有 IEND，否则视为半截图"""
    if b[:3] == b"\xff\xd8\xff":
        return b"\xff\xd9" not in b[-4096:]
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return b"IEND" not in b[-64:]
    return False

def fix_img_url(img, base_url):
    """处理 MacCMS 的 mac:// 前缀、协议相对地址、相对路径"""
    img = clean_url(img)
    if not img or img.startswith("data:"):
        return ""
    if img.lower().startswith("mac://"):
        img = "https://" + img[6:]
    return urljoin(base_url, img)

_PLACEHOLDER_RE = re.compile(r"(load(ing)?|lazy|blank|nopic|placeholder)\.(gif|png|jpe?g|svg|webp)", re.I)

def pick_img_attr(tag):
    if not tag:
        return ""
    for attr in ("data-original", "data-src", "data-background", "src"):
        v = clean_url(tag.get(attr) or "")
        if v and not v.startswith("data:") and not _PLACEHOLDER_RE.search(v):
            return v
    m = re.search(r"url\(\s*['\"]?(.*?)['\"]?\s*\)", tag.get("style", "") or "")
    if m and not _PLACEHOLDER_RE.search(m.group(1)):
        return clean_url(m.group(1))
    return ""

_IMG_SESSION = None
_IMG_SESSION_LOCK = threading.Lock()

def _img_session():
    global _IMG_SESSION
    with _IMG_SESSION_LOCK:
        if _IMG_SESSION is None:
            s = requests.Session()
            ad = HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
            s.mount("http://", ad)
            s.mount("https://", ad)
            _IMG_SESSION = s
        return _IMG_SESSION

def _img_headers(referer=None):
    h = {
        "User-Agent": _fetcher.browser.ua or IMG_DEFAULT_UA,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",          # 图片不需要压缩，且保证断点续传的字节偏移准确
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    if referer:
        h["Referer"] = referer
    return h

def _short_err(e):
    s = str(e).replace("\n", " ")
    s = s.split(" See https://curl")[0]
    return (s[:160] + "…") if len(s) > 160 else s

def _stream_download(url, referer, deadline, cancel=None):
    """
    流式下载：
    - 超时按「连续 IMG_READ_TIMEOUT 秒无数据」判定，慢速但持续的传输不会被打断
    - 连接中断后用 Range 从断点续传；服务器不支持 Range 时自动从头再来
    """
    s = _img_session()
    base_headers = _img_headers(referer)
    buf = bytearray()
    total = None
    resumes = 0
    verify = True
    while True:
        if cancel is not None and cancel.is_set():
            raise FetchError("已被其他方案抢先完成")
        remaining = deadline - time.time()
        if remaining <= 0:
            raise FetchError(f"超出时限（已收 {len(buf)}/{total or '?'} 字节）")
        h = dict(base_headers)
        if buf:
            h["Range"] = f"bytes={len(buf)}-"
        try:
            with s.get(url, headers=h, stream=True, verify=verify, allow_redirects=True,
                       timeout=(IMG_CONNECT_TIMEOUT, max(3.0, min(IMG_READ_TIMEOUT, remaining)))) as r:
                if r.status_code == 416 and buf and total and len(buf) >= total:
                    return bytes(buf)
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code}")
                if "text/html" in (r.headers.get("Content-Type") or "").lower():
                    raise FetchError("返回的是网页而非图片（疑似防盗链拦截）")
                if r.status_code == 206:
                    m = re.search(r"/(\d+)\s*$", r.headers.get("Content-Range", "") or "")
                    if m:
                        total = int(m.group(1))
                else:
                    if buf:            # 服务器忽略了 Range，返回整个文件 → 从头再来
                        buf.clear()
                        total = None
                    cl = r.headers.get("Content-Length") or ""
                    ce = (r.headers.get("Content-Encoding") or "identity").lower()
                    if cl.isdigit() and ce in ("", "identity"):
                        total = int(cl)
                for chunk in r.iter_content(64 * 1024):
                    if chunk:
                        buf.extend(chunk)
                    if cancel is not None and cancel.is_set():
                        raise FetchError("已被其他方案抢先完成")
                    if time.time() > deadline:
                        raise FetchError(f"超出时限（已收 {len(buf)}/{total or '?'} 字节）")
            if total is None or len(buf) >= total:
                return bytes(buf)
            raise requests.exceptions.ChunkedEncodingError(f"连接提前结束（{len(buf)}/{total}）")
        except requests.exceptions.SSLError:
            if verify:
                verify = False
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            resumes += 1
            if resumes > IMG_RESUME_MAX or time.time() >= deadline:
                raise FetchError(f"{type(e).__name__}（已收 {len(buf)}/{total or '?'} 字节，续传 {resumes - 1} 次）")
            time.sleep(1.0)

def _cffi_download(url, referer, deadline):
    """curl_cffi 浏览器 TLS 指纹（应对按指纹拦截的 CDN）"""
    h = _img_headers(referer)
    timeout = max(5.0, deadline - time.time())
    last = None
    for imp in IMPERSONATE_CANDIDATES:
        try:
            r = cffi.get(url, headers=h, impersonate=imp, timeout=timeout, allow_redirects=True)
            break
        except Exception as e:
            last = e
            if "impersonat" in str(e).lower():
                continue
            raise
    else:
        raise FetchError(f"curl_cffi 不可用: {last}")
    if r.status_code >= 400:
        raise FetchError(f"HTTP {r.status_code}")
    content = r.content
    cl = r.headers.get("Content-Length") or ""
    ce = (r.headers.get("Content-Encoding") or "identity").lower()
    if cl.isdigit() and ce in ("", "identity") and len(content) < int(cl):
        raise FetchError(f"数据不完整（{len(content)}/{cl}）")
    return content

def _validated(fn):
    b = fn()
    if not _looks_like_image(b):
        raise FetchError(f"返回内容不是有效图片（{len(b or b'')} 字节，可能被拦截）")
    if _image_truncated(b):
        raise FetchError(f"图片数据不完整（{len(b)} 字节）")
    return b

def download_image_bytes(img_url, budget=IMG_TOTAL_BUDGET):
    """多方案并发竞速，返回 (bytes, 方案名)；全部失败返回 (None, "")"""
    deadline = time.time() + budget
    cancel = threading.Event()
    ref = DOMAIN + "/"
    alt = ""
    if img_url.startswith("https://"):
        alt = "http://" + img_url[8:]
    elif img_url.startswith("http://"):
        alt = "https://" + img_url[7:]

    strategies = [
        ("直连+Referer",  lambda: _stream_download(img_url, ref, deadline, cancel)),
        ("直连无Referer", lambda: _stream_download(img_url, None, deadline, cancel)),
        ("curl_cffi指纹", lambda: _cffi_download(img_url, ref, deadline)),
    ]
    if alt:
        strategies.append((f"协议切换({alt.split(':')[0]})",
                           lambda: _stream_download(alt, None, deadline, cancel)))
    for tpl in IMAGE_PROXY_TEMPLATES:
        purl = tpl.format(url=quote(img_url, safe=""))
        strategies.append((f"图片代理 {urlparse(tpl).netloc}",
                           lambda purl=purl: _stream_download(purl, None, deadline, cancel)))

    errors = []
    pool = ThreadPoolExecutor(max_workers=len(strategies), thread_name_prefix="img")
    futs = {pool.submit(_validated, fn): label for label, fn in strategies}
    try:
        for fut in as_completed(futs, timeout=max(1.0, deadline - time.time() + 5)):
            label = futs[fut]
            try:
                b = fut.result()
                cancel.set()
                return b, label
            except Exception as e:
                errors.append(f"{label}: {_short_err(e)}")
    except FuturesTimeout:
        errors.append("整体超时")
    finally:
        cancel.set()
        pool.shutdown(wait=False, cancel_futures=True)

    # 并发方案都失败时，浏览器已启动则再用浏览器通道试一次（Playwright 同步 API 不能跨线程，放主线程）
    if _fetcher.browser.started and time.time() < deadline:
        try:
            b = _validated(lambda: _fetcher.browser.get_bytes(
                img_url, timeout=max(10, int(deadline - time.time())), referer=ref))
            return b, "浏览器通道"
        except Exception as e:
            errors.append(f"浏览器通道: {_short_err(e)}")

    for msg in errors:
        print(f"    [图片] ✗ {msg}")
    return None, ""

def download_and_localize_image(img_url, budget=IMG_TOTAL_BUDGET):
    img_url = clean_url(img_url)
    if not img_url or not img_url.lower().startswith(("http://", "https://")):
        return ""
    fn = _cover_filename(img_url)
    local_path = os.path.join(IMG_DIR, fn)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return fn
    t0 = time.time()
    content, via = download_image_bytes(img_url, budget)
    if not content:
        print(f"  [图片下载失败] {img_url}（所有方案均失败，稍后会再补抓）")
        return ""
    try:
        os.makedirs(IMG_DIR, exist_ok=True)
        tmp = local_path + ".part"
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, local_path)
    except Exception as e:
        print(f"  [图片写盘失败] {local_path}: {e}")
        return ""
    print(f"  [图片] 已下载 -> {fn}（{len(content)/1024:.0f} KB，{time.time()-t0:.1f}s，via {via}）")
    return fn

# —— 首轮失败的封面进入待补队列，收尾时放宽时限再抓一次 ——
_PENDING_COVERS = []

def localize_cover(item, img_url):
    fn = download_and_localize_image(img_url)
    if fn:
        return fn
    if img_url and not any(it is item for it, _ in _PENDING_COVERS):
        _PENDING_COVERS.append((item, img_url))
    return ""

def retry_pending_covers(data):
    pend = [(it, u) for it, u in _PENDING_COVERS if not it.get("image")]
    _PENDING_COVERS.clear()
    if not pend:
        return
    print(f"\n[封面补抓] {len(pend)} 张封面首轮下载失败，放宽时限（{IMG_FINAL_BUDGET}s/张）再试 ...")
    ok = 0
    for it, u in pend:
        print(f"  - {it.get('name')}  <- {u}")
        fn = download_and_localize_image(u, budget=IMG_FINAL_BUDGET)
        if fn:
            it["image"] = fn
            save_json(data)
            ok += 1
        else:
            print(f"    ✗ 仍失败，下次运行或执行 `python {SCRIPT_NAME} backfill` 时会再补")
    print(f"[封面补抓] 完成：{ok}/{len(pend)} 成功")


# ============== 列表页解析 ==============
def _main_list_container(soup):
    """优先选带分页条的 vod-list，避免把侧栏/推荐位混进来"""
    for box in soup.select("div.vod-list"):
        if box.select_one("ul.ewave-page"):
            return box
    boxes = soup.select("div.vod-list")
    if boxes:
        return max(boxes, key=lambda b: len(b.select("a[href*='/voddetail/']")))
    return soup

def parse_list_items(soup, base_url):
    out = []
    box = _main_list_container(soup)
    lis = box.select("ul.row > li") or box.select("li")
    for li in lis:
        pic_a = li.select_one("div.pic a[href]")
        name_a = li.select_one("div.name h3 a[href]") or li.select_one("div.name a[href]")
        a = name_a or pic_a
        if not a:
            continue
        href = (a.get("href") or "").strip() or ((pic_a.get("href") or "").strip() if pic_a else "")
        if not href:
            continue
        full = urljoin(base_url, href)
        if DETAIL_URL_PATTERN and not DETAIL_URL_PATTERN.search(urlparse(full).path):
            continue
        title = normalize_text((name_a.get("title") if name_a else "")
                               or (name_a.get_text(" ", strip=True) if name_a else "")
                               or (pic_a.get("title") if pic_a else "") or "")
        if not title:
            continue

        st = li.select_one("p.item-status") or li.select_one(".item-status")
        info = normalize_text(st.get_text(" ", strip=True)) if st else ""

        img = ""
        if pic_a:
            img = pick_img_attr(pic_a.select_one(".img-wrapper") or pic_a.select_one("[data-original]")) \
                  or pick_img_attr(pic_a.find("img"))
        img = fix_img_url(img, base_url)

        name, _ = split_name_info(title)
        out.append((name or title, info, full, img))
    return out

def find_next_page(soup, cur_url):
    pager = soup.select_one("ul.ewave-page") or soup
    cands = [a for a in pager.select("a[href]")
             if normalize_text(a.get_text(strip=True)) in ("下一页", "下页", "›", "»", ">")]
    if not cands:
        cur = None
        for li in pager.select("li.active"):
            m = re.search(r"\d+", li.get_text(" ", strip=True))
            if m:
                cur = int(m.group())
                break
        if cur is not None:
            cands = [a for a in pager.select("a[href]")
                     if normalize_text(a.get_text(strip=True)) == str(cur + 1)][:1]
    for a in cands:
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript", "#")):
            continue
        nxt = urljoin(cur_url, href)
        if normalize_url(nxt) != normalize_url(cur_url):
            return nxt
    return None

def collect_list_items(list_url):
    items, seen, visited = [], set(), set()
    url = list_url
    for page_no in range(1, max(1, MAX_LIST_PAGES) + 1):
        if normalize_url(url) in visited:
            break
        visited.add(normalize_url(url))
        html = fetch(url)
        soup = BeautifulSoup(html, "lxml")
        if page_no == 1:
            m = re.search(r"ewave-total['\"]?\s*\)\s*\.text\(\s*(\d+)\s*\)", html)
            if m:
                print(f"  [列表] 站点显示该分类共 {m.group(1)} 部")
        page_items = parse_list_items(soup, url)
        new = 0
        for it in page_items:
            key = normalize_url(it[2])
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
            new += 1
        print(f"  [列表] 第 {page_no} 页解析到 {len(page_items)} 条（去重后新增 {new}）")
        if not page_items:
            print("  [列表] 本页没有解析到任何条目（页面结构可能变化或被拦截），停止翻页")
            break
        if page_no >= MAX_LIST_PAGES:
            break
        nxt = find_next_page(soup, url)
        if not nxt:
            break
        url = nxt
        polite_sleep()
    return items


# ============== 详情页解析 ==============
FIELD_LABELS = [
    ("导演",    r"导\s*演"),
    ("编剧",    r"编\s*剧"),
    ("主演",    r"主\s*演|演\s*员"),
    ("类型",    r"分\s*类|类\s*型|类\s*别"),
    ("地区",    r"地\s*区|国\s*家"),
    ("year",    r"年\s*份|年\s*代"),
    ("release", r"上\s*映|首\s*播|首\s*映|发\s*行"),
    ("status",  r"状\s*态|备\s*注|连\s*载"),
    ("alias",   r"又\s*名|别\s*名"),
    ("douban",  r"豆\s*瓣"),
]
LIST_FIELDS = ("类型", "主演", "导演", "编剧")

def _detect_label(label):
    for key, pat in FIELD_LABELS:
        if re.search(pat, label or ""):
            return key
    return None

def _split_people(v):
    parts = re.split(r"[,，/、|]+|\s{2,}", v or "")
    return [x for x in (_clean_val(p) for p in parts) if x]

def _norm_genre(g):
    g2 = re.sub(r"(电影|片)$", "", g or "").strip()
    return g2 or g

def parse_title(soup, default_name):
    h = (soup.select_one(".vod-info .info h3 a") or soup.select_one(".vod-info .info h3")
         or soup.select_one(".vod-info h1") or soup.select_one(".vod-info h3"))
    t = ""
    if h:
        t = normalize_text(h.get("title") or h.get_text(" ", strip=True))
    if not t:
        og = soup.find("meta", attrs={"property": "og:title"})
        t = normalize_text(og.get("content", "")) if og else ""
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t

def parse_detail_info(soup):
    res = {"类型": [], "地区": "", "year": "", "release": "", "status": "", "alias": "",
           "douban": "", "主演": [], "导演": [], "编剧": []}
    box = soup.select_one(".vod-info .info") or soup.select_one(".vod-info")
    if not box:
        return res
    spans = box.select("p.row > span") or box.select("p span")
    genre_main, genre_sub = [], []
    for sp in spans:
        text = normalize_text(sp.get_text(" ", strip=True))
        m = re.match(r"^([^：:]{1,8})[：:]\s*(.*)$", text)
        if not m:
            continue
        key = _detect_label(m.group(1))
        if not key:
            continue
        rest = m.group(2)
        a_tags = sp.find_all("a")
        links = [x for x in (_clean_val(a.get_text(" ", strip=True)) for a in a_tags) if x]

        if key == "类型":
            for a in a_tags:
                v = _clean_val(a.get_text(" ", strip=True))
                if not v:
                    continue
                (genre_main if "/vodtype/" in (a.get("href") or "") else genre_sub).append(v)
            if not a_tags:
                genre_sub += _split_people(rest)
        elif key in ("主演", "导演", "编剧"):
            for v in (links or _split_people(rest)):
                if v not in res[key]:
                    res[key].append(v)
        elif key == "地区":
            if not res["地区"]:
                res["地区"] = " / ".join(dict.fromkeys(links)) if links else _clean_val(rest)
        elif key == "douban":
            mm = re.search(r"\d+(?:\.\d+)?", rest)
            if mm and float(mm.group()) > 0 and not res["douban"]:
                res["douban"] = mm.group()
        else:
            if not res[key]:
                res[key] = _clean_val(links[0] if (links and key == "year") else rest)

    genres = genre_sub or [_norm_genre(g) for g in genre_main]
    res["类型"] = list(dict.fromkeys(g for g in genres if g))
    return res

def _clean_intro(text):
    text = normalize_text(text)
    text = re.sub(r"^[\s；;，,:：]+", "", text)
    text = re.sub(r"^(内容简介|剧情简介|剧情介绍|简介|剧情)[：:]\s*", "", text)
    text = re.sub(r"\s*(详情|展开|收起)\s*$", "", text)
    return "" if is_garbled(text) else text

def parse_intro(soup):
    for h2 in soup.select("div.vod-list h2, div.layout-box h2"):
        if re.search(r"简介|剧情", h2.get_text()):
            box = h2.find_parent("div", class_="vod-list") or h2.parent
            more = box.select_one(".more-box")
            if more:
                text = more.get_text(" ", strip=True)
            else:
                h2c = copy.copy(box)
                for h in h2c.find_all("h2"):
                    h.decompose()
                text = h2c.get_text(" ", strip=True)
            t = _clean_intro(text)
            if t:
                return t
    short = soup.select_one(".vod-info .info .text")
    if short:
        t = _clean_intro(short.get_text(" ", strip=True))
        if t:
            return t
    meta = soup.find("meta", attrs={"name": "description"})
    return _clean_intro(meta.get("content", "")) if meta else ""

def _container_episodes(container, page_url):
    eps = {}
    for a in container.select("li a[href]") or container.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript", "#")):
            continue
        full = urljoin(page_url, href)
        if urlparse(full).scheme not in ("http", "https"):
            continue
        ep = normalize_text(a.get_text(strip=True)) or normalize_text(a.get("title", ""))
        if not ep:
            continue
        key, n = ep, 2
        while key in eps and eps[key] != full:
            key = f"{ep}({n})"
            n += 1
        eps[key] = full
    return filter_episodes(eps)

def extract_playlists(soup, page_url):
    """按优先级选线路：首选 → 备用 → （可选）第一条。统一命名为 PLAYLIST_NAME。
    返回 (playlists, 页面上所有线路名, 实际选中的线路名)"""
    lines, seen = [], set()
    tabs = soup.select("li.ewave-tab[data-target]") or soup.select(".playlist-tab [data-target]")
    for tab in tabs:
        tid = (tab.get("data-target") or "").strip().lstrip("#")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        cont = soup.find(id=tid)
        if not cont:
            continue
        name = normalize_text(tab.get_text(" ", strip=True))
        eps = _container_episodes(cont, page_url)
        if eps:
            lines.append((name, eps))
    if not lines:
        for ul in soup.select("ul.ewave-playlist-content"):
            eps = _container_episodes(ul, page_url)
            if eps:
                lines.append(("", eps))

    chosen, chosen_name = None, ""
    # 首选 + 备用关键字，按顺序逐个尝试
    for kw in tuple(PREFERRED_LINE_KEYWORDS) + tuple(FALLBACK_LINE_KEYWORDS):
        for n, eps in lines:
            if kw in n:
                chosen, chosen_name = eps, n
                break
        if chosen:
            break
    # 都没匹配上时，可选退而取第一条
    if chosen is None and lines and (all(not n for n, _ in lines) or PLAYLIST_FALLBACK_FIRST):
        chosen_name, chosen = lines[0]

    pls = [{"name": PLAYLIST_NAME, "episodes": chosen}] if chosen else []
    return pls, [n or "(未命名)" for n, _ in lines], chosen_name

def parse_subpage(sub_url, default_name, default_info, list_img=""):
    """返回 (rec, meta)；meta 中含 year，不写入 JSON"""
    soup = BeautifulSoup(fetch(sub_url), "lxml")

    real_name = parse_title(soup, default_name)
    f = parse_detail_info(soup)

    year = extract_year(f["year"], f["release"])
    date_val = f["release"] if (f["release"] and len(f["release"]) > 4 and extract_year(f["release"])) else year
    if re.fullmatch(r"(19|20)\d{2}\D*", date_val or ""):
        date_val = year

    img_url = pick_img_attr(soup.select_one(".vod-info .pic img")) or list_img
    img_url = fix_img_url(img_url, sub_url)

    playlists, line_names, chosen_line = extract_playlists(soup, sub_url)

    rec = {
        "name":   real_name,
        "url":    sub_url,
        "info":   default_info or f["status"],
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   " / ".join(f["导演"]) if f["导演"] else "",
        "编剧":   f["编剧"],
        "主演":   f["主演"],
        "类型":   f["类型"],
        "地区":   f["地区"],
        "date":   date_val,
        "date_re": date_val,
        "alias":  f["alias"],
        "intro":  parse_intro(soup),
        "评分":   {"豆瓣": f["douban"], "IMDB": ""},
        "playlist": playlists,
    }
    return rec, {"year": year, "fields": f, "lines": line_names, "chosen": chosen_line}


# ============== 去重查找 ==============
def _normalize_name(s):
    if not s:
        return ""
    s = s.translate(str.maketrans("：！？，（）【】", ":!?,()[]"))
    return re.sub(r"\s+", "", s).strip().lower()

def clean_season_one(s):
    return re.sub(r"(?:第[一1]季)$", "", s or "").strip()

def _year_conflict(item, year, group):
    if not year or group not in YEAR_CONFLICT_GROUPS:
        return False
    old_year = extract_year(item.get("date", ""), item.get("date_re", ""))
    return bool(old_year) and abs(int(old_year) - int(year)) > 1

def find_existing_global(data, name, sub_url, prefer_group=None, year="", log=print):
    groups_all = ["Movie", "Drama", "Show", "Anime"]
    norm_sub = normalize_url(sub_url)

    if norm_sub:
        for g in groups_all:
            for item in data.get(g, []):
                for k in item.keys():
                    if (k == "url" or re.match(r"^url\d+$", k)) and normalize_url(item.get(k, "")) == norm_sub:
                        if item.get("name", "") != name:
                            log(f"      [URL匹配去重] 已有:「{item.get('name')}」, 抓取:「{name}」")
                        return g, item

    norm = _normalize_name(name)
    base = clean_season_one(norm)
    order = ([prefer_group] if prefer_group in groups_all else []) + [g for g in groups_all if g != prefer_group]
    for g in order:
        for item in data.get(g, []):
            en = _normalize_name(item.get("name", ""))
            eb = clean_season_one(en)
            hit = (en == norm) or (base and eb and base == eb)
            if not hit:
                continue
            if _year_conflict(item, year, g) or _year_conflict(item, year, prefer_group):
                log(f"      [年份冲突] 同名「{item.get('name')}」年份 {item.get('date')} ≠ {year}，视为不同作品")
                continue
            log(f"      [名称去重] 匹配成功：已有「{item.get('name')}」({g}) ↔ 抓取「{name}」")
            return g, item
    return None, None


# ============== 合并到已有记录 ==============
def merge_into_existing(existing, rec, sub_url, group, log=print):
    """返回 (status, changed)"""
    new_pls = rec.get("playlist", [])
    serial = group in SERIAL_GROUPS
    playlist = existing.setdefault("playlist", [])
    site_idx = site_playlist_indices(playlist)
    site_set = set(site_idx)
    old_site = [playlist[i] for i in site_idx]
    others = [(i, pl) for i, pl in enumerate(playlist) if i not in site_set]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if old_site and (is_in_tc_lock_list(existing.get("name", "")) or is_in_tc_lock_list(rec["name"])):
        old_tc = any(has_tc_keyword(ep) for pl in old_site for ep in (pl.get("episodes") or {}))
        new_tc = any(has_tc_keyword(ep) for pl in new_pls for ep in pl["episodes"])
        if old_tc and not new_tc:
            return "tc_locked", False

    old_max_all = max([get_max_episode_number(pl.get("episodes", {})) for pl in playlist] or [0])
    other_max = max([get_max_episode_number(pl.get("episodes", {})) for _, pl in others] or [0])
    new_max = max([get_max_episode_number(pl["episodes"]) for pl in new_pls] or [0])
    best_new_eps = max(new_pls, key=lambda pl: get_effective_episode_count(pl["episodes"], group))["episodes"]

    status = "no_change"
    playlist_changed = False
    url_added = not has_site_url_key(existing, sub_url)

    if old_site:
        if playlist_signature(old_site) == playlist_signature(new_pls):
            pass
        elif total_episode_count(new_pls) < total_episode_count(old_site):
            log(f"      [忽略线路] 本次 {total_episode_count(new_pls)} 项 < 已有 {total_episode_count(old_site)} 项，保留原线路")
            status = "decreased"
        else:
            first = site_idx[0]
            remove_indices(playlist, site_idx)
            playlist[first:first] = copy.deepcopy(new_pls)
            playlist_changed = True
            log(f"      [线路更新] {[p['name'] for p in old_site]} -> {[p['name'] for p in new_pls]}")

        if serial and status != "decreased":
            cur = site_playlist_indices(playlist)
            if cur and cur[0] != 0 and new_max > other_max:
                block = [playlist[i] for i in cur]
                remove_indices(playlist, cur)
                playlist[0:0] = block
                playlist_changed = True
                log(f"      [排序调整] {SITE_KEY} 最大集数({new_max}) > 其他渠道({other_max})，已移动至最前")
        _ensure_site_url(existing, sub_url)
    else:
        # 仅 ONLY_UPDATE_OWN_CHANNEL=False 时才会走到这里
        if group not in ADD_CHANNEL_GROUPS:
            return "skip_add", False
        if serial:
            if new_max > other_max:
                pos = 0
            else:
                best_i, best_v = -1, -1
                for i, pl in others:
                    v = get_max_episode_number(pl.get("episodes", {}))
                    if v > best_v:
                        best_i, best_v = i, v
                pos = best_i + 1 if best_i >= 0 else len(playlist)
        else:
            pos = len(playlist)
        if ENABLE_GDEFUD_RULE:
            pos = resolve_insert_position_with_gdefud(playlist, best_new_eps, pos, group, log)
        playlist[pos:pos] = copy.deepcopy(new_pls)
        key = _ensure_site_url(existing, sub_url, force_new=True)
        url_added = True
        playlist_changed = True
        status = "channel_added"
        log(f"      [新增渠道] {SITE_KEY} 写入 {key}，{len(new_pls)} 条线路插入至第 {pos + 1} 位")

    info_changed = False
    old_info = existing.get("info", "")
    if serial and new_max > 0 and (new_max > old_max_all or not old_info):
        cand = make_episode_info(max(new_max, old_max_all), get_episode_unit(group, best_new_eps, old_info))
        if old_info != cand:
            existing["info"] = cand
            info_changed = True
            log(f"      [info更新] 「{old_info}」 -> 「{cand}」")
    elif not serial and not old_info and rec.get("info"):
        existing["info"] = rec["info"]
        info_changed = True
        log(f"      [info补充] 「{rec['info']}」")

    fields_changed = merge_missing_fields(existing, rec, log)
    if not existing.get("image") and rec.get("image"):
        local = localize_cover(existing, rec["image"])
        if local:
            existing["image"] = local
            fields_changed = True
            log(f"      [字段更新] 补充封面: {local}")

    changed = playlist_changed or info_changed or fields_changed or url_added
    if status == "decreased":
        return "decreased", changed

    if serial:
        if new_max > old_max_all:
            existing["update"] = now
    elif playlist_changed:
        existing["update"] = now

    if status == "no_change" and changed:
        status = "updated"
    return status, changed


# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name, seen_urls):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    filter_regions = FILTER_REGIONS_BY_GROUP.get(group, FILTER_REGIONS)
    try:
        items = collect_list_items(list_url)
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        return 0, 0, 0, 0
    print(f"  共发现 {len(items)} 条")
    ok = fail = skip_year = skip_exist = 0

    for idx, (name, info, url, img) in enumerate(items, 1):
        tag = f"  ({idx}/{len(items)}) {name}"
        if normalize_url(url) in seen_urls:
            print(f"{tag} [本次运行已处理过，跳过]")
            continue
        seen_urls.add(normalize_url(url))
        if is_blacklisted_name(name):
            print(f"{tag} [在名称黑名单中，跳过]")
            continue
        if any(b in url for b in BLACKLIST_URLS if b):
            print(f"{tag} [URL 在黑名单中，跳过: {url}]")
            continue

        header = f"{tag}  [{info}]"
        buf = []

        def flush():
            print(header)
            for line in buf:
                print(line)
            buf.clear()

        try:
            rec, meta = parse_subpage(url, name, info, list_img=img)
            real_name = rec["name"]
            year = meta["year"]

            # —— 第一道关：年份过滤 ——
            if (not year and SKIP_IF_YEAR_UNKNOWN) or (year and year not in ALLOWED_YEARS):
                print(f"{header}\n    - 跳过：年份「{year or '未知'}」不在 {sorted(ALLOWED_YEARS)} 内")
                skip_year += 1
                polite_sleep()
                continue

            if real_name != name and is_blacklisted_name(real_name):
                print(f"{header}\n    - 跳过：真实名称「{real_name}」在黑名单中")
                polite_sleep()
                continue

            new_pls = rec["playlist"]
            if not new_pls:
                flush()
                print(f"    ! 未找到「{'/'.join(PREFERRED_LINE_KEYWORDS + FALLBACK_LINE_KEYWORDS)}」线路，跳过"
                      f"（页面线路：{meta['lines'] or '无'}）")
                fail += 1
                polite_sleep()
                continue
            line_desc = ", ".join(f"{p['name']}({len(p['episodes'])})" for p in new_pls)
            buf.append(f"    [线路] {line_desc}  来源:「{meta['chosen']}」  年份:{year}  地区:{rec.get('地区') or '未知'}")

            max_line = max(len(p["episodes"]) for p in new_pls)
            if group in ("Drama", "Anime") and max_line > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」集数 {max_line} 超过 {MAX_EPISODES} 上限")
                ok += 1
                polite_sleep()
                continue

            matched_group, existing = find_existing_global(
                data, real_name, url, prefer_group=group, year=year, log=buf.append)
            eff_group = matched_group or group

            if existing is not None and ONLY_UPDATE_OWN_CHANNEL and not has_own_channel(existing):
                # 只补缺失字段/封面，绝不动 playlist、url、info、update
                changed = merge_missing_fields(existing, rec, buf.append)
                if _cover_missing(existing) and rec.get("image"):
                    fn = localize_cover(existing, rec["image"])
                    if fn:
                        existing["image"] = fn
                        changed = True
                        buf.append(f"      [字段更新] 补充封面: {fn}")
                if changed:
                    save_json(data)
                flush()
                print(f"    - 「{existing.get('name')}」({matched_group}) 无 {PLAYLIST_NAME} 渠道 → "
                      f"playlist 不更新" + ("，已补全字段" if changed else "，无可补字段"))
                skip_exist += 1
                polite_sleep()
                continue

            if existing and matched_group != group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，将按「{matched_group}」规则处理")

            if is_whitelisted_name(real_name):
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            elif existing and eff_group in ("Anime", "Drama", "Movie"):
                buf.append(f"    已存在记录（含 {PLAYLIST_NAME} 渠道），跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = (rec.get("地区") or "").strip()
                if region_blocked(region, filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    ok += 1
                    polite_sleep()
                    continue
                if region in ("", "未知"):
                    type_text = " ".join(rec.get("类型", []) or [])
                    kw = next((k for k in ["国产", "中国", "大陆", "内地"] if k in type_text), None)
                    if kw:
                        flush()
                        print(f"    - 跳过：地区未知，但类型「{type_text}」含「{kw}」，判定为国产内容")
                        ok += 1
                        polite_sleep()
                        continue

            if existing:
                status, changed = merge_into_existing(existing, rec, url, eff_group, buf.append)
                if changed:
                    save_json(data)
                flush()
                msg = {
                    "channel_added": f"    ✅ 更新({eff_group})：已把 {SITE_KEY} 作为新渠道写入",
                    "updated":       f"    ✅ 更新({eff_group})：{SITE_KEY} 线路/信息已更新",
                    "no_change":     f"    - 无变更({eff_group})",
                    "decreased":     f"    - 忽略({eff_group})：抓取集数少于已有集数" + ("（字段已补全）" if changed else ""),
                    "tc_locked":     f"    🛡️ [TC锁定跳过] 「{real_name}」原有 {SITE_KEY} 线路含 TC，新抓为非 TC，锁定不更新",
                    "skip_add":      f"    - 跳过({eff_group})：项目已存在但无 {SITE_KEY} 渠道，且该分类不允许追加渠道",
                }.get(status, f"    ? 未知状态 {status}")
                print(msg)
                ok += 1
            else:
                flush()
                img_src = rec.get("image", "")
                rec["image"] = localize_cover(rec, img_src)
                if group in SERIAL_GROUPS:
                    ep_cnt = max(get_max_episode_number(p["episodes"]) for p in new_pls)
                    if ep_cnt > 0:
                        best = max(new_pls, key=lambda p: len(p["episodes"]))["episodes"]
                        rec["info"] = make_episode_info(ep_cnt, get_episode_unit(group, best, rec.get("info", "")))
                data.setdefault(group, []).append(rec)
                save_json(data)
                print(f"    ✅ 新增 -> {group} (线路 {len(new_pls)} 条) [真实名称: {real_name}] [URL: {url}]"
                      + ("" if rec["image"] else "  ⚠️ 封面暂缺，收尾时补抓"))
                ok += 1

        except ConcurrentWriteError:
            raise
        except Exception as e:
            flush()
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        polite_sleep()

    return ok, fail, skip_year, skip_exist


# ============== 补全模式 ==============
def fill_empty_fields(item, rec):
    changed = False
    for f in ["导演", "编剧", "主演", "类型", "地区", "date", "intro", "alias"]:
        if not item.get(f) and rec.get(f):
            item[f] = rec[f]
            changed = True
    score = item.get("评分") if isinstance(item.get("评分"), dict) else None
    new_db = (rec.get("评分") or {}).get("豆瓣")
    if new_db and (score is None or not score.get("豆瓣")):
        if not isinstance(item.get("评分"), dict):
            item["评分"] = {"豆瓣": "", "IMDB": ""}
        item["评分"]["豆瓣"] = new_db
        changed = True
    return changed

def _cover_missing(item):
    img = item.get("image") or ""
    if not img:
        return True
    if img.lower().startswith(("http://", "https://")):
        return True
    return not (os.path.exists(os.path.join(IMG_DIR, img)) and os.path.getsize(os.path.join(IMG_DIR, img)) > 0)

def backfill_existing(data):
    print(f"\n[补全模式] 扫描含 {SITE_KEY} 渠道、字段或封面缺失的资源 ...")
    total = updated = 0
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            target = next((item.get(k) for k in _url_keys_sorted(item)
                           if item.get(k) and SITE_KEY in item.get(k)), None)
            if not target:
                continue
            # if ONLY_UPDATE_OWN_CHANNEL and not has_own_channel(item):
            #     continue
            need_fields = not any(item.get(f) for f in ["导演", "主演", "类型", "地区", "intro"])
            need_image = _cover_missing(item)
            if not (need_fields or need_image):
                continue
            total += 1
            why = "/".join(x for x, c in (("字段", need_fields), ("封面", need_image)) if c)
            print(f"  [{group}] 补全({why}): {item.get('name')}  <- {target}")
            try:
                rec, _ = parse_subpage(target, item.get("name", ""), "")
                changed = fill_empty_fields(item, rec)
                if changed:
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if need_image and rec.get("image"):
                    fn = download_and_localize_image(rec["image"], budget=IMG_FINAL_BUDGET)
                    if fn:
                        item["image"] = fn
                        changed = True
                if changed:
                    updated += 1
                    save_json(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} "
                          f"地区:「{item.get('地区')}」 封面:{item.get('image') or '仍缺'})")
                else:
                    print("    - 未发现可补全内容")
            except ConcurrentWriteError:
                raise
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            polite_sleep()
    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")


# ============== 命令行解析 ==============
def parse_cli():
    global USE_CDP, HEADLESS, FORCE_BROWSER, BROWSER_FALLBACK, AUTO_CLICK_TURNSTILE, MAX_LIST_PAGES
    args = [a.lower().lstrip("-") for a in sys.argv[1:]]
    if "open" in args or "launch" in args:
        launch_chrome_for_cdp()
        sys.exit(0)
    if "cdp" in args:
        USE_CDP = True
        AUTO_CLICK_TURNSTILE = False
        print(">>> [模式] CDP：附着到你手动启动的 Chrome（不会关闭它）")
    if "browser" in args:
        FORCE_BROWSER = True
        print(">>> [模式] 强制浏览器通道")
    if "headless" in args:
        HEADLESS = True
        print(">>> [模式] 无头浏览器")
    if "nobrowser" in args:
        BROWSER_FALLBACK = False
        print(">>> [模式] 禁用浏览器兜底（纯直连）")
    if "click" in args:
        AUTO_CLICK_TURNSTILE = True
    for a in args:
        m = re.match(r"^pages=(\d+)$", a)
        if m:
            MAX_LIST_PAGES = max(1, int(m.group(1)))
            print(f">>> [模式] 每个分类最多翻 {MAX_LIST_PAGES} 页")
    return "backfill" in args


# ============== 主流程 ==============
def main():
    setup_logging()
    is_backfill = parse_cli()
    start_caffeinate()
    acquire_run_lock()
    os.makedirs(IMG_DIR, exist_ok=True)

    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    data = load_existing(JSON_PATH)
    snapshot_backup(JSON_PATH)
    if os.path.exists(JSON_PATH + ".tmp"):
        print(f">>> [提示] 发现残留临时文件 {JSON_PATH}.tmp，可自行检查后删除")
    print(f">>> [规则] ONLY_UPDATE_OWN_CHANNEL={ONLY_UPDATE_OWN_CHANNEL}："
          f"{'只新增新作品；已存在作品仅在含 ' + PLAYLIST_NAME + ' 渠道时更新' if ONLY_UPDATE_OWN_CHANNEL else '已存在作品可追加本站渠道'}")

    try:
        _fetcher.start()
        if is_backfill:
            backfill_existing(data)
            print(f"\n补全任务完成! 数据已保存在 {JSON_PATH}")
            return

        seen_urls = set()
        total_ok = total_fail = total_year = total_exist = 0
        for list_url, group, page_name in LIST_PAGES:
            ok, fail, sy, se = process_list_page(data, list_url, group, page_name, seen_urls)
            total_ok += ok
            total_fail += fail
            total_year += sy
            total_exist += se
        retry_pending_covers(data)
        print("\n====================================")
        print(f"所有抓取任务完成! 成功 {total_ok} 条，失败 {total_fail} 条，"
              f"年份不符跳过 {total_year} 条，已存在且无 {PLAYLIST_NAME} 渠道跳过 {total_exist} 条。"
              f"数据已实时保存在 {JSON_PATH}")
    except ConcurrentWriteError as e:
        print(f"\n⛔ {e}")
    finally:
        _fetcher.close()

if __name__ == "__main__":
    main()