# -*- coding: utf-8 -*-
"""
dzfwjd.com（番茄影视）分类页（欧美剧 / 日韩剧）爬取脚本 —— 替代已失效的 312f.com
—— 默认 curl_cffi 直连（快）；遇 Cloudflare 挑战自动弹出真实 Chrome 让你手动验证，
   通过后把 cookie/UA 同步回直连，并缓存到本地，下次运行直接复用

【流程】列表页 -> 详情页(字段/年份/地区过滤) -> 播放页(全部线路 & 选集)

【用法】
    python Crawl_dzfwjd.py                 # 正常抓取（直连优先，被拦时自动弹出独立 Chrome 让你验证）
    python Crawl_dzfwjd.py probe           # 探测站点是否有 Cloudflare / WAF（不写任何数据）
    python Crawl_dzfwjd.py backfill        # 补全模式：对已有 dzfwjd 记录补缺失字段
    python Crawl_dzfwjd.py open            # 手动启动带调试端口的独立 Chrome（预先过验证用）
    python Crawl_dzfwjd.py cdp             # 强制附着到 open 启动的 Chrome
    python Crawl_dzfwjd.py pw              # 浏览器兜底改用 Playwright 自启 Chrome（不推荐，易卡验证）
    python Crawl_dzfwjd.py browser         # 不用直连，全程真实浏览器（直连始终被拦时用）
    python Crawl_dzfwjd.py headless        # Playwright 模式下无头（遇 CF 不推荐）
    python Crawl_dzfwjd.py nocache         # 不使用/不读取本地 cookie 缓存
    python Crawl_dzfwjd.py drama=3         # 按分类临时覆盖抓取页数
    python Crawl_dzfwjd.py pages=3         # 所有分类统一抓前 3 页
    python Crawl_dzfwjd.py only=drama      # 只抓指定分类
参数可组合：python Crawl_dzfwjd.py browser drama=2
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
import tempfile
import atexit
import unicodedata
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen
from datetime import datetime

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi

try:
    import fcntl          # macOS / Linux 文件锁
except ImportError:       # Windows 无 fcntl，退化为无锁
    fcntl = None

SCRIPT_NAME = os.path.basename(__file__)


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
DOMAIN        = "https://www.dzfwjd.com"
SITE_HOST     = "dzfwjd.com"          # 按域名判断 URL 是否属于本站（www 子域也算）
SITE_KEY      = "dzfwjd"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
TARGET_COMPARE_CHANNEL = "shangxidq"     # 目标比对排序渠道
REQUEST_TIMEOUT = 20
SLEEP_BETWEEN   = 1.0

# —— 列表页与翻页 ——
PAGES_BY_GROUP = {
    "Movie": 1,
    "Drama": 1,
    "Show":  1,
    "Anime": 1,
}
DEFAULT_PAGES = 1
ONLY_GROUPS = set()

LIST_SOURCES = [
    (f"{DOMAIN}/cate-filter/oumeiju.html", "Drama", "欧美剧"),
    (f"{DOMAIN}/cate-filter/hanju.html",   "Drama", "日韩剧"),
    # 以后要加别的分类页，照格式追加即可：
    # (f"{DOMAIN}/cate-filter/XXX.html", "Show",  "综艺"),
    # (f"{DOMAIN}/cate-filter/XXX.html", "Anime", "动漫"),
]

def get_max_pages(group):
    return PAGES_BY_GROUP.get(group, DEFAULT_PAGES)

# —— 年份过滤 ——
ALLOWED_YEARS = {"2026"}
ALLOWED_YEARS_BY_GROUP = {
    # "Anime": {"2025", "2026"},
}
# 列表卡片上有「美国／2026」，年份明显不符时直接跳过，不再请求详情页（最终仍以详情页年份为准）
PREFILTER_BY_LIST_YEAR = True

# —— 简介里的「又名XXX」「豆瓣评分X.X」是否提取为 alias / 评分 ——
EXTRACT_ALIAS_FROM_INTRO = True

# —— 播放列表命名 / 归属 ——
PLAYLIST_NAME_TEMPLATE = "{line}"          # 线路名直接用站点名（如 "FF线路"）
PLAYLIST_SOURCE_FIELD = "source"           # 每条本站 playlist 带 source=dzfwjd 标识归属
KEEP_MISSING_LINES = True                  # 某条线路本次没抓到时保留旧数据
PLAYLIST_ORIGIN_FIELD = "origin"           # 记录线路来自哪个本站详情页

# —— 已失效站点的旧线路处理（312f 已被封） ——
# "demote": 本脚本更新某条记录时，把这些来源的线路移到 playlist 末尾（不删除，默认）
# "remove": 直接删除这些来源的线路
# "keep"  : 完全不处理
RETIRED_SOURCES = {"312f"}
RETIRED_POLICY  = "demote"

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

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 5.0
BROWSER_ON_LAST_RETRY = True

# ============== 直连 / 浏览器回退配置 ==============
BROWSER_ONLY    = False
FAST_IMPERSONATE_CANDIDATES = ["chrome136", "chrome133a", "chrome131", "chrome124", "chrome120", "chrome"]
COOKIE_RESYNC_INTERVAL = 300
DIRECT_MAX_RESYNC_FAIL = 3
IMAGE_BROWSER_FALLBACK = True
BASE_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# 验证通过后的 cookie + UA 缓存（下次运行直接复用，失效会自动丢弃并重新验证）
USE_COOKIE_CACHE     = True
COOKIE_CACHE_FILE    = os.path.expanduser("~/.dzfwjd_cookies.json")
COOKIE_CACHE_MAX_AGE = 24 * 3600

USER_DATA_DIR    = os.path.expanduser("~/.dzfwjd_chrome_profile")       # CDP 独立 Chrome 的 profile
PW_USER_DATA_DIR = os.path.expanduser("~/.dzfwjd_chrome_profile_pw")    # Playwright 自启时的 profile（避免与上面抢锁）
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9224                        # 与 shangxidq(9222)、312f(9223) 错开
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False                       # 命令行 cdp：强制附着
AUTO_ATTACH_CDP = True                        # 检测到 CDP 端口在监听时自动附着
AUTO_LAUNCH_CDP = True                        # 需要浏览器时自动启动「普通 Chrome + 调试端口」再附着（过 CF 最稳）
NAV_TIMEOUT_MS  = 60000

CHALLENGE_WAIT        = 600
CHALLENGE_GRACE       = 10
PASS_STABLE_HITS      = 3
POLL_INTERVAL         = 1.5
SITE_READY_TIMEOUT    = 8
PAGE_SETTLE           = 1.0

AUTO_CLICK_TURNSTILE   = True        # 仅 Playwright 自启模式生效；CDP 模式下由你手动点
AUTO_CLICK_FIRST_DELAY = 8
AUTO_CLICK_EVERY       = 15

CHALLENGE_MARKERS = (
    "Just a moment", "challenges.cloudflare.com/turnstile", "__cf_chl", "cf_chl_opt",
    "cf-challenge", "challenge-platform", "Checking your browser", "Verifying you are human",
    "Enable JavaScript and cookies to continue", "需要先验证您是真人", "正在验证您是否是真人",
    "btwaf", "人机验证", "人机识别", "安全验证", "访问验证", "滑动验证", "请开启JavaScript",
)
# 本站模板特征（全部小写，判断时对 html.lower() 匹配）
SITE_MARKERS = ("gm-list", "gm-vod", "dom-source", "gm-head", "gm-main",
                'href="/movie/', 'href="/movie-play/')

# ⚠️ 与 Crawl_shangxidq.py / Crawl_312f.py 保持同步
BLACKLIST_NAMES = [
    "天堂之剑", "定海神针：九尾三世劫", "机甲少女破时空战记", "永恒和一日",
    "无名传奇", "魔彩王国历险记", "阿松与阿暖", "欲望的陷阱", "轻松熊", "家1",
    "人生赢家", "判决", "判决墨西哥剧", "后门", "校规101", "校规", "无人区",
    "第二盘", "别班 第二季",
]
BLACKLIST_URLS = []
WHITELIST_NAMES = [
    "二十世纪电气目录", "茶啊二中 第六季", "猫与龙",
    "骸骨骑士大人异世界冒险中Ⅱ", "炒翻天", "别班 第二季",
    "超超超超超喜欢你的100个女朋友 第三季", "七龙珠超：比鲁斯",
    "虽然我不是完美恶女～雏宫蝶鼠替换传～",
    "暗芝居 第十七季", "鬼之花嫁", "成长秀～向日葵马戏团～",
]

QIANGXIAN_KEYWORDS = ['TC', 'TS', '抢先', 'HC']
TC_LOCK_NAMES = {"起义", "猛攻"}

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "日本"]
FILTER_REGIONS_BY_GROUP = {
    "Movie": ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "Drama": ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产",
              "泰国", "台湾", "中国台湾", "日本"],
    "Show":  FILTER_REGIONS,
    "Anime": ["中国", "大陆", "内地", "国产", "中国大陆", "中国内地", "国产剧",
              "泰国", "台湾", "中国台湾", "日本"],
}
FILTER_REGIONS_OVERRIDE = {}
REGION_BYPASS_FOR_EXISTING = ("Anime", "Drama", "Movie")

EMPTY_VALUES = {"未知", "内详", "暂无", "/", "-", "未录入", "不详"}
INVALID_EPISODE_NAMES = {"立即播放", "收藏", "免费观看"}
MAX_EPISODES_BY_GROUP = {
    "Drama": 30,
    "Anime": 30,
}
GROUPS = ["Movie", "Drama", "Show", "Anime"]


# ============== 异常类型 ==============
class FetchError(Exception):
    pass

class NoRetryFetchError(FetchError):
    pass


# ==========================================================
#                    数据读写（带文件锁）
# ==========================================================
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

    has_backup = False
    if not main_exists:
        has_backup = any(os.path.exists(c) and os.path.getsize(c) > 0 for c in _backup_candidates())
        if has_backup:
            print(f"\n⚠️ [警告] 主数据文件不存在，但发现历史备份，尝试从备份恢复。"
                  f"\n   （如确实想从零开始，请先清空 {BACKUP_DIR} 与 {BAK_FILE}）")

    if main_exists or has_backup:
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
    return {g: [] for g in GROUPS}

def save_json(data: dict, force: bool = False, quiet: bool = True) -> bool:
    """原子写盘：唯一临时文件 + fsync + 校验 + os.replace"""
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

    json_dir = os.path.dirname(JSON_PATH)
    os.makedirs(json_dir, exist_ok=True)
    tmp_file = None
    try:
        if os.path.exists(JSON_PATH) and os.path.getsize(JSON_PATH) > 0:
            try:
                shutil.copy2(JSON_PATH, BAK_FILE)
            except Exception:
                pass
        fd, tmp_file = tempfile.mkstemp(dir=json_dir, prefix=".OVideos.", suffix=f".{SITE_KEY}.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _read_json_strict(tmp_file)
        os.replace(tmp_file, JSON_PATH)
        tmp_file = None
        _BASELINE_TOTAL = max(_BASELINE_TOTAL, total)
        if not quiet:
            print(f"  [已保存] 共 {total} 条")
        return True
    except Exception as e:
        print(f"  [错误] 实时保存失败: {e}")
        return False
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


class _Tx:
    def __init__(self, data):
        self.data = data
        self.dirty = False
        self.saved = True


class DataStore:
    """
    防止多个爬虫脚本互相覆盖：
    - 修改前加排他文件锁；
    - 加锁后若发现磁盘文件被其它进程改过（mtime/size 变化），先重新加载再修改；
    - 网络请求全部在锁外完成，锁只包住「读-改-写」这一小段。
    """
    def __init__(self, path):
        self.path = path
        self.data = None
        self._sig = None

    def _file_sig(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return None

    @contextmanager
    def locked(self):
        if fcntl is None:
            yield
            return
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        fd = open(LOCK_FILE, "a+")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                fd.close()

    def initial_load(self):
        with self.locked():
            self.data = load_existing(self.path)
            self._sig = self._file_sig()
        return self.data

    def _refresh_if_changed(self):
        global _BASELINE_TOTAL
        sig = self._file_sig()
        if sig is None or sig == self._sig:
            return
        try:
            fresh = _read_json_strict(self.path)
        except Exception as e:
            print(f"  [同步] 数据文件被外部修改但无法解析({e})，继续使用内存数据")
            return
        self.data = fresh
        self._sig = sig
        _BASELINE_TOTAL = count_items(fresh)
        print(f"  [同步] 检测到其他进程修改了数据文件，已重新加载（{_BASELINE_TOTAL} 条）")

    @contextmanager
    def transaction(self):
        with self.locked():
            self._refresh_if_changed()
            tx = _Tx(self.data)
            try:
                yield tx
            except BaseException:
                self._sig = None
                raise
            if tx.dirty:
                if save_json(self.data):
                    self._sig = self._file_sig()
                else:
                    tx.saved = False


# ==========================================================
#              CDP：启动 / 探测 Chrome
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

def launch_chrome_for_cdp(open_url=True, hint=True):
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    if cdp_alive():
        print(f">>> [CDP] 端口 {CDP_PORT} 已在监听，无需重复启动。")
        return True
    print(">>> [CDP] 正在启动独立 Chrome（独立 profile，不影响你日常使用的 Chrome）")
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
            print(f">>> [CDP] Chrome 已就绪（端口 {CDP_PORT}）")
            if hint:
                print(f">>> 请在窗口里手动通过验证，然后执行：python {SCRIPT_NAME} cdp")
            return True
    print("!!! 等待调试端口超时。请手动执行：\n" + cdp_launch_command())
    return False


# ==========================================================
#                  内容判定小工具
# ==========================================================
def looks_blocked(html: str) -> bool:
    """判断一段 HTML 是不是挑战/验证页（而不是站点正常页）"""
    if not html or len(html) < 200:
        return True
    low = html.lower()
    if any(m in low for m in SITE_MARKERS):
        return False
    head = html[:10000]
    if any(m in head for m in CHALLENGE_MARKERS):
        return True
    if len(html) < 3000 and "<script" in low:
        return True
    return False

def looks_like_image(data: bytes, ctype: str = "") -> bool:
    if not data or len(data) < 100:
        return False
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG"):
        return True
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[4:12] in (b"ftypavif", b"ftypheic", b"ftypmif1"):
        return True
    if (ctype or "").lower().startswith("image/") and not data.lstrip()[:1] == b"<":
        return True
    return False

def is_site_url(u: str) -> bool:
    if not u:
        return False
    u = str(u).strip()
    host = (urlparse(u if "://" in u else "https://" + u).hostname or "").lower()
    return host == SITE_HOST or host.endswith("." + SITE_HOST)

def _imp_supported(imp: str) -> bool:
    """尽量在创建会话前判断 curl_cffi 是否支持该指纹（老版本拿不到枚举时默认支持，失败再轮换）"""
    if imp == "chrome":
        return True
    try:
        from curl_cffi.requests import BrowserType
        return imp in {b.value for b in BrowserType}
    except Exception:
        return True


# ==========================================================
#        抓取层：curl_cffi 直连优先 + 真实 Chrome 回退
# ==========================================================
_STATE_JS = """
() => {
  const q = s => !!document.querySelector(s);
  const hasSite = q('.gm-list') || q('.gm-vod') || q('#dom-source') || q('.gm-head') ||
                  q('a[href*="/movie/"]') || q('a[href*="/movie-play/"]');
  const cfFrame = Array.from(document.querySelectorAll('iframe'))
                       .some(f => (f.src || '').includes('challenges.cloudflare.com'));
  const hasChl  = cfFrame || q('#challenge-form') || q('#challenge-running') ||
                  q('#cf-challenge-running') || q('.cf-turnstile') ||
                  q('#turnstile-wrapper') || q('#challenge-stage');
  const title   = document.title || '';
  const titleChl = /just a moment|attention required|checking your browser|verify|请稍候|稍等|安全检查|安全验证/i.test(title);
  const len = (document.body && document.body.innerText) ? document.body.innerText.length : 0;
  return { hasSite, hasChl, titleChl, len, title };
}
"""


class HybridFetcher:
    def __init__(self):
        # 直连
        self._session = None
        self._imp_idx = 0
        self._impersonate = None
        self._cookies = {}
        self._ua = ""
        self._synced = False
        self._from_cache = False
        self._cache_loaded = False
        self._last_sync = 0.0
        self._blocked_after_sync = 0
        self.direct_disabled = BROWSER_ONLY
        self._no_session_warned = False
        # 浏览器
        self._pw = None
        self._ctx = None
        self._page = None
        self._browser = None
        self._using_cdp = False
        self._own_page = False

    # ---------------- cookie 缓存 ----------------
    def _load_cookie_cache(self):
        if self._cache_loaded:
            return
        self._cache_loaded = True
        if not USE_COOKIE_CACHE:
            return
        try:
            with open(COOKIE_CACHE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            return
        except Exception as e:
            print(f">>> [缓存] cookie 缓存读取失败（忽略）: {e}")
            return
        age = time.time() - float(d.get("ts") or 0)
        cookies = d.get("cookies") or {}
        if not cookies or age > COOKIE_CACHE_MAX_AGE:
            return
        self._cookies = dict(cookies)
        self._ua = d.get("ua") or ""
        self._from_cache = True
        print(f">>> [缓存] 复用上次验证通过的 {len(cookies)} 个 cookie（{int(age // 60)} 分钟前，"
              f"cf_clearance: {'有' if 'cf_clearance' in cookies else '无'}）")

    def _save_cookie_cache(self):
        if not USE_COOKIE_CACHE or not self._cookies:
            return
        try:
            tmp = COOKIE_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "ua": self._ua, "cookies": self._cookies}, f, ensure_ascii=False)
            os.replace(tmp, COOKIE_CACHE_FILE)
            try:
                os.chmod(COOKIE_CACHE_FILE, 0o600)
            except Exception:
                pass
        except Exception as e:
            print(f"    [缓存] cookie 缓存写入失败: {e}")

    def _drop_cookie_cache(self):
        self._cookies = {}
        self._ua = ""
        self._from_cache = False
        self._session = None          # 重建会话，恢复指纹自带的 UA
        try:
            os.remove(COOKIE_CACHE_FILE)
        except Exception:
            pass

    # ---------------- 直连通道 ----------------
    def _ensure_session(self):
        self._load_cookie_cache()
        if self._session is not None:
            return self._session
        while self._imp_idx < len(FAST_IMPERSONATE_CANDIDATES):
            imp = FAST_IMPERSONATE_CANDIDATES[self._imp_idx]
            if not _imp_supported(imp):
                self._imp_idx += 1
                continue
            try:
                s = cffi.Session(impersonate=imp)
            except Exception:
                self._imp_idx += 1
                continue
            s.headers.update(BASE_HEADERS)
            if self._ua:
                s.headers["User-Agent"] = self._ua
            self._session = s
            if self._impersonate != imp:
                print(f">>> [直连] curl_cffi 已就绪，TLS 指纹: {imp}")
            self._impersonate = imp
            return s
        if not self._no_session_warned:
            print(">>> [直连] 所有 TLS 指纹候选都不可用，改为全程浏览器")
            self._no_session_warned = True
        return None

    def _rotate_impersonate(self):
        self._imp_idx += 1
        self._session = None

    @staticmethod
    def _decode(r):
        raw = r.content or b""
        enc = (getattr(r, "encoding", None) or "").lower()
        if not enc or enc == "iso-8859-1":
            m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', raw[:4096])
            enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")

    def _direct(self, url, binary=False, referer=None):
        """返回 (状态, 值)；状态 ∈ ok / 404 / blocked / error / skip"""
        if self.direct_disabled and not binary:
            return "skip", None
        s = self._ensure_session()
        if s is None:
            return "skip", None

        if self._ctx is not None and time.time() - self._last_sync > COOKIE_RESYNC_INTERVAL:
            self._sync_cookies(verbose=False)

        kw = {"timeout": REQUEST_TIMEOUT, "allow_redirects": True,
              "headers": {"Referer": referer or (DOMAIN + "/")}}
        if is_site_url(url) and self._cookies:
            kw["cookies"] = dict(self._cookies)

        try:
            r = s.get(url, **kw)
        except Exception as e:
            msg = str(e)
            if "impersonat" in msg.lower():
                self._rotate_impersonate()
                return "error", FetchError(f"TLS 指纹不可用，已切换候选: {msg}")
            return "error", FetchError(f"直连异常: {msg}")

        code = r.status_code
        mitigated = (r.headers.get("cf-mitigated") or "").lower()
        if code == 404:
            return "404", None
        if mitigated == "challenge":
            return "blocked", f"HTTP {code} + cf-mitigated: challenge"
        if code == 403:
            return "blocked", "HTTP 403"
        if code == 503:
            try:
                txt = self._decode(r)
            except Exception:
                txt = ""
            if any(m in txt[:10000] for m in CHALLENGE_MARKERS):
                return "blocked", "HTTP 503 挑战页"
            return "error", FetchError("HTTP 503")
        if code == 429:
            return "error", FetchError("HTTP 429 限流")
        if code >= 400:
            return "error", FetchError(f"HTTP {code}")

        if binary:
            data = r.content
            if not looks_like_image(data, r.headers.get("content-type", "")):
                return "blocked", "返回内容不是有效图片"
            return "ok", data

        text = self._decode(r)
        if looks_blocked(text):
            return "blocked", "命中挑战/验证页"
        return "ok", text

    def _sync_cookies(self, verbose=True):
        if self._ctx is None:
            return
        try:
            cookies = {c["name"]: c["value"] for c in self._ctx.cookies(DOMAIN)}
        except Exception:
            cookies = {}
        try:
            ua = self._page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            ua = ""
        self._cookies = cookies
        self._last_sync = time.time()
        self._synced = True
        self._from_cache = False
        if ua and ua != self._ua:
            self._ua = ua      # cf_clearance 与 UA 绑定，直连必须用同一个 UA
            if self._session is not None:
                self._session.headers["User-Agent"] = ua
        self._save_cookie_cache()
        if verbose:
            has_clr = "cf_clearance" in cookies
            print(f"    [同步] 已把浏览器 {len(cookies)} 个 cookie 同步回直连 "
                  f"(cf_clearance: {'有 ✅' if has_clr else '无'})")

    # ---------------- 对外接口 ----------------
    def get_html(self, url, prefer_browser=False):
        if not prefer_browser:
            st, val = self._direct(url)
            if st == "ok":
                self._blocked_after_sync = 0
                return val
            if st == "404":
                raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
            if st == "error":
                raise val
            if st == "blocked":
                if self._from_cache:
                    print("    [直连] 缓存的验证 cookie 已失效，丢弃缓存")
                    self._drop_cookie_cache()
                elif self._synced:
                    self._blocked_after_sync += 1
                    if self._blocked_after_sync >= DIRECT_MAX_RESYNC_FAIL:
                        print("    [直连] 同步 cookie 后仍连续被拦，本次运行改为全程浏览器")
                        self.direct_disabled = True
                print(f"    [直连] {val} → 切换真实 Chrome: {url}")
        html = self._browser_get(url)
        if not self.direct_disabled:
            self._sync_cookies()
        return html

    def get_bytes(self, url):
        st, val = self._direct(url, binary=True)
        if st == "ok":
            return val
        if st == "404":
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if st == "error":
            raise val
        if not IMAGE_BROWSER_FALLBACK:
            raise FetchError(str(val))
        print(f"    [图片] 直连失败({val})，改用浏览器通道")
        return self._browser_bytes(url)

    # ---------------- 浏览器通道 ----------------
    def _start_browser(self):
        if self._ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise FetchError("需要浏览器回退但未安装 playwright：pip install playwright && playwright install chromium")

        want_cdp = USE_CDP or AUTO_LAUNCH_CDP or (AUTO_ATTACH_CDP and cdp_alive())
        if want_cdp and not cdp_alive():
            if AUTO_LAUNCH_CDP:
                print(">>> [CDP] 未检测到调试 Chrome，自动启动独立 Chrome（普通 Chrome，最容易通过 Cloudflare）")
                if not launch_chrome_for_cdp(open_url=False, hint=False):
                    if USE_CDP:
                        raise FetchError("CDP 端口不可用")
                    print(">>> [CDP] 启动失败，改用 Playwright 自启 Chrome")
                    want_cdp = False
            else:
                print(f"\n!!! 没有检测到可用的 Chrome 调试端口 {CDP_ENDPOINT}")
                print(f"    请先执行：python {SCRIPT_NAME} open\n    或手动执行：\n{cdp_launch_command()}")
                raise FetchError("CDP 端口不可用")

        self._pw = sync_playwright().start()

        if want_cdp:
            try:
                print(f">>> [CDP] 正在附着到 Chrome：{CDP_ENDPOINT}")
                self._browser = self._pw.chromium.connect_over_cdp(CDP_ENDPOINT)
                self._ctx = (self._browser.contexts[0]
                             if self._browser.contexts else self._browser.new_context())
                self._page = self._pick_page()
                self._using_cdp = True
            except Exception as e:
                if USE_CDP:
                    raise FetchError(f"CDP 附着失败: {e}")
                print(f">>> [CDP] 附着失败({e})，改用 Playwright 自启 Chrome")
                self._ctx = self._browser = self._page = None
                want_cdp = False

        if not want_cdp:
            os.makedirs(PW_USER_DATA_DIR, exist_ok=True)
            print(f">>> [浏览器] 启动真实 Chrome（profile: {PW_USER_DATA_DIR}）")
            launch_kwargs = dict(
                user_data_dir=PW_USER_DATA_DIR, headless=HEADLESS, locale="zh-CN",
                timezone_id="Asia/Shanghai", viewport={"width": 1360, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                      "--no-default-browser-check", "--start-maximized"],
                ignore_default_args=["--enable-automation"],
            )
            if BROWSER_CHANNEL:
                launch_kwargs["channel"] = BROWSER_CHANNEL
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e:
                print(f">>> [浏览器] 系统 Chrome 启动失败({e})，改用 Playwright 自带 Chromium")
                launch_kwargs.pop("channel", None)
                self._ctx = self._pw.chromium.launch_persistent_context(**launch_kwargs)
            try:
                self._ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except Exception:
                pass
            pages = [p for p in self._ctx.pages if not p.is_closed()]
            self._page = pages[0] if pages else self._ctx.new_page()

        self._ctx.set_default_timeout(NAV_TIMEOUT_MS)
        self._ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        if self._using_cdp:
            self._report_clearance()    # 打印 cf_clearance 是否存在
            self._sync_cookies()        # 立即把验证后的 cookie + UA 同步给直连

    def _report_clearance(self):
        try:
            cookies = {c["name"]: c["value"] for c in self._ctx.cookies(DOMAIN)}
        except Exception:
            cookies = {}
        if "cf_clearance" in cookies:
            print(">>> [Cloudflare] 已检测到 cf_clearance ✅（本次应无需再验证）")
        else:
            print(">>> [Cloudflare] 未检测到 cf_clearance ⚠️，请先执行 open 手动过验证")

    def _pick_page(self):
        """优先复用 Chrome 里已打开的 dzfwjd 标签页（验证就是在那里通过的）"""
        for p in self._ctx.pages:
            try:
                if not p.is_closed() and SITE_HOST in (p.url or ""):
                    self._own_page = False      # 复用的是你的页面，close() 时不关闭
                    return p
            except Exception:
                continue
        self._own_page = True
        return self._ctx.new_page()
    
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
        print("  ⚠️  检测到 Cloudflare 人机验证页面，脚本已暂停")
        print("  👉  请切到弹出的 Chrome 窗口完成验证（勾选 “确认您是真人 / Verify you are human”）")
        print(f"  ⏳  至少等你 {CHALLENGE_GRACE} 秒，最长等待 {CHALLENGE_WAIT} 秒；通过后自动继续。")
        print(f"      URL: {url}")
        if not self._using_cdp:
            print("-" * 72)
            print("  💡 如果反复转圈过不了，改用【独立 Chrome + CDP 附着】：")
            print(f"       1) python {SCRIPT_NAME} open   （在窗口里手动过验证）")
            print(f"       2) python {SCRIPT_NAME} cdp")
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
        challenge_seen = False
        grace_until = next_click_at = last_tip = 0.0
        stable = 0
        html = ""
        auto_click = AUTO_CLICK_TURNSTILE and not self._using_cdp

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
                if auto_click and time.time() >= next_click_at:
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

    def _browser_get(self, url):
        self._start_browser()
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

    def _browser_bytes(self, url):
        self._start_browser()
        r = self._ctx.request.get(url, headers={"Referer": DOMAIN + "/"},
                                  timeout=REQUEST_TIMEOUT * 1000)
        if r.status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status >= 400:
            raise FetchError(f"HTTP {r.status}: {url}")
        body = r.body()
        if not looks_like_image(body, r.headers.get("content-type", "")):
            raise FetchError("浏览器通道返回的也不是有效图片")
        return body

    def close(self):
        try:
            if self._using_cdp:
                if self._own_page and self._page and not self._page.is_closed():
                    self._page.close()
            elif self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = self._page = self._browser = None


_fetcher = HybridFetcher()
atexit.register(_fetcher.close)


def fetch(url, is_binary=False):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if is_binary:
                return _fetcher.get_bytes(url)
            prefer_browser = BROWSER_ON_LAST_RETRY and attempt == MAX_RETRIES and attempt > 1
            return _fetcher.get_html(url, prefer_browser=prefer_browser)
        except NoRetryFetchError:
            raise
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                if "验证" in str(e) or "429" in str(e):
                    wait = max(wait, 15)
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    raise last_err if last_err else FetchError(f"请求失败: {url}")


# ==========================================================
#                    探测：站点是否有 Cloudflare
# ==========================================================
def probe_site():
    print(f">>> [探测] 目标站点: {DOMAIN}")
    s = None
    for imp in FAST_IMPERSONATE_CANDIDATES:
        if not _imp_supported(imp):
            continue
        try:
            s = cffi.Session(impersonate=imp)
            s.headers.update(BASE_HEADERS)
            s.get(DOMAIN + "/", timeout=REQUEST_TIMEOUT)
            print(f"    TLS 指纹: {imp}")
            break
        except Exception as e:
            if "impersonat" in str(e).lower():
                s = None
                continue
            break
    if s is None:
        print("    ✗ 无法创建 curl_cffi 会话")
        return

    any_cf, any_chl, any_ok = False, False, False
    for url in [DOMAIN + "/", LIST_SOURCES[0][0]]:
        try:
            r = s.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except Exception as e:
            print(f"    ✗ {url} 请求异常: {e}")
            continue
        h = {k.lower(): v for k, v in r.headers.items()}
        server = h.get("server", "")
        is_cf = "cloudflare" in server.lower() or "cf-ray" in h
        text = HybridFetcher._decode(r)
        chl = h.get("cf-mitigated", "").lower() == "challenge" or looks_blocked(text) or r.status_code in (403, 503)
        any_cf |= is_cf
        any_chl |= chl
        any_ok |= (r.status_code == 200 and not chl)
        print(f"    - {url}\n      HTTP {r.status_code} | server={server or '-'} | cf-ray={h.get('cf-ray', '-')}"
              f" | 长度={len(text)} | 最终URL={r.url} | 挑战页={'是' if chl else '否'}")

    print("\n>>> [结论]")
    if any_chl:
        print("    ⚠️ 直连被拦（挑战/验证页）。正常运行时脚本会弹出独立 Chrome 让你验证，通过后 cookie 同步回直连。")
    elif any_cf:
        print("    ℹ️ 站点走 Cloudflare CDN，但目前没有触发挑战，直连可用；万一被拦会自动切浏览器。")
    elif any_ok:
        print("    ✅ 未发现 Cloudflare，curl_cffi 直连即可。")
    else:
        print("    ✗ 没有拿到有效响应，请检查网络/代理。")


# ==========================================================
#                        文本工具
# ==========================================================
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
    s = s.replace("・", "·").replace("‧", "·").replace("•", "·")
    s = s.replace("\xa0", " ").replace("\u3000", " ")
    s = re.sub(r"[，；;]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·")
    return s

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

_SEASON_TOKEN = r"第[0-9零一二三四五六七八九十百两〇]+季"

def normalize_title(raw):
    """'造雨人第二季' -> '造雨人 第二季'；'治安官之乡第2季免费观看' -> '治安官之乡 第二季'"""
    t = normalize_text(raw or "")
    if not t:
        return ""
    t = re.sub(r"\s*(全集)?(免费观看|在线观看|在线播放)$", "", t).strip()
    t = re.sub(r"第\s*(\d+)\s*季", lambda m: f"第{num_to_chinese(m.group(1))}季", t)
    t = re.sub(rf"(?<=\S)({_SEASON_TOKEN})(?=$|\s|[\[［(（:：])", r" \1", t)
    return re.sub(r"\s+", " ", t).strip()

def extract_year(date_val):
    m = re.search(r"(19|20)\d{2}", str(date_val or ""))
    return m.group(0) if m else ""

def safe_filename(url):
    return os.path.basename(url.split("?")[0].split("#")[0])

def _C(name):
    """class 名忽略大小写精确匹配（BeautifulSoup 会对每个 class 单独匹配）"""
    return re.compile(rf"^{re.escape(name)}$", re.I)


# ==========================================================
#                  集数 / info / 排序规则
# ==========================================================
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

_DATE_SEP_RE = re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})")
_DATE_COMPACT_RE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")

def get_max_episode_number(episodes):
    if not episodes:
        return 0
    names = [str(n) for n in episodes.keys()]

    date_vals = []
    for n in names:
        if re.search(r"第\s*\d+\s*[集期话話]", n):
            continue
        m = _DATE_SEP_RE.search(n)
        if m:
            date_vals.append(int(f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"))
            continue
        m = _DATE_COMPACT_RE.search(n)
        if m:
            date_vals.append(int(m.group(1) + m.group(2) + m.group(3)))
    if date_vals and len(date_vals) * 2 >= len(names):
        return max(date_vals)

    se_pairs = []
    for name in names:
        m = re.search(r'S(\d+)E(\d+)', name, re.IGNORECASE)
        if m:
            se_pairs.append((int(m.group(1)), int(m.group(2))))
    if se_pairs:
        ms = max(s for s, _ in se_pairs)
        return max(e for s, e in se_pairs if s == ms)

    sp = []
    for name in names:
        m = re.search(r'第\s*(\d+)\s*季.*?第\s*(\d+)\s*[集期话話]', name)
        if m:
            sp.append((int(m.group(1)), int(m.group(2))))
    if sp:
        ms = max(s for s, _ in sp)
        return max(e for s, e in sp if s == ms)

    max_num = 0
    for name in names:
        m = (re.search(r'(\d+)\s*[集期话話]', name) or re.search(r'第\s*(\d+)', name)
             or re.search(r'(\d+)', name))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num

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

def make_series_info(episodes, group, old_info=""):
    n = get_max_episode_number(episodes)
    if n <= 0:
        return ""
    unit = get_episode_unit(group, episodes, old_info)
    if re.fullmatch(r"(19|20)\d{6}", str(n)):
        return f"更新至{n}期"
    return make_episode_info(n, unit)

def resolve_insert_position_with_shangxidq(playlist, new_episodes, default_insert_pos=None, group="", log=print):
    """新增渠道时：本站集数 >= shangxidq 集数，则必须排在 shangxidq 之前"""
    target_pos = len(playlist) if default_insert_pos is None else max(0, min(default_insert_pos, len(playlist)))
    gidx = next((i for i, pl in enumerate(playlist)
                 if str(pl.get("name", "")).strip().lower() == TARGET_COMPARE_CHANNEL.lower()), None)
    if gidx is not None:
        cnt_g = get_effective_episode_count(playlist[gidx].get("episodes", {}), group=group)
        cnt_s = get_effective_episode_count(new_episodes, group=group)
        if cnt_s >= cnt_g:
            if target_pos > gidx:
                log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) >= {TARGET_COMPARE_CHANNEL}({cnt_g})，"
                    f"插入位置由第 {target_pos + 1} 位提前至第 {gidx + 1} 位")
                target_pos = gidx
        else:
            log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) < {TARGET_COMPARE_CHANNEL}({cnt_g})，保持第 {target_pos + 1} 位")
    return target_pos

def has_tc_keyword(text: str) -> bool:
    if not text:
        return False
    upper = str(text).upper()
    return any(kw.upper() in upper for kw in QIANGXIAN_KEYWORDS)

def is_in_tc_lock_list(name: str) -> bool:
    if not name or not TC_LOCK_NAMES:
        return False
    clean = re.sub(r"\s+", "", str(name)).lower()
    return any(re.sub(r"\s+", "", str(i)).lower() == clean for i in TC_LOCK_NAMES)

def is_valid_episode_name(name):
    if not name or name in INVALID_EPISODE_NAMES:
        return False
    return not re.match(r"^更新[至到]", name)

def filter_episodes(eps):
    return {k: v for k, v in eps.items() if is_valid_episode_name(k)}


# ==========================================================
#                    url 键 / 去重匹配
# ==========================================================
def _is_url_key(k):
    return k == "url" or bool(re.match(r"^url\d+$", str(k)))

def _url_keys_sorted(existing):
    return sorted(
        [k for k in existing.keys() if _is_url_key(k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

def _site_url_list(existing):
    """记录里所有本站详情页链接（按 url, url1, url2 ... 的顺序）"""
    return [existing[k] for k in _url_keys_sorted(existing) if is_site_url(existing.get(k, ""))]

def _ensure_site_url(existing, sub_url):
    """确保 sub_url 已登记在记录的 url / urlN 键中，返回 (键名, 是否本次新增)"""
    url_keys = _url_keys_sorted(existing)
    target = normalize_url(sub_url)
    for k in url_keys:
        if normalize_url(str(existing.get(k) or "")) == target:
            return k, False
    for k in url_keys:
        if not str(existing.get(k) or "").strip():
            existing[k] = sub_url
            return k, True
    max_num = 0
    for k in url_keys:
        m = re.match(r"^url(\d+)$", k)
        if m:
            max_num = max(max_num, int(m.group(1)))
    new_key = f"url{max_num + 1}" if url_keys else "url"
    last_key = url_keys[-1] if url_keys else None
    ordered, inserted = {}, False
    for k, v in existing.items():
        ordered[k] = v
        if k == last_key:
            ordered[new_key] = sub_url
            inserted = True
    if not inserted:
        ordered[new_key] = sub_url
    existing.clear()
    existing.update(ordered)
    return new_key, True

def normalize_url(u):
    if not u:
        return ""
    u = str(u).strip()
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    u = re.sub(r"^www\.", "", u, flags=re.IGNORECASE)
    return u.rstrip("/")

def clean_season_one(s):
    return re.sub(r"(?:第[一1]季)$", "", s).strip() if s else ""

def name_key(s):
    """用于去重匹配的规范化键：NFKC 统一全/半角，去掉所有空白和标点，忽略大小写"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\W_]+", "", s)
    return s.lower()

def find_existing_global(data, name, sub_url, log=print):
    norm_name = name_key(name)
    base_name = clean_season_one(norm_name)
    norm_sub = normalize_url(sub_url)

    if norm_sub:
        for group in GROUPS:
            for item in data.get(group, []):
                for k in item.keys():
                    if k == "url" or re.match(r"^url\d+$", k):
                        val = item.get(k, "")
                        if val and normalize_url(val) == norm_sub:
                            if item.get("name", "") != name:
                                log(f"      [URL匹配去重] 已有「{item.get('name', '')}」 ↔ 抓取「{name}」")
                            return group, item

    for group in GROUPS:
        for item in data.get(group, []):
            ex_raw = item.get("name", "")
            ex_norm = name_key(ex_raw)
            if ex_norm == norm_name:
                log(f"      [名称去重（忽略标点空格）] 已有「{ex_raw}」 ↔ 抓取「{name}」")
                return group, item
            ex_base = clean_season_one(ex_norm)
            if base_name and ex_base and base_name == ex_base:
                log(f"      [季数兼容去重] 已有「{ex_raw}」 ↔ 抓取「{name}」")
                return group, item
    return None, None


# ==========================================================
#                        列表页解析
# ==========================================================
_DETAIL_RE = re.compile(r"/movie/(\d+)\.html")
_PLAY_RE   = re.compile(r"/movie-play/(\d+)-(\d+)-(\d+)\.html")
_LAST_TEXTS = {"尾页", "末页", "最后一页", "最后页", "last", "»»"}
_NEXT_TEXTS = {"下一页", "下页", "next", "›", "»", ">"}

def _vod_id(url):
    m = _DETAIL_RE.search(url or "")
    return m.group(1) if m else ""

def _pick_img(img_tag):
    if not img_tag:
        return ""
    for attr in ("data-src", "data-original", "data-echo", "src"):
        v = (img_tag.get(attr) or "").strip()
        if not v or v.startswith("data:"):
            continue
        low = v.lower()
        if attr == "src" and any(x in low for x in ("loading", "lazy", "placeholder", "blank.")):
            continue
        return v
    return ""

def _parse_tag2(text):
    """'美国／2026' -> ('美国', '2026')"""
    toks = [t for t in re.split(r"[／/|·\s]+", normalize_text(text or "")) if t]
    year = next((t for t in toks if re.fullmatch(r"(19|20)\d{2}", t)), "")
    region = next((t for t in toks if not re.fullmatch(r"\d+", t)), "")
    return region, year

def _make_page_tpl(url, n):
    s = str(n)
    ms = [m for m in re.finditer(r"\d+", url) if m.group(0) == s]
    if not ms:
        return None
    m = ms[-1]
    return url[:m.start()] + "{n}" + url[m.end():]

def _tpl_regex(tpl):
    return re.compile(re.escape(tpl).replace(re.escape("{n}"), r"(\d+)"))

def parse_pager(soup, list_url):
    """自动识别分页：返回 {links: {页码: url}, tpl: 'xxx{n}xxx'|None, total: int|None, next: url|None}"""
    stem = os.path.splitext(os.path.basename(urlparse(list_url).path))[0]
    containers = soup.find_all(class_=re.compile(r"pag", re.I))
    anchors = [a for c in containers for a in c.find_all("a", href=True)]
    if not anchors:
        anchors = soup.find_all("a", href=True)
    links, last_cands, next_url = {}, [], None
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith("javascript") or href.startswith("#"):
            continue
        full = urljoin(DOMAIN, href)
        pu = urlparse(full)
        if stem and stem not in (pu.path + "?" + (pu.query or "")):
            continue
        txt = a.get_text(strip=True)
        tl = txt.lower()
        if txt.isdigit():
            links[int(txt)] = full
        elif tl in _LAST_TEXTS:
            last_cands.append(full)
        elif tl in _NEXT_TEXTS:
            next_url = full
    tpl = None
    for n, u in sorted(links.items()):
        if n >= 2:
            tpl = _make_page_tpl(u, n)
            if tpl:
                break
    total = max(links) if links else None
    if tpl:
        rx = _tpl_regex(tpl)
        for u in last_cands:
            m = rx.fullmatch(u)
            if m:
                total = max(total or 0, int(m.group(1)))
    return {"links": links, "tpl": tpl, "total": total, "next": next_url}

def get_list(page_url, list_url):
    """返回 (items, pager)；items: [(name, info, url, img, year_hint), ...]"""
    html = fetch(page_url)
    soup = BeautifulSoup(html, "lxml")
    scope = soup.find("div", class_=_C("gm-list")) or soup
    items, used = [], set()
    for a in scope.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not _DETAIL_RE.search(href):
            continue
        img_tag = a.find("img")
        if not img_tag:              # 只取带封面的卡片链接（标题链接重复，跳过）
            continue
        url = urljoin(DOMAIN, href)
        key = normalize_url(url)
        if key in used:
            continue
        used.add(key)
        card = a.find_parent("div", class_=_C("item")) or a.parent
        title = a.get("title") or ""
        if not title and card:
            t = card.find("a", class_=_C("title"))
            title = t.get_text(strip=True) if t else ""
        if not title:
            title = img_tag.get("alt", "")
        name = normalize_title(title)
        if not name:
            continue
        tag1 = (card or a).find(class_=_C("tag1"))
        tag2 = (card or a).find(class_=_C("tag2"))
        info = normalize_text(tag1.get_text(strip=True)) if tag1 else ""
        _, year_hint = _parse_tag2(tag2.get_text(strip=True) if tag2 else "")
        img = _pick_img(img_tag)
        items.append((name, info, url, urljoin(DOMAIN, img) if img else "", year_hint))
    return items, parse_pager(soup, list_url)


# ==========================================================
#                   详情页 / 播放页解析
# ==========================================================
_FIELD_PATTERNS = [
    ("主演", r"主\s*演|演\s*员"),
    ("导演", r"导\s*演"),
    ("编剧", r"编\s*剧"),
    ("类型", r"类\s*型|分\s*类"),
    ("地区", r"地\s*区|国\s*家|产\s*地"),
    ("date", r"年\s*份|上\s*映|首\s*播"),
    ("alias", r"别\s*名|又\s*名"),
    ("评分", r"评\s*分|豆\s*瓣"),
    ("资源", r"资\s*源|状\s*态"),
]
_LIST_FIELDS = {"主演", "导演", "编剧", "类型"}
_LIST_SPLIT_RE = re.compile(r"\s*[/,，、|／;；]\s*")

def _detect_field(label):
    for field, pat in _FIELD_PATTERNS:
        if re.search(pat, label or ""):
            return field
    return None

def _split_label(text):
    m = re.match(r"^\s*([^：:]{1,8}?)\s*[：:]\s*(.*)$", text or "", re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)

def _split_people(txt):
    vals = [_clean_val(v) for v in _LIST_SPLIT_RE.split(txt or "")]
    vals = [v for v in vals if v]
    # 只有一个值但内部用空格分隔多个中文名时，再按空格拆（英文名的空格不拆）
    if len(vals) == 1 and " " in vals[0]:
        parts = vals[0].split(" ")
        if len(parts) > 1 and all(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", p) for p in parts):
            vals = [_clean_val(p) for p in parts if _clean_val(p)]
    return vals

def parse_detail_fields(soup):
    res = {"主演": [], "导演": [], "编剧": [], "类型": [], "地区": "", "date": "",
           "alias": "", "评分": "", "资源": ""}
    vod = soup.find("div", class_=_C("gm-vod")) or soup
    more = vod.find("div", class_=_C("more")) or vod
    for div in more.find_all("div", class_=_C("info")):
        if div.find_parent("div", class_=_C("info-box")) or div.find("div", class_=_C("info")):
            continue
        text = normalize_text(div.get_text(" ", strip=True))
        label, value = _split_label(text)
        if not label:
            continue
        field = _detect_field(label)
        if not field:
            continue
        vals = [_clean_val(a.get_text(" ", strip=True)) for a in div.find_all("a")]
        vals = [v for v in vals if v]
        if not vals:
            value = _clean_val(value)
            if not value:
                continue
            vals = _split_people(value) if field in _LIST_FIELDS else [value]
        if not vals:
            continue
        if field in _LIST_FIELDS:
            for v in vals:
                if v not in res[field]:
                    res[field].append(v)
        elif field == "评分":
            m = re.search(r"\d+(?:\.\d+)?", vals[0])
            if m and 0 < float(m.group(0)) <= 10 and not res["评分"]:
                res["评分"] = m.group(0)
        elif field == "地区":
            if not res["地区"]:
                toks = []
                for v in vals:
                    toks.extend(t for t in _LIST_SPLIT_RE.split(v) if _clean_val(t))
                res["地区"] = " / ".join(dict.fromkeys(toks))
        elif field in ("alias", "资源", "date"):
            if not res[field]:
                res[field] = vals[0]
    return res

def parse_intro_box(soup, name=""):
    """返回 (intro, alias, 豆瓣评分)"""
    box = soup.find("div", class_=_C("info-box"))
    if not box:
        return "", "", ""
    parts = []
    for d in box.find_all("div", class_=_C("info")):
        t = normalize_text(d.get_text(" ", strip=True))
        t = re.sub(r"^(剧情)?(简介|介绍)[：:]\s*", "", t)
        t = re.sub(r"\s*(展开全部|收起全部|展开|收起|详情)$", "", t).strip()
        if t and not is_garbled(t) and t not in parts:
            parts.append(t)
    intro = " ".join(parts)
    alias, score = "", ""
    m = re.search(r"又名\s*([^，,。；;]+?)\s*[，,。；;]", intro)
    if m:
        cand = _clean_val(m.group(1))
        if cand and name_key(cand) != name_key(name):
            alias = cand
    m = re.search(r"豆瓣评分\s*([0-9]+(?:\.[0-9]+)?)", intro)
    if m:
        try:
            if 0 < float(m.group(1)) <= 10:
                score = m.group(1)
        except ValueError:
            pass
    return intro, alias, score

def parse_title(soup, default_name):
    h1 = soup.find("h1")
    if not h1:
        return default_name
    for x in h1.find_all(["small", "span"]):
        x.extract()
    return normalize_title(h1.get_text(" ", strip=True)) or default_name

def extract_detail_image(soup):
    thumb = soup.find("div", class_=_C("gm-thumb"))
    img = (thumb.find("img") if thumb else None) or soup.select_one(".gm-vod img")
    return _pick_img(img)

def extract_play_url(soup, vid):
    anchors = soup.find_all("a", class_=_C("btn-play"), href=True) + \
              soup.find_all("a", href=_PLAY_RE)
    for a in anchors:
        m = _PLAY_RE.search(a.get("href") or "")
        if m and (not vid or m.group(1) == vid):
            return urljoin(DOMAIN, a["href"])
    return f"{DOMAIN}/movie-play/{vid}-1-1.html" if vid else ""

def _clean_line_name(s):
    return normalize_text(s or "").strip("'\"‘’“” ")

def to_fullwidth_colon(s: str) -> str:
    if not s:
        return s
    return re.sub(r"(?<!\d):(?!\d)", "：", s)

def in_name_list(name, names):
    key = to_fullwidth_colon(str(name or "")).strip()
    return any(key == to_fullwidth_colon(str(n)).strip() for n in names)

def _collect_eps(container):
    eps = {}
    for a in container.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        ep = normalize_text(a.get_text(" ", strip=True))
        if not href or href.lower().startswith("javascript") or not ep or ep in eps:
            continue
        eps[ep] = urljoin(DOMAIN, href)
    return filter_episodes(eps)

def extract_playlists(soup, vid=""):
    """解析播放页 #dom-source：线路名(.hd-item) 与选集列表(.source .list) 按顺序一一对应"""
    blocks = []
    box = soup.find(id="dom-source")
    names = []
    if box:
        hd = box.find(class_=_C("hd"))
        if hd:
            items = hd.find_all(class_=_C("hd-item")) or hd.find_all(["span", "a", "li"])
            names = [_clean_line_name(x.get_text(" ", strip=True)) for x in items]
        src = box.find(class_=_C("source")) or box
        lists = src.find_all("div", class_=_C("list"))
        for i, lst in enumerate(lists):
            eps = _collect_eps(lst)
            if not eps:
                continue
            name = names[i] if i < len(names) and names[i] else f"线路{i + 1}"
            blocks.append((name, eps))

    if not blocks:   # 兜底：按 /movie-play/ID-SID-EP.html 的 SID 分组
        groups = {}
        for a in soup.find_all("a", href=_PLAY_RE):
            m = _PLAY_RE.search(a["href"])
            if vid and m.group(1) != vid:
                continue
            ep = normalize_text(a.get_text(" ", strip=True))
            if ep:
                groups.setdefault(m.group(2), {}).setdefault(ep, urljoin(DOMAIN, a["href"]))
        for sid in sorted(groups, key=int):
            eps = filter_episodes(groups[sid])
            if eps:
                idx = int(sid) - 1
                nm = names[idx] if 0 <= idx < len(names) and names[idx] else f"线路{sid}"
                blocks.append((nm, eps))

    result, used = [], set()
    for name, eps in blocks:
        final = PLAYLIST_NAME_TEMPLATE.format(line=name)
        base, n = final, 2
        while final in used:
            final = f"{base}{n}"
            n += 1
        used.add(final)
        result.append({"name": final, "episodes": eps, PLAYLIST_SOURCE_FIELD: SITE_KEY})
    return result

def parse_detail(sub_url, default_name, default_info="", list_img=""):
    """抓详情页。返回 (rec, play_url, inline_playlists)"""
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")
    vid = _vod_id(sub_url)
    name = parse_title(soup, default_name)
    fields = parse_detail_fields(soup)
    intro, alias_i, score_i = parse_intro_box(soup, name)
    alias = fields["alias"] or (alias_i if EXTRACT_ALIAS_FROM_INTRO else "")
    score = fields["评分"] or (score_i if EXTRACT_ALIAS_FROM_INTRO else "")
    img_url = list_img or extract_detail_image(soup)
    if img_url:
        img_url = urljoin(DOMAIN, img_url)
    inline = extract_playlists(soup, vid) if soup.find(id="dom-source") else []
    play_url = extract_play_url(soup, vid)
    rec = {
        "name":   name,
        "url":    sub_url,
        "info":   default_info or fields["资源"],
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   " / ".join(fields["导演"]),     # 导演为单一字符串
        "编剧":   fields["编剧"],
        "主演":   fields["主演"],
        "类型":   fields["类型"],
        "地区":   fields["地区"],
        "date":   fields["date"],
        "date_re": fields["date"],
        "alias":  alias,
        "intro":  intro,
        "评分":   {"豆瓣": score, "IMDB": ""},
        "playlist": [],
    }
    return rec, play_url, inline

def parse_play(play_url, vid=""):
    html = fetch(play_url)
    soup = BeautifulSoup(html, "lxml")
    return extract_playlists(soup, vid)

def download_and_localize_image(img_url):
    if not img_url:
        return ""
    fn = safe_filename(img_url)
    if not fn:
        return ""
    local_path = os.path.join(IMG_DIR, fn)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return fn
    try:
        content = fetch(img_url, is_binary=True)
        os.makedirs(IMG_DIR, exist_ok=True)
        tmp = local_path + ".part"
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, local_path)
        print(f"  [图片] 已下载 -> {fn}")
        return fn
    except Exception as e:
        print(f"  [图片下载失败] {img_url}: {e}")
        return ""


# ==========================================================
#                        合并逻辑
# ==========================================================
def is_own_playlist(pl):
    return isinstance(pl, dict) and pl.get(PLAYLIST_SOURCE_FIELD) == SITE_KEY

def _is_retired(pl):
    return (RETIRED_POLICY in ("demote", "remove") and isinstance(pl, dict)
            and not is_own_playlist(pl) and pl.get(PLAYLIST_SOURCE_FIELD) in RETIRED_SOURCES)

def _dump(obj, drop_url_keys=False):
    if drop_url_keys and isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if not _is_url_key(k)}
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)

def _pl_origin(pl, legacy_origin=""):
    return normalize_url(pl.get(PLAYLIST_ORIGIN_FIELD) or legacy_origin or "")

def _ep_strength(eps, group):
    eps = eps or {}
    return (get_effective_episode_count(eps, group=group), len(eps))

def sort_own_lines_by_count(playlist, group):
    """本站线路集数少于整体最大集数时，移到所有集数更多的线路之后（只移动本站线路）"""
    result = list(playlist)
    if len(result) < 2:
        return result

    def cnt(pl):
        return get_effective_episode_count(pl.get("episodes") or {}, group=group)

    max_cnt = max(cnt(p) for p in result)
    for pl in [p for p in result if is_own_playlist(p)]:
        c = cnt(pl)
        if c >= max_cnt:
            continue
        idx = next(i for i, p in enumerate(result) if p is pl)
        result.pop(idx)
        bigger = [i for i, p in enumerate(result) if cnt(p) > c]
        if bigger:
            result.insert(bigger[-1] + 1, pl)
        else:
            result.insert(idx, pl)
    return result

def _best_eps(pls):
    best, best_n = {}, -1
    for pl in pls:
        eps = pl.get("episodes", {}) or {}
        n = get_max_episode_number(eps)
        if n > best_n or (n == best_n and len(eps) > len(best)):
            best, best_n = eps, n
    return best

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

    old_date, new_date = existing.get("date", ""), rec.get("date", "")
    if new_date and (not old_date or len(str(new_date)) > len(str(old_date))):
        existing["date"] = new_date
        changed = True
        log(f"      [字段更新] 更新「date」: 「{old_date}」 -> 「{new_date}」")

    score = existing.setdefault("评分", {"豆瓣": "", "IMDB": ""})
    new_db = (rec.get("评分") or {}).get("豆瓣", "")
    if isinstance(score, dict) and new_db and not score.get("豆瓣"):
        score["豆瓣"] = new_db
        changed = True
        log(f"      [字段更新] 补充豆瓣评分: {new_db}")
    return changed

def merge_into_existing(existing, rec, sub_url, matched_group, log):
    """
    把本站多条线路合并进已有记录。返回 (status, message)；status ∈ changed / moved / no_change / tc_locked
    额外：RETIRED_SOURCES（312f）的失效线路按 RETIRED_POLICY 移到末尾或删除。
    """
    before = _dump(existing)
    before_core = _dump(existing, drop_url_keys=True)
    name = existing.get("name") or rec.get("name", "")
    playlist = existing.get("playlist")
    if not isinstance(playlist, list):
        playlist = []
    old_order = [_dump(p) for p in playlist]

    own = [pl for pl in playlist if is_own_playlist(pl)]
    retired = [pl for pl in playlist if _is_retired(pl)]
    others = [pl for pl in playlist if not is_own_playlist(pl) and not _is_retired(pl)]
    own_anchor, cnt = None, 0
    for pl in playlist:
        if is_own_playlist(pl):
            own_anchor = cnt
            break
        if not _is_retired(pl):
            cnt += 1

    new_pls = rec.get("playlist", [])
    cur = normalize_url(sub_url)
    site_urls_before = _site_url_list(existing)
    legacy_origin = site_urls_before[0] if site_urls_before else ""

    # —— TC 锁定 ——
    if own and is_in_tc_lock_list(name):
        old_tc = any(has_tc_keyword(ep) for pl in own for ep in (pl.get("episodes") or {}))
        new_tc = any(has_tc_keyword(ep) for pl in new_pls for ep in (pl.get("episodes") or {}))
        if old_tc and not new_tc:
            return "tc_locked", f"「{name}」命中TC名单，原有本站线路含TC选集，新抓到为非TC版本，锁定不更新"

    # —— 逐条线路合并 ——
    new_by_name = {}
    for npl in new_pls:
        new_by_name.setdefault(npl.get("name"), npl)
    merged, handled = [], set()
    n_keep = n_upd = n_add = n_drop = 0

    for opl in own:
        lname = opl.get("name")
        if lname in handled:
            merged.append(opl)
            continue
        handled.add(lname)
        same_origin = _pl_origin(opl, legacy_origin) == cur
        npl = new_by_name.get(lname)

        if npl is None:
            if same_origin and not KEEP_MISSING_LINES:
                log(f"      [线路下线] 「{lname}」在其来源详情页已不存在，删除")
                n_drop += 1
                continue
            if same_origin:
                log(f"      [保护] 线路「{lname}」本次未抓到，保留原有数据")
            merged.append(opl)
            n_keep += 1
            continue

        old_eps = opl.get("episodes") or {}
        new_eps = npl.get("episodes") or {}
        if new_eps == old_eps:
            merged.append(opl)
            n_keep += 1
            continue

        s_new = _ep_strength(new_eps, matched_group)
        s_old = _ep_strength(old_eps, matched_group)
        detail = f"集数 {s_old[0]}→{s_new[0]}（选集 {s_old[1]}→{s_new[1]} 条）"
        if s_new > s_old:
            src = "" if same_origin else f"，来自同一视频的另一详情页 {sub_url}"
            log(f"      [线路更新] 「{lname}」{detail}{src}")
            merged.append(npl)
            n_upd += 1
        elif same_origin and s_new == s_old:
            log(f"      [线路刷新] 「{lname}」集数不变但选集链接有变化，按原详情页刷新")
            merged.append(npl)
            n_upd += 1
        else:
            if same_origin:
                log(f"      [保护] 线路「{lname}」本次集数少于已有（{detail}），保留原有")
            else:
                log(f"      [多链接] 线路「{lname}」集数未超过已有（{detail}），保持原选集链接不变")
            merged.append(opl)
            n_keep += 1

    for npl in new_pls:
        lname = npl.get("name")
        if lname in handled:
            continue
        handled.add(lname)
        if own:
            log(f"      [线路新增] 「{lname}」（{len(npl.get('episodes') or {})} 集，来自 {sub_url}）")
        merged.append(npl)
        n_add += 1

    old_max_all = max((get_max_episode_number(pl.get("episodes", {}) or {})
                       for pl in playlist if isinstance(pl, dict)), default=0)
    best_new = _best_eps(merged)
    new_max = get_max_episode_number(best_new)
    other_max, idx_other_max = 0, -1
    for i, pl in enumerate(others):
        m = get_max_episode_number(pl.get("episodes", {}) or {})
        if m > other_max:
            other_max, idx_other_max = m, i

    is_series = matched_group in ("Drama", "Anime")
    if new_max > other_max:
        target = 0
    elif is_series and idx_other_max >= 0:
        target = idx_other_max + 1
    elif own_anchor is not None:
        target = own_anchor
    else:
        target = len(others)
    if own_anchor is None:
        target = resolve_insert_position_with_shangxidq(others, best_new, default_insert_pos=target,
                                                     group=matched_group, log=log)
    target = max(0, min(target, len(others)))
    live = others[:target] + merged + others[target:]
    live = sort_own_lines_by_count(live, matched_group)

    # —— 失效站点线路 ——
    n_retired_drop = 0
    if retired and RETIRED_POLICY == "remove":
        n_retired_drop = len(retired)
        log(f"      [失效渠道] 删除 {'/'.join(sorted(RETIRED_SOURCES))} 的 {n_retired_drop} 条失效线路")
        tail = []
    else:
        tail = retired
        if tail:
            was_tail = all(a is b for a, b in zip(playlist[-len(tail):], tail))
            if not was_tail:
                log(f"      [失效渠道] {'/'.join(sorted(RETIRED_SOURCES))} 的 {len(tail)} 条线路已失效，移到末尾")
    existing["playlist"] = live + tail

    url_key, url_added = _ensure_site_url(existing, sub_url)
    if url_added and site_urls_before:
        log(f"      [多链接登记] 本站第 {len(site_urls_before) + 1} 个详情页指向同一视频 -> {url_key}: {sub_url}")

    old_info = existing.get("info", "") or ""
    if matched_group in ("Drama", "Anime", "Show"):
        if new_max > 0 and (new_max > old_max_all or not old_info):
            cand = make_series_info(best_new, matched_group, old_info)
            if cand and cand != old_info:
                existing["info"] = cand
                log(f"      ✅[info更新] 本站最大集数 {new_max} > 历史最大 {old_max_all}：「{old_info}」 -> 「{cand}」")
    elif not old_info and rec.get("info"):
        existing["info"] = rec["info"]

    merge_missing_fields(existing, rec, log)

    new_order = [_dump(p) for p in existing["playlist"]]
    pure_move = (sorted(old_order) == sorted(new_order)) and (old_order != new_order)
    no_content_change = not (n_upd or n_add or n_drop or n_retired_drop)
    if pure_move and no_content_change:
        extra = f"，并登记多链接 {url_key}" if url_added else ""
        return "moved", f"线路位置调整为第 {target + 1} 位（无新增线路，集数无变化）{extra}"
    is_mirror_page = bool(own) and all(_pl_origin(pl, legacy_origin) != cur for pl in merged)
    after = _dump(existing)
    if after == before:
        if is_mirror_page:
            return "no_change", "同一视频的另一详情页，线路无新增、集数未超过已有，保持原链接"
        return "no_change", ""

    core_changed = _dump(existing, drop_url_keys=True) != before_core
    if not core_changed:
        return "changed", (f"登记多链接 {url_key}（本站共 {len(_site_url_list(existing))} 个详情页指向同一视频），"
                           f"播放线路保持不变")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if matched_group in ("Drama", "Anime", "Show"):
        if new_max > old_max_all:
            existing["update"] = now
    else:
        existing["update"] = now

    action = "新增渠道" if own_anchor is None else "更新渠道"
    return "changed", (f"{action}：{SITE_KEY} {len(merged)} 条线路（保留 {n_keep} / 更新 {n_upd} / 新增 {n_add}"
                       + (f" / 删除 {n_drop}" if n_drop else "")
                       + (f" / 清理失效 {n_retired_drop}" if n_retired_drop else "") +
                       f"，{url_key}）放在第 {target + 1} 位；本站最大集数 {new_max}，其他渠道最大 {other_max}")

def region_block_reason(rec, filter_regions):
    region = (rec.get("地区") or "").strip()
    tokens = [t for t in re.split(r"[\s/,，、|／]+", region) if t]
    hit = next((t for t in tokens if t in filter_regions), None)
    if hit:
        return f"地区为「{region}」，命中过滤词「{hit}」"
    if not tokens or region == "未知":
        type_text = " ".join(rec.get("类型") or [])
        kw = next((k for k in ["国产", "中国", "大陆", "内地", "国漫", "国创"] if k in type_text), None)
        if kw:
            return f"地区未知，但类型「{type_text}」含「{kw}」，判定为国产内容"
    return None


# ==========================================================
#                        单条处理
# ==========================================================
def process_item(store, idx_tag, item, group, filter_regions):
    """返回统计键：new / updated / moved / nochange / skip / fail"""
    name, info, url, img, year_hint = item
    if in_name_list(name, BLACKLIST_NAMES):
        print(f"  {idx_tag} {name} [名称黑名单，跳过]")
        return "skip"
    if any(b in url for b in BLACKLIST_URLS if b):
        print(f"  {idx_tag} {name} [URL 黑名单，跳过]")
        return "skip"

    allowed_years = ALLOWED_YEARS_BY_GROUP.get(group, ALLOWED_YEARS)
    if PREFILTER_BY_LIST_YEAR and year_hint and year_hint not in allowed_years:
        print(f"  {idx_tag} {name} [列表年份 {year_hint} 不在 {sorted(allowed_years)} 内，跳过]")
        return "skip"

    header = f"  {idx_tag} {name}  [{info}]"
    buf = []

    def flush(*extra):
        print(header)
        for line in buf:
            print(line)
        for line in extra:
            print(line)

    # —— 1. 详情页 ——
    try:
        rec, play_url, inline_pls = parse_detail(url, name, info, list_img=img)
    except Exception as e:
        flush(f"    ✗ 详情页抓取失败: {e}")
        return "fail"

    real_name = rec["name"]
    if in_name_list(real_name, BLACKLIST_NAMES):
        flush(f"    - 跳过：真实名称「{real_name}」在黑名单中")
        return "skip"

    year = extract_year(rec.get("date"))
    if year not in allowed_years:
        flush(f"    - 跳过：年份「{rec.get('date') or '空'}」不在 {sorted(allowed_years)} 内")
        return "skip"

    peek_group, peek_existing = find_existing_global(store.data, real_name, url, buf.append)
    if peek_existing and peek_group != group:
        buf.append(f"    * 该资源已存在于「{peek_group}」分类，将按「{peek_group}」规则处理")

    if in_name_list(real_name, WHITELIST_NAMES):
        buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
    elif peek_existing and group in REGION_BYPASS_FOR_EXISTING:
        buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
    else:
        reason = region_block_reason(rec, filter_regions)
        if reason:
            flush(f"    - 跳过：{reason}")
            return "skip"

    # —— 2. 播放页（过滤通过后才请求） ——
    new_pls = inline_pls
    if not new_pls:
        if not play_url:
            flush("    ! 详情页没有找到播放入口，跳过")
            return "fail"
        try:
            new_pls = parse_play(play_url, _vod_id(url))
        except Exception as e:
            flush(f"    ✗ 播放页抓取失败: {e}")
            return "fail"
    for pl in new_pls:
        pl[PLAYLIST_ORIGIN_FIELD] = url
    rec["playlist"] = new_pls

    if not new_pls:
        flush(f"    ! 无播放源，跳过（播放页: {play_url}）")
        return "fail"
    max_len = max(len(pl["episodes"]) for pl in new_pls)
    line_desc = ", ".join("{}({})".format(pl["name"], len(pl["episodes"])) for pl in new_pls)
    buf.append(f"    [线路] {line_desc}")

    limit = MAX_EPISODES_BY_GROUP.get(group)
    if limit and max_len > limit:
        flush(f"    - 跳过：「{real_name}」属于「{group}」，集数 {max_len} 超过 {limit} 上限")
        return "skip"

    # —— 3. 图片（锁外下载） ——
    local_img = ""
    if rec.get("image") and (not peek_existing or not peek_existing.get("image")):
        local_img = download_and_localize_image(rec["image"])

    # —— 4. 写入 ——
    status, msg, mg = "fail", "", group
    with store.transaction() as tx:
        mg, existing = find_existing_global(tx.data, real_name, url, lambda *_: None)
        if existing is None:
            rec["name"] = to_fullwidth_colon(rec["name"])
            rec["image"] = local_img
            if group in ("Drama", "Anime", "Show"):
                cand = make_series_info(_best_eps(new_pls), group, rec.get("info", ""))
                if cand:
                    rec["info"] = cand
            tx.data.setdefault(group, []).append(rec)
            tx.dirty = True
            status, mg = "new", group
        else:
            if local_img and not existing.get("image"):
                existing["image"] = local_img
                buf.append(f"      [字段更新] 补充封面: {local_img}")
            status, msg = merge_into_existing(existing, rec, url, mg, buf.append)
            if status in ("changed", "moved") or (local_img and existing.get("image") == local_img and status == "no_change"):
                tx.dirty = True
                if status == "no_change":
                    status, msg = "changed", "仅补充封面"
    if tx.dirty and not tx.saved:
        buf.append("    ⚠️ 本次修改未能写盘（见上方提示）")

    if status == "new":
        flush(f"    ✅ 新增 -> {group}（{len(new_pls)} 条线路，最多 {max_len} 集）[URL: {url}]")
        return "new"
    if status == "moved":
        flush(f"    ↔ 位置调整({mg})：{msg}")
        return "moved"
    if status == "changed":
        flush(f"    ✅ 更新({mg})：{msg}")
        return "updated"
    if status == "tc_locked":
        flush(f"    🛡️ [TC锁定跳过] {msg}")
        return "skip"
    print(f"  {idx_tag} {real_name} - 无变更" + (f"（{msg}）" if msg else ""))
    return "nochange"


def process_list_source(store, list_url, group, label, max_pages, seen, stats):
    filter_regions = FILTER_REGIONS_OVERRIDE.get(list_url) or FILTER_REGIONS_BY_GROUP.get(group, FILTER_REGIONS)
    known_links, tpl, total, next_url = {}, None, None, None
    for page in range(1, max_pages + 1):
        if page == 1:
            purl = list_url
        else:
            if total and page > total:
                print(f"  [翻页] 站点只有 {total} 页，停止")
                break
            purl = known_links.get(page) or (tpl.replace("{n}", str(page)) if tpl else None) or next_url
            if not purl:
                print(f"  [翻页] 页面上没有识别到第 {page} 页的链接，停止翻页")
                break
        print(f"\n[抓取] {label} 第 {page}/{max_pages} 页 -> {group}  ({purl})")
        try:
            items, pager = get_list(purl, list_url)
        except Exception as e:
            print(f"  ✗ 列表抓取失败: {e}")
            stats["fail"] += 1
            break      # 列表页失败：后面的页链接也依赖它，直接停止该分类
        known_links.update(pager["links"])
        tpl = tpl or pager["tpl"]
        if pager["total"]:
            total = max(total or 0, pager["total"])
        next_url = pager["next"]
        if not items:
            print("  本页无条目，停止翻页")
            break
        if page > 1 and all(normalize_url(it[2]) in seen for it in items):
            print("  本页条目全部已处理过（疑似翻页无效），停止翻页")
            break
        print(f"  共发现 {len(items)} 条" + (f"（站点共 {total} 页）" if page == 1 and total else ""))
        for i, it in enumerate(items, 1):
            key = normalize_url(it[2])
            if key in seen:
                print(f"  ({i}/{len(items)}) {it[0]} [本轮已处理过，跳过]")
                continue
            seen.add(key)
            result = process_item(store, f"({i}/{len(items)})", it, group, filter_regions)
            stats[result] += 1
            if result != "skip" or not (PREFILTER_BY_LIST_YEAR and it[4]):
                time.sleep(SLEEP_BETWEEN)       # 列表预过滤跳过的条目没有发请求，不用等


# ==========================================================
#                        补全模式
# ==========================================================
def _needs_backfill(item):
    return any(not item.get(f) for f in ("导演", "主演", "类型", "地区", "intro", "image"))

def backfill_existing(store):
    print(f"\n[补全模式] 扫描已有 {SITE_KEY} 记录中字段缺失的资源 ...")
    cands = []
    for group in GROUPS:
        for item in store.data.get(group, []):
            targets = _site_url_list(item)
            if targets and _needs_backfill(item):
                cands.append((group, item.get("name", ""), targets, not item.get("image")))
    updated = 0
    for group, name, targets, need_img in cands:
        rec, used = None, None
        for target in targets:
            print(f"  [{group}] 补全: {name}  <- {target}")
            try:
                rec, _, _ = parse_detail(target, name, "")
                used = target
                break
            except Exception as e:
                print(f"    ✗ 失败: {e}" + ("，尝试下一个链接" if target != targets[-1] else ""))
                time.sleep(SLEEP_BETWEEN)
        if rec is None:
            continue
        local_img = download_and_localize_image(rec["image"]) if (need_img and rec.get("image")) else ""
        with store.transaction() as tx:
            _, item = find_existing_global(tx.data, name, used, lambda *_: None)
            if item is not None:
                changed = merge_missing_fields(item, rec, lambda m: print(m))
                if local_img and not item.get("image"):
                    item["image"] = local_img
                    changed = True
                if changed:
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    tx.dirty = True
                    updated += 1
                    print("    ✅ 已补全")
                else:
                    print("    - 未发现可补全内容")
        time.sleep(SLEEP_BETWEEN)
    print(f"\n[补全模式] 完成：扫描 {len(cands)} 条候选，成功更新 {updated} 条。")


# ==========================================================
#                        命令行 & 主流程
# ==========================================================
def parse_cli():
    global USE_CDP, HEADLESS, BROWSER_ONLY, AUTO_CLICK_TURNSTILE, AUTO_LAUNCH_CDP, USE_COOKIE_CACHE
    args = [a.lower().lstrip("-") for a in sys.argv[1:]]
    if "cdp" in args:
        USE_CDP = True
        AUTO_LAUNCH_CDP = False          # 只附着，端口不通就报错，绝不自己再开一个 Chrome
        AUTO_CLICK_TURNSTILE = False
        print(">>> [模式] CDP：只附着到已运行的调试 Chrome（不自动启动、不自动点击）")
    if "pw" in args:
        AUTO_LAUNCH_CDP = False
        print(">>> [模式] 浏览器兜底改用 Playwright 自启 Chrome")
    if "headless" in args:
        HEADLESS = True
        AUTO_LAUNCH_CDP = False
        print(">>> [模式] Playwright 无头模式（可能过不了 Cloudflare）")
    if "browser" in args:
        BROWSER_ONLY = True
        _fetcher.direct_disabled = True
        print(">>> [模式] 全程真实浏览器（不走直连）")
    if "click" in args:
        AUTO_CLICK_TURNSTILE = True
    if "nocache" in args:
        USE_COOKIE_CACHE = False
        print(">>> [模式] 不使用本地 cookie 缓存")

    for a in args:
        m = re.fullmatch(r"pages=(\d+)", a)
        if m:
            n = max(1, int(m.group(1)))
            for g in GROUPS:
                PAGES_BY_GROUP[g] = n
    for a in args:
        m = re.fullmatch(r"(movie|drama|show|anime)=(\d+)", a)
        if m:
            PAGES_BY_GROUP[m.group(1).capitalize()] = max(1, int(m.group(2)))

    for a in args:
        m = re.fullmatch(r"(?:only|group)=([a-z,]+)", a)
        if m:
            for g in m.group(1).split(","):
                g = g.strip().capitalize()
                if g in GROUPS:
                    ONLY_GROUPS.add(g)
                elif g:
                    print(f">>> [警告] 忽略未知分类: {g}（可选：{', '.join(GROUPS)}）")

    active = sorted({g for _, g, _ in LIST_SOURCES if not ONLY_GROUPS or g in ONLY_GROUPS},
                    key=GROUPS.index)
    pages_desc = " / ".join(f"{g} {get_max_pages(g)} 页" for g in active)
    print(f">>> [配置] 抓取分类：{pages_desc}；年份限定 {sorted(ALLOWED_YEARS)}"
          + (f"；仅限 {sorted(ONLY_GROUPS)}" if ONLY_GROUPS else "")
          + f"；失效渠道 {sorted(RETIRED_SOURCES)} 策略={RETIRED_POLICY}")
    return {"backfill": "backfill" in args}

def main():
    raw_args = [a.lower().lstrip("-") for a in sys.argv[1:]]
    if "open" in raw_args or "launch" in raw_args:
        launch_chrome_for_cdp()
        return
    if "probe" in raw_args:
        probe_site()
        return

    setup_logging()
    opts = parse_cli()
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)

    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    store = DataStore(JSON_PATH)
    store.initial_load()
    snapshot_backup(JSON_PATH)
    leftovers = glob.glob(os.path.join(os.path.dirname(JSON_PATH), ".OVideos.*.tmp")) + \
                glob.glob(JSON_PATH + ".tmp")
    if leftovers:
        print(f">>> [提示] 发现残留临时文件（可能是之前崩溃留下的，可检查后删除）: {leftovers}")

    try:
        if opts["backfill"]:
            backfill_existing(store)
            return
        keys = ("new", "updated", "moved", "nochange", "skip", "fail")
        group_stats = {g: dict.fromkeys(keys, 0) for g in GROUPS}
        seen = set()
        for list_url, group, label in LIST_SOURCES:
            if ONLY_GROUPS and group not in ONLY_GROUPS:
                continue
            process_list_source(store, list_url, group, label, get_max_pages(group),
                                seen, group_stats[group])

        total = {k: sum(s[k] for s in group_stats.values()) for k in keys}
        print("\n====================================")
        for g in GROUPS:
            s = group_stats[g]
            if any(s.values()):
                print(f"  [{g:<5}] 新增 {s['new']}，更新 {s['updated']}，位置调整 {s['moved']}，"
                      f"无变更 {s['nochange']}，跳过 {s['skip']}，失败 {s['fail']}")
        print(f"所有抓取任务完成! 新增 {total['new']}，更新 {total['updated']}，位置调整 {total['moved']}，"
              f"无变更 {total['nochange']}，跳过 {total['skip']}，失败 {total['fail']}。数据已实时保存在 {JSON_PATH}")
    finally:
        _fetcher.close()

if __name__ == "__main__":
    main()