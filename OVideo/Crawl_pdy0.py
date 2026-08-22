import json
import os
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


import ssl
from urllib3.util.ssl_ import create_urllib3_context


# 标准 requests 的 Session（作为 curl_cffi 失败时的兜底）
_std_session = requests.Session()


# 候选 impersonate 列表，失败时轮换
_IMPERSONATE_POOL = ["chrome", "chrome120", "chrome110", "safari17_0", "edge101"]


# ==========================================
# 受保护的播放源（由其他爬虫维护，本爬虫不覆盖这些源）
# 当条目重新抓取时，这些源会从旧数据中保留下来，
# 只更新这个集合之外的源。后续要新增其它外部源，直接加进来即可。
# 【修改】：将 "6vdy" 也加入受保护源，防止在更新时被覆盖或删除
PROTECTED_SOURCES = {"gdefud", "huxitech", "xb6v"}

# 受保护域名（用于"同名且 URL 仅来自这些域名"的特殊合并规则）
PROTECTED_URL_DOMAINS = ("gdefud.com", "cifppc.com", "6vdy.org")


def get_all_url_keys(item: dict) -> list[str]:
    """返回条目中所有 url 相关的 key，按 url, url1, url2... 顺序排列。"""
    keys = [k for k in item.keys()
            if k == "url" or (k.startswith("url") and k[3:].isdigit())]

    def _sort_key(k):
        return -1 if k == "url" else int(k[3:])

    return sorted(keys, key=_sort_key)

def append_new_url_fields(old_entry: dict, ordered_detail: dict, new_url: str) -> str:
    """
    将 new_url 按 url1/url2/url3... 规则追加到 ordered_detail。
    返回：
      - 新增的 key，例如 "url2"
      - 如果 URL 已存在或无效，返回空字符串
    """
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


def is_all_urls_protected(item: dict) -> bool:
    """
    判断一个条目的所有 url（url/url1/url2...）是否仅来自受保护域名
    （chnland.com 或 6vdy.org）。
      - 至少要有一个有效（非空）url
      - 任意一个 url 不属于受保护域名，则返回 False
    场景：同名且 url 只有 chnland、只有 6vdy、或两者都有但仅此两者。
    """
    url_keys = get_all_url_keys(item)
    if not url_keys:
        return False
    has_valid = False
    for k in url_keys:
        val = item.get(k, "")
        if not val:
            continue
        has_valid = True
        if not any(dom in val for dom in PROTECTED_URL_DOMAINS):
            return False
    return has_valid


# ==========================================
# 日志配置
# ==========================================
# 设置为 False 则屏蔽非关键日志
VERBOSE_LOG = False 


def log(message: str, force: bool = False):
    """
    统一日志输出函数
    :param message: 日志内容
    :param force: 是否强制打印（即使 VERBOSE_LOG 为 False）
    """
    if force or VERBOSE_LOG:
        print(message)


# ==========================================
# 抓取任务总配置
# ==========================================


# 1. 定义一个通用的配置模板，方便复用
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


# 3. 组装 TASKS
TASKS = [
    {
        "sort_type": "score",
        "enabled": False,
        "jobs": [
            # 拼接刚才生成的历史年份
            *historical_jobs, 
        ]
    },
    {
        "sort_type": "score",
        "enabled": False,
        "jobs": [            
            # 最后的空年份配置
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
    # 按播放量和按更新日期抓取
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
                 # skip_score_filter=True  → 2026 新片不要求评分，直接抓取入库（旧片仍需评分）
                 # skip_score_filter=False → 2026 新片也跟旧片一样到详情页拿最高分，高于 6.5 才抓
                 "Movie": {"id": 1, "enabled": True, "pages": 1, "skip_score_filter": True},
                 "Drama": {"id": 2, "enabled": True, "pages": 0},
                 "Show": {"id": 3, "enabled": True, "pages": 0},
                 "Anime": {"id": 4, "enabled": True, "pages": 0}
                 }
            },
        ]
    },
    # ==========================================
    # 【新增】：首页推荐抓取（独立开关，与其它任务互不影响）
    #   - 不看评分（再低或没分都抓）
    #   - 其余规则（地区过滤、剧集数上限、播放源跳过等）保持一致
    #   - categories 里的 id 对应首页 #index-vod-{id}
    # ==========================================
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


# 1. 创建一个全局 of Session 对象
# 这样可以复用 TCP/TLS 连接，极大减少握手错误 (Error 35)
# 强制使用 HTTP/1.1 (http_version=1) 可以避免很多 CDN 的 HTTP/2 握手 Bug
http_session = c_requests.Session(
    impersonate="chrome", 
    http_version=1  # 强制降级到 HTTP/1.1，解决 WRONG_VERSION_NUMBER 报错
)


# ============== 自定义 TLS Adapter:强制更宽松的 SSL 配置 ==============
class TLSAdapter(requests.adapters.HTTPAdapter):
    """
    解决某些老旧 CDN 因 SECLEVEL 或 TLS 版本问题导致的 WRONG_VERSION_NUMBER。
    通过降级 cipher 安全等级、放宽 TLS 版本范围,提高兼容性。
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        except Exception:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)




# 用于"自定义 TLS"降级策略的 session
_tls_session = requests.Session()
_tls_session.mount("https://", TLSAdapter())
_tls_session.mount("http://", requests.adapters.HTTPAdapter())




# ============== 第三方图片代理服务(最强兜底) ==============
# 这些代理服务器和你本机不在同一个网络环境,可以绕过本地/CDN 对你 IP 的封锁
IMAGE_PROXY_TEMPLATES = [
    "https://images.weserv.nl/?url={host_and_path}",
    "https://wsrv.nl/?url={host_and_path}",
]


# 配置区域
# 列表页所在域名
LIST_BASE_URL = "https://www.pys2.com"
# 详情页所在域名
DETAIL_BASE_URL = "https://www.pys2.com"
# 【新增】：首页推荐所在域名（列表页与详情页同域）
INDEX_BASE_URL = "https://www.pys2.com"
# 输出 JSON 文件路径
OUTPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
# 封面图片保存目录
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"


# 【新增】：最低评分过滤配置
# 低于该分数的视频将直接在列表页阶段被过滤，不请求详情页
MIN_SCORE_LIMIT = 6.3
# 非当前年份的旧片，豆瓣/IMDB 取最高分，低于此值则跳过不抓
OLD_VIDEO_MIN_SCORE = 6.3
# 当前年份（综艺 Show 分类只抓当年内容，跨年自动跟随，无需改代码）
CURRENT_YEAR = str(time.localtime().tm_year)


# ==========================================
# 【新增】：剧集数量限制配置
# ==========================================
DRAMA_MAX_EPISODES_LIMIT = 25  # 电视剧分类最大剧集限制（超过则跳过不抓）
ANIME_MAX_EPISODES_LIMIT = 25  # 动漫分类最大剧集限制（超过则跳过不抓）
# 剧集数白名单：命中此列表的名称，不受剧集数量上限过滤
EPISODE_WHITELIST = {"test"}


# Drama / Anime / Show 黑名单地区：只要精准匹配这些，就跳过不抓取
FILTER_REGIONS = {"中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"}


# ==========================================
# 黑名单播放源配置，遇到这些源将直接跳过不抓取
# ==========================================
EXCLUDED_SOURCES = {"非凡", "牛牛", "无尽", "奇异", "猫眼", "ikun"}


# 网络请求配置
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


REQUEST_TIMEOUT = 15        # 单次请求超时秒数
SLEEP_BETWEEN_REQUESTS = 1.0  # 每次请求间隔（秒）
RETRY_TIMES = 3             # 失败重试次数


ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


# =============================================================
# 工具函数
# =============================================================


def format_date_str(date_str: str) -> str:
    """
    将日期字符串转换为 'YYYY-MM-DD' 格式。
    支持处理包含分隔符 '/' 的复杂字符串，取最后一个 '/' 后的内容进行解析。
    """
    if not date_str:
        return date_str


    # 1. 预处理：如果包含 '/' 或 '／'，取最后一个分隔符后面的内容
    if '/' in date_str or '／' in date_str:
        parts = re.split(r'[/／]', date_str)
        date_str = parts[-1].strip()


    try:
        # 2. 使用正则提取所有数字
        parts = re.findall(r'\d+', date_str)
        
        if len(parts) >= 3:
            year, month, day = parts[0], parts[1], parts[2]
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        elif len(parts) == 2:
            return f"{parts[0]}-{parts[1].zfill(2)}"
        
        elif len(parts) == 1:
            return parts[0]
            
    except Exception:
        pass
    
    return date_str




def should_skip_info_update(old_info: str, new_info: str) -> bool:
    """
    判断是否应该跳过 info 的更新。
    如果新旧 info 均包含"第X集"或"X集"，且新集数 <= 旧集数，则返回 True（跳过更新，维持原样）。
    """
    if not old_info or not new_info:
        return False
        
    pattern = r'(?:更新至|第)?(\d+)(?:集|期)?'
    
    old_match = re.search(pattern, old_info)
    new_match = re.search(pattern, new_info)
    
    if old_match and new_match:
        try:
            old_num = int(old_match.group(1))
            new_num = int(new_match.group(1))
            if new_num <= old_num:
                return True
        except ValueError:
            pass
            
    return False




def save_data(data: dict):
    """
    实时保存数据到 JSON 文件。
    使用临时文件替换法，防止写入过程中断导致 JSON 损坏。
    """
    temp_file = OUTPUT_FILE + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(temp_file, OUTPUT_FILE)
    except Exception as e:
        print(f"  [错误] 实时保存失败: {e}")


def get_url_path(url: str) -> str:
    """提取 URL 的路径部分，用于忽略域名差异进行去重。例如提取 /mv/466215.html"""
    try:
        return urlparse(url).path
    except Exception:
        return url


def download_cover(img_url: str, video_id: str, log_prefix: str = "") -> str:
    """
    图片下载 - 新策略(节省时间):
      1) curl_cffi 单次尝试(chrome 指纹)
      2) 失败立即走第三方图片代理(经验证最稳)
      3) 代理也失败再回头试 TLS 降级 / 标准 requests / 多 impersonate 重试
    """
    if not img_url:
        return ""

    # 内部打印函数，确保序号只在第一行打印，后续行保持缩进
    def _print(msg):
        nonlocal log_prefix
        if log_prefix:
            print(f"{log_prefix} {msg}")
            log_prefix = "    "  # 打印过一次后替换为空白缩进
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

    headers = dict(HEADERS)
    headers["Referer"] = DETAIL_BASE_URL
    headers["Connection"] = "close"

    url_candidates = [img_url]
    if img_url.startswith("https://"):
        url_candidates.append("http://" + img_url[8:])
    elif img_url.startswith("http://"):
        url_candidates.append("https://" + img_url[7:])

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

    # ---------- 策略 1:curl_cffi 单次快速尝试 ----------
    for url in url_candidates:
        try:
            resp = c_requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                impersonate="chrome",
                verify=False,
            )
            if resp.status_code == 200 and _save(resp.content):
                _print(f"[封面已下载|curl_cffi/chrome] {filename}")
                return filename
            else:
                _print(f"[curl_cffi HTTP {resp.status_code}] {url}")
        except Exception as e:
            short = str(e).split("See https")[0].strip()
            _print(f"[curl_cffi 单次失败 | {filename}] {short}")

    # ---------- 策略 2:第三方图片代理(主要兜底,经验证最稳) ----------
    _print("[快速降级] 直接走第三方图片代理...")
    parsed = urlparse(img_url)
    host_and_path = parsed.netloc + parsed.path
    if parsed.query:
        host_and_path += "?" + parsed.query

    proxy_headers = {"User-Agent": HEADERS["User-Agent"]}

    for proxy_tpl in IMAGE_PROXY_TEMPLATES:
        proxy_url = proxy_tpl.format(host_and_path=host_and_path)
        for use_curl in (True, False):
            try:
                if use_curl:
                    resp = c_requests.get(
                        proxy_url,
                        headers=proxy_headers,
                        timeout=REQUEST_TIMEOUT * 2,
                        impersonate="chrome",
                        verify=False,
                    )
                else:
                    resp = _std_session.get(
                        proxy_url,
                        headers=proxy_headers,
                        timeout=REQUEST_TIMEOUT * 2,
                        verify=False,
                    )
                if resp.status_code == 200 and _save(resp.content):
                    via = proxy_tpl.split("/?")[0]
                    method = "curl_cffi" if use_curl else "requests"
                    _print(f"[封面已下载|proxy/{method}] {filename} via {via}")
                    return filename
                else:
                    _print(f"[proxy HTTP {resp.status_code}] {proxy_url[:100]}")
            except Exception as e:
                 _print(f"[proxy 失败 | {filename}] {str(e)[:120]}")

    # ---------- 策略 3:深度兜底(仅当代理也挂了才执行) ----------
    _print("[深度兜底] 代理也失败,尝试 TLS 降级 + 多 impersonate 重试...")

    # 3a) 自定义 TLS Adapter
    for url in url_candidates:
        try:
            resp = _tls_session.get(url, headers=headers,
                                    timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200 and _save(resp.content):
                _print(f"[封面已下载|tls_session] {filename}")
                return filename
        except Exception as e:
            _print(f"[tls_session 失败] {str(e)[:120]}")

    # 3b) 标准 requests
    for url in url_candidates:
        try:
            resp = _std_session.get(url, headers=headers,
                                    timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200 and _save(resp.content):
                _print(f"[封面已下载|requests] {filename}")
                return filename
        except Exception as e:
            pass

    return ""


def extract_video_id(url: str, name: str) -> str:
    """从详情页 URL 中提取数字 ID；提取不到则用清洗后的 name。"""
    m = re.search(r"/(?:mv|vod|detail)/(\d+)", url)
    if m:
        return m.group(1)
    safe = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", name).strip("_")
    return safe or "unknown"


def fetch(url: str) -> str | None:
    for i in range(RETRY_TIMES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text
            print(f"  [HTTP {resp.status_code}] {url}")
        except Exception as e:
            print(f"  [Error {i+1}/{RETRY_TIMES}] {url} -> {e}")
            time.sleep(2)
    return None




def clean_ws(s: str) -> str:
    """把连续空白（含 \\r \\n \\t 等）压缩为单个空格，并 strip。"""
    return re.sub(r"\s+", " ", s).strip()




def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)




# =============================================================
# 已有数据读取 / 去重索引 (【已修改】：升级为跨分类全局索引)
# =============================================================
def load_existing(path: str) -> dict:
    """读取已有 JSON。若不存在或损坏，返回空 dict。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"  [警告] 读取已有 JSON 失败，将视为空：{e}")
    return {}




def build_index(existing: dict) -> dict:
    """
    【核心修改】：构建跨分类全局索引。
    返回结构: {(name, path): {"info": info, "update": update, "image": image, "real_name": name, "real_path": path, "category": cat, "list_idx": idx}}
    """
    idx = {}
    for cat, items in existing.items():
        if isinstance(items, list):
            for list_idx, it in enumerate(items):
                name = it.get("name", "")
                info = it.get("info", "")
                update = it.get("update", "")
                image = it.get("image", "")


                if name:
                    url_keys = [k for k in it.keys() if k == "url" or (k.startswith("url") and k[3:].isdigit())]
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
# 解析列表项（通用：普通列表页 / 首页 共用）
# =============================================================
def parse_list_items(scope, li_selector: str, base_url: str) -> list[dict]:
    """
    从给定的 scope（BeautifulSoup 节点）中按 li_selector 解析所有条目。
    href 使用 base_url 进行拼接，从而兼容不同域名（pys2 / pdy0）。
    """
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


        # info：取 .pic span.s1 中的文本（如 "更新至14集"、"78集全"、"HD" 等）
        info = ""
        s1 = li.select_one(".pic span.s1")
        if s1:
            tmp = BeautifulSoup(str(s1), "html.parser")
            for i in tmp.find_all("i"):
                i.decompose()
            info = clean_ws(tmp.get_text(" ", strip=True))


        # 提取评分 <span class="s2">
        score_val = 0.0
        s2 = li.select_one(".pic span.s2")
        if s2:
            score_text = clean_ws(s2.get_text(strip=True))
            if score_text and score_text != "--":
                try:
                    score_val = float(score_text)
                except ValueError:
                    score_val = 0.0


        # 提取列表项中的年份和地区信息
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
    """普通分类列表页解析（域名为 DETAIL_BASE_URL）。"""
    soup = BeautifulSoup(html, "html.parser")
    return parse_list_items(soup, "div.vod-list ul.row > li", DETAIL_BASE_URL)




def parse_homepage(html: str) -> dict:
    """
    【新增】：解析首页推荐栏目。
    首页结构：#index-vod-1 (电影) / #index-vod-2 (剧集) / #index-vod-3 (综艺) / #index-vod-4 (动漫)
    每个栏目下为 div.vlist ul.row > li
    返回 {分类名: [items]}
    """
    soup = BeautifulSoup(html, "html.parser")
    cat_map = {1: "Movie", 2: "Drama", 3: "Show", 4: "Anime"}
    result = {}
    for sec_id, cat_name in cat_map.items():
        section = soup.select_one(f"#index-vod-{sec_id}")
        if section:
            result[cat_name] = parse_list_items(
                section, "div.vlist ul.row > li", INDEX_BASE_URL
            )
        else:
            result[cat_name] = []
    return result




# =============================================================
# 解析详情页
# =============================================================
def _split_by_slash(span) -> list[str]:
    """从一个 <span> 中提取所有 <a> 文本，返回列表"""
    return [a.get_text(strip=True) for a in span.find_all("a")
            if a.get_text(strip=True) and a.get_text(strip=True) != "[展开...]"]




def _find_span_by_label(info_block, label: str):
    """根据起始文字（如 '导演：'）找到对应的 <span>"""
    for span in info_block.find_all("span"):
        text = span.get_text(" ", strip=True)
        if text.startswith(label):
            return span
    return None




def parse_detail_page(html: str, name: str, url: str,
                      info: str = "", base_url: str = DETAIL_BASE_URL,
                      list_year: str = "", skip_score_filter: bool = False,
                      cat_name: str = "", sort_type: str = "") -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    # ====== 提取播放列表并校验（前置逻辑） ======
    playlist = parse_playlist(soup, base_url)
    if not playlist:
        log(f"     [警告] 没有有效播放源，跳过该条目: {name}")
        return None

    # ====== 提取最后更新时间 ======
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
        "评分": {
            "豆瓣": "",
            "IMDB": ""
        },
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

    # ---- 评分（豆瓣 / IMDB） ----
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
                score = num_match.group(1)
                data["评分"]["豆瓣"] = score

    # =============================================================
    # 【修改后】评分过滤
    #   A) 普通模式（其它分类 / score / index / hits&time 的非电影）：沿用旧逻辑
    #   B) 电影 hits/time 模式（movie_region_mode）：
    #        - 新片（detail_year == CURRENT_YEAR）：
    #            * 地区在 FILTER_REGIONS 内  → 必须"有评分且 >= 门槛"，否则跳过
    #            * 地区不在 FILTER_REGIONS 内 → "无评分"放行；"有评分但 < 门槛"才跳过
    #        - 老片（detail_year != CURRENT_YEAR）→ 始终评分过滤（无评分视为不达标）
    #   情色片始终放行（豁免）。
    # =============================================================
    detail_year = ""
    if data.get("date"):
        ym = re.match(r"(\d{4})", data["date"])
        if ym:
            detail_year = ym.group(1)
    if not detail_year:
        detail_year = list_year  # 详情页拿不到年份时，回退用列表页年份

    # 统一计算 豆瓣/IMDB 评分情况
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

    # 情色片豁免
    is_erotic = any("情色" in t for t in data.get("类型", []))

    region = data.get("地区", "")
    is_current_year = (detail_year == CURRENT_YEAR)
    movie_region_mode = (cat_name == "Movie" and sort_type in ("hits", "time"))

    if movie_region_mode:
        if not is_erotic:
            if is_current_year:
                # ===== 2026 新片：地区感知过滤 =====
                if region in FILTER_REGIONS:
                    # 过滤地区（中国/泰国等）：必须有评分且 >= 门槛
                    if (not has_rating) or (max_score < OLD_VIDEO_MIN_SCORE):
                        log(f"     ⚠️[跳过-过滤地区新片评分不达标] {name} "
                            f"(地区: {region or '未知'}, 有评分: {has_rating}, "
                            f"最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})", force=True)
                        return None
                else:
                    # 非过滤地区（美国/韩国等）：无评分放行；有评分但 < 门槛才跳过
                    if has_rating and max_score < OLD_VIDEO_MIN_SCORE:
                        log(f"     ⚠️[跳过-非过滤地区新片评分过低] {name} "
                            f"(地区: {region or '未知'}, 最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})",
                            force=True)
                        return None
            else:
                # ===== 老片：始终评分过滤（无评分 → max_score=0 → 跳过）=====
                if max_score < OLD_VIDEO_MIN_SCORE:
                    log(f"     ⚠️[跳过-老片评分过低] {name} "
                        f"(年份: {detail_year or '未知'}, 最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})",
                        force=True)
                    return None
    else:
        # ===== 原有逻辑：其它分类 / score / index 等，行为完全不变 =====
        should_check_score = False
        if detail_year:
            if detail_year != CURRENT_YEAR:
                should_check_score = True
            elif not skip_score_filter:
                should_check_score = True

        if should_check_score:
            if max_score < OLD_VIDEO_MIN_SCORE and not is_erotic:
                log(f"     ⚠️[跳过-评分过低] {name} (年份: {detail_year}, "
                    f"豆瓣/IMDB最高分: {max_score} < {OLD_VIDEO_MIN_SCORE})", force=True)
                return None

    # ====== 通过过滤后，才开始下载封面图 ======
    img_url = ""
    pic_img = soup.select_one("div.vod-info .pic img")
    if pic_img:
        img_url = (pic_img.get("data-original")
                   or pic_img.get("data-src")
                   or pic_img.get("src")
                   or "").strip()
        if img_url.startswith("//"):
            img_url = "https:" + img_url

    # 不在这里直接下载，将图片URL暂存，交由外层决定是否下载
    data["_img_url"] = img_url
    data["image"] = ""

    # 剧情介绍
    intro_box = soup.select_one("div.more-box.zksq-content")
    if intro_box:
        for a in intro_box.find_all("a"):
            a.decompose()
        intro_text = intro_box.get_text(" ", strip=True)
        intro_text = re.sub(r"^剧情介绍[:：]", "", intro_text)
        data["intro"] = re.sub(r"\s+", "", intro_text)

    return data




def parse_playlist(soup, base_url: str = DETAIL_BASE_URL) -> list[dict]:
    """
    # 兼容多种页面结构：
    #   旧结构：使用 #url-content1（"在线观看"区块）作为容器
    #   新结构：无"在线观看"字段，直接使用 .playlist-box（"播放列表"）
    episodes 结构为 dict {"集数名": "播放链接"}
    href 使用 base_url 拼接，兼容不同域名。
    """
    playlist = []

    online_section = (soup.select_one("#url-content1")
              or soup.select_one(".playlist-box")
              or soup)

    allowed_playlist = []
    excluded_playlist = []

    tabs = online_section.select(".playlist-tab ul.swiper-wrapper > li.swiper-slide")
    if not tabs:
        return []
    for tab in tabs:
        target = tab.get("data-target", "")
        if not target:                 # 跳过没有 data-target 的占位 slide
            continue
        channel_name = ""
        for content in tab.contents:
            if isinstance(content, str) and content.strip():
                channel_name = content.strip()
                break
        if not channel_name:
            channel_name = tab.get_text(strip=True)


        channel_name = channel_name.replace('"', '').replace('“', '').replace('”', '').strip()


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
            playlist_item = {"name": channel_name, "episodes": episodes}
            if channel_name in EXCLUDED_SOURCES:
                excluded_playlist.append(playlist_item)
            else:
                allowed_playlist.append(playlist_item)


    if allowed_playlist:
        return allowed_playlist
    else:
        return excluded_playlist




# =============================================================
# 主流程
# =============================================================
def build_list_url(cat_id: int, page: int, year: str, sort_type: str) -> str:
    """根据传入的 sort_type 和 year 生成不同的列表页 URL。"""
    if sort_type == "score":
        if year:
            return f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---{year}.html"
        else:
            return f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---.html"
    elif sort_type == "hits":
        return f"{LIST_BASE_URL}/ms/{cat_id}--hits------{page}---.html"
    elif sort_type == "time":
        if year:
            return f"{LIST_BASE_URL}/ms/{cat_id}--time------{page}---{year}.html"
        return f"{LIST_BASE_URL}/ms/{cat_id}--time------{page}---.html"
    else:
        raise ValueError(f"未知的 sort_type: {sort_type}")




# =============================================================
# 【已重构】：单个条目的去重 + 详情抓取 + 合并 + 写入
#   被 crawl_category（普通页）与 crawl_homepage（首页）共同复用。
#   返回值: "new" / "updated" / "skipped"
#   skip_score_filter=True 时不进行最低评分过滤（首页专用 / time电影新片专用）。
# =============================================================
def process_item(item: dict, cat_name: str,
                 all_data: dict, global_index: dict,
                 detail_base_url: str = DETAIL_BASE_URL,
                 skip_score_filter: bool = False,
                 idx_i: int = 0, total: int = 0,
                 sort_type: str = "") -> str:          # ← 新增 sort_type
    # =============================================================
    # 分类过滤逻辑分流
    # 【修复】：Drama / Anime 从 Show 内部拆出，成为独立的、与 Show 平级的
    #          elif 分支，且位于电影 else 分支之前。
    # =============================================================
    if cat_name == "Show":
        # 综艺分类：不看评分，只抓当前年份（如 2026），跨年自动跟随
        if item["year"] != CURRENT_YEAR:
            log(f"  ({idx_i}/{total}) [跳过-年份不符] {item['name']} (年份: '{item['year']}' != '{CURRENT_YEAR}')")
            return "skipped"
        # 地区过滤
        if item["region"] in FILTER_REGIONS:
            log(f"  ({idx_i}/{total}) [跳过-黑名单地区] {item['name']} (地区: '{item['region']}')")
            return "skipped"

    elif cat_name == "Drama":
        if (not skip_score_filter) and item["score"] < MIN_SCORE_LIMIT:
            log(f"  ({idx_i}/{total}) [跳过-评分过低] {item['name']} (当前评分: {item['score']} < {MIN_SCORE_LIMIT})")
            return "skipped"
        if item["region"] in FILTER_REGIONS:
            # 【规则】：如果评分大于 7.0，则破格放行
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
            # 【规则】：如果评分大于 7.0，则破格放行
            if item["score"] > 7.0:
                log(f"  ({idx_i}/{total}) [破格放行-高分黑名单地区] {item['name']} (地区: '{item['region']}', 评分: {item['score']} > 7.0)", force=True)
            else:
                log(f"  ({idx_i}/{total}) [跳过-黑名单地区] {item['name']} (地区: '{item['region']}')")
                return "skipped"

    else:
        # 电影分类：评分过滤（skip_score_filter=True 时不过滤）
        # 【说明】：列表页 "--"（→0.0）视为"暂无评分"，放行到详情页再判断；
        #          只有列表页确实给出了评分、且低于门槛时，才在列表阶段跳过。
        if (not skip_score_filter) and 0 < item["score"] < MIN_SCORE_LIMIT:
            log(f"  ({idx_i}/{total}) [跳过-评分过低] {item['name']} (当前评分: {item['score']} < {MIN_SCORE_LIMIT})")
            return "skipped"

    item_path = get_url_path(item["url"])

    # =============================================================
    # 跨分类多维度去重判定
    # =============================================================
    key = (item["name"], item_path)
    old_data = global_index.get(key)
    matched_by_path_only = False
    is_special_6vdy_update = False

    # 1. 跨分类全局 path 查找
    if old_data is None:
        for idx_key, idx_val in global_index.items():
            if idx_val.get("real_path") == item_path:
                old_data = idx_val
                key = idx_key
                matched_by_path_only = True
                break

    # 2. 跨分类全局按名称查找
    #    移植 chnland 的规则：
    #    - 如果 URL/path 没命中，但名称已经存在，则不新增项目
    #    - 后续在旧项目中追加 url1/url2/url3...
    matched_by_name_only = False
    if old_data is None:
        for cat, existing_list in all_data.items():
            if not isinstance(existing_list, list):
                continue

            for list_idx, existing_item in enumerate(existing_list):
                if existing_item.get("name") == item["name"]:
                    old_url_keys = get_all_url_keys(existing_item)
                    first_url_val = ""
                    if old_url_keys:
                        first_url_val = existing_item.get(old_url_keys[0], "")

                    old_data = {
                        "info": existing_item.get("info", ""),
                        "update": existing_item.get("update", ""),
                        "image": existing_item.get("image", ""),
                        "real_name": existing_item.get("name", ""),
                        "real_path": get_url_path(first_url_val) if first_url_val else "",
                        "category": cat,
                        "list_idx": list_idx
                    }

                    key = (
                        existing_item.get("name", item["name"]),
                        get_url_path(first_url_val) if first_url_val else item_path
                    )
                    matched_by_name_only = True

                    log(
                        f"  ({idx_i}/{total}) [同名合并] 发现已有同名记录："
                        f"{item['name']}，本次不新增，将追加 URL/播放源",
                        force=True
                    )
                    break

            if matched_by_name_only:
                break

    # 3. 保留原来的“受保护源特殊同名合并”逻辑作为兜底
    #    注意：由于上面已经做了普通同名合并，所以这里通常不会再触发。
    #    但为了兼容你原来代码里的特殊日志和逻辑，保留不删。
    if old_data is None:
        for cat, existing_list in all_data.items():
            if not isinstance(existing_list, list):
                continue
            for list_idx, existing_item in enumerate(existing_list):
                if existing_item.get("name") == item["name"]:
                    if is_all_urls_protected(existing_item):
                        is_special_6vdy_update = True
                        old_url_keys = get_all_url_keys(existing_item)
                        first_url_val = existing_item.get(old_url_keys[0], "")
                        old_data = {
                            "info": existing_item.get("info", ""),
                            "update": existing_item.get("update", ""),
                            "image": existing_item.get("image", ""),
                            "real_name": existing_item.get("name"),
                            "real_path": get_url_path(first_url_val),
                            "category": cat,
                            "list_idx": list_idx
                        }
                        key = (existing_item.get("name"), get_url_path(first_url_val))
                        break
            if is_special_6vdy_update:
                break

    # 3. 拦截未更新、抢先版、集数未增加
    if old_data is not None and not is_special_6vdy_update and not matched_by_name_only:
        old_info   = old_data.get("info", "")
        old_update = old_data.get("update", "")
        old_image  = old_data.get("image", "")

        if old_image and old_update and (old_info == item["info"]):
            log(f"  ({idx_i}/{total}) [跳过-未更新] {item['name']} (info一致)", force=True)
            return "skipped"

        if old_image and old_update and (old_info != item["info"]):
            block_keywords = ['TC', 'TS', '抢先', 'HC']
            new_info_upper = item["info"].upper()
            if any(kw.upper() in new_info_upper for kw in block_keywords):
                log(f"  ({idx_i}/{total}) [跳过-抢先版拦截] {item['name']} (新info '{item['info']}' 包含抢先关键字)", force=True)
                return "skipped"
            if should_skip_info_update(old_info, item["info"]):
                log(f"  ({idx_i}/{total}) [跳过-集数未增加] {item['name']} (旧info '{old_info}' -> 新info '{item['info']}'，集数未增加)", force=True)
                return "skipped"

    # 判定本次是新增 / 补图 / 补update / 普通更新 / 同名合并 / 受保护源特殊更新
    is_update = (old_data is not None) or is_special_6vdy_update
    if is_update:
        if is_special_6vdy_update:
            tag = "[受保护源特殊更新]"
        elif matched_by_name_only:
            tag = "[同名合并更新]"
        elif matched_by_path_only:
            tag = "[更名更新]"
        elif old_data.get("info") != item["info"]:
            tag = "[Info更新]"
        elif not old_data.get("update"):
            tag = "[补update]"
        elif not old_data.get("image"):
            tag = "[补图]"
        else:
            tag = "[更新]"
    else:
        tag = "[新增]"

    detail_html = fetch(item["url"])
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not detail_html:
        return "skipped"

    try:
        detail = parse_detail_page(detail_html, item["name"], item["url"],
                                   info=item["info"], base_url=detail_base_url,
                                   list_year=item.get("year", ""),
                                   skip_score_filter=skip_score_filter,
                                   cat_name=cat_name, sort_type=sort_type)   # ← 新增这两个

        if detail is None:
            return "skipped"

        # =============================================================
        # 针对 Drama 和 Anime 的最大剧集数限制过滤
        # =============================================================
        if detail.get("playlist"):
            max_episodes = max(len(p.get("episodes", {})) for p in detail["playlist"])
            video_name = item["name"]
            # 判断是否命中白名单，命中则跳过集数校验
            in_ep_whitelist = video_name in EPISODE_WHITELIST

            if not in_ep_whitelist:
                if cat_name == "Drama" and max_episodes > DRAMA_MAX_EPISODES_LIMIT:
                    log(f"  ({idx_i}/{total}) [跳过-剧集数超限] {video_name} (最大集数: {max_episodes} > {DRAMA_MAX_EPISODES_LIMIT})", force=True)
                    return "skipped"
                elif cat_name == "Anime" and max_episodes > ANIME_MAX_EPISODES_LIMIT:
                    log(f"  ({idx_i}/{total}) [跳过-剧集数超限] {video_name} (最大集数: {max_episodes} > {ANIME_MAX_EPISODES_LIMIT})", force=True)
                    return "skipped"
            else:
                log(f"  ({idx_i}/{total}) ✅[剧集白名单放行] {video_name}，忽略集数限制 {max_episodes}", force=True)

        # =============================================================
        # 【新增】：所有过滤条件通过后，决定是否下载图片
        # =============================================================
        img_url = detail.pop("_img_url", "")
        # 如果是更新且旧数据已经有图片，则直接复用，不下载
        if is_update and old_data and old_data.get("image"):
            detail["image"] = old_data.get("image")
        else:
            # 如果是新增项目，或者已有项目但缺少图片，则执行下载
            if img_url:
                video_id = extract_video_id(item["url"], item["name"])
                # 将序号作为 log_prefix 传给下载函数，去掉原先单独的准备下载日志
                detail["image"] = download_cover(img_url, video_id, log_prefix=f"  ({idx_i}/{total})")
                time.sleep(SLEEP_BETWEEN_REQUESTS)

        # 去掉这行日志前面的 ({idx_i}/{total}) 序号
        log(f"   {'✅' if tag == '[新增]' else ''}{tag} {item['name']}  {item['url']}  info={item['info']}", force=True)

        # ===== 任何更新名字 name 不要改 =====
        if is_update:
            detail["name"] = key[0]

        # 获取旧分类和旧条目
        old_entry = None
        old_category = None
        target_list_idx = None

        if is_update:
            old_category = old_data.get("category")
            target_list_idx = old_data.get("list_idx")
            if old_category and old_category in all_data:
                existing_list = all_data[old_category]
                if target_list_idx is not None and target_list_idx < len(existing_list):
                    old_entry = existing_list[target_list_idx]

        # ======================【修改后的 playlist 合并逻辑 开始】======================
        # 合并播放源：完整保留旧playlist原有顺序，不再置顶重排受保护源
        if old_entry:
            old_playlist = old_entry.get("playlist", [])
            
            # 本次抓取出来的所有非受保护源，转为字典方便查找
            new_candidate_dict = {
                p["name"]: p for p in detail.get("playlist", [])
                if p.get("name") not in PROTECTED_SOURCES
            }

            final_playlist = []
            old_source_names = set()

            # 1. 遍历旧 playlist，保持原有顺序
            for old_p in old_playlist:
                name = old_p.get("name")
                old_source_names.add(name)
                
                if name in PROTECTED_SOURCES:
                    # 受保护源：无条件保留旧数据
                    final_playlist.append(old_p)
                else:
                    # 非受保护源：如果本次抓取到了新数据，则用新数据覆盖（更新集数）；否则保留旧的
                    if name in new_candidate_dict:
                        final_playlist.append(new_candidate_dict[name])
                    else:
                        final_playlist.append(old_p)

            # 2. 追加旧 playlist 中完全不存在的新增渠道
            for name, new_p in new_candidate_dict.items():
                if name not in old_source_names:
                    final_playlist.append(new_p)
                    
            # 重新生成 new_candidate_sources 供后续 info 校验使用
            new_candidate_sources = list(new_candidate_dict.values())

            # ==========================================
            # 【新增】：寻找拥有最大集数的渠道并置顶
            # ==========================================
            # if final_playlist:
            #     max_ep_count = -1
            #     max_ep_idx = -1
            #     # 遍历寻找集数最大的渠道
            #     for i, p in enumerate(final_playlist):
            #         ep_count = len(p.get("episodes", {}))
            #         if ep_count > max_ep_count:
            #             max_ep_count = ep_count
            #             max_ep_idx = i
                
            #     # 如果找到了最大集数的渠道，将其移出并插入到第0位
            #     if max_ep_idx > 0:  # >0 说明它不在第一位才需要移动
            #         top_channel = final_playlist.pop(max_ep_idx)
            #         final_playlist.insert(0, top_channel)
            #         print(f"     [渠道置顶] 将拥有最大集数({max_ep_count}集)的渠道 '{top_channel['name']}' 置于首位")

            # ==========================================
            # 【修改】：仅当 playlist 内容发生变化时才做“最大集数渠道置顶”
            #   若本次抓取内容与旧 playlist 完全一致（渠道、集数都没变），
            #   则保持用户手动调整过的原有顺序，绝不重排。
            # ==========================================
            content_changed = (final_playlist != old_playlist)
            if content_changed and final_playlist:
                max_ep_count = -1
                max_ep_idx = -1
                # 遍历寻找集数最大的渠道
                for i, p in enumerate(final_playlist):
                    ep_count = len(p.get("episodes", {}))
                    if ep_count > max_ep_count:
                        max_ep_count = ep_count
                        max_ep_idx = i

                # 如果找到了最大集数的渠道，将其移出并插入到第0位
                if max_ep_idx > 0:  # >0 说明它不在第一位才需要移动
                    top_channel = final_playlist.pop(max_ep_idx)
                    final_playlist.insert(0, top_channel)
                    print(f"     [渠道置顶] 将拥有最大集数({max_ep_count}集)的渠道 '{top_channel['name']}' 置于首位")
            elif not content_changed:
                print(f"     [顺序保持] 本次抓取内容与已有 playlist 完全一致，保留原有顺序不做置顶")

            detail["playlist"] = final_playlist

            detail["playlist"] = final_playlist

            protected_in_old = [
                p for p in old_playlist
                if p.get("name") in PROTECTED_SOURCES
            ]
            kept_names = [p.get("name") for p in protected_in_old]
            print(f"     [保留受保护源] {kept_names} (维持原有顺序，新增渠道追加至末尾)")

            # ==========================================
            # 【修改】：info 更新前，进行双重集数校验
            #   1. 自己渠道集数 vs 受保护渠道集数
            #   2. 自己渠道真实集数 vs 抓取到的新 info 宣称集数
            # ==========================================
            protected_max_ep = max(
                (len(p.get("episodes", {})) for p in protected_in_old),
                default=0
            )
            own_max_ep = max(
                (len(p.get("episodes", {})) for p in new_candidate_sources),
                default=0
            )
            old_info_val = old_entry.get("info", "")
            new_info_val = detail.get("info", "")
            
            # 提取新/旧 info 中的数字（如“更新至第05集”提取出 5）
            new_info_num = 0
            match_new = re.search(r'(?:更新至|第)?(\d+)(?:集|期)?', new_info_val)
            if match_new:
                new_info_num = int(match_new.group(1))
                
            old_info_num = 0
            match_old = re.search(r'(?:更新至|第)?(\d+)(?:集|期)?', old_info_val)
            if match_old:
                old_info_num = int(match_old.group(1))

            # 真实的最大集数（无论是自己抓的还是受保护源的）
            actual_max_ep = max(own_max_ep, protected_max_ep)

            # 如果新宣称的集数大于真实拥有的最大集数，说明是虚假更新
            if new_info_num > 0 and actual_max_ep < new_info_num:
                if new_info_val != old_info_val:
                    print(f"     [Info保持] 虚假更新拦截！真实最大集数({actual_max_ep}) < 宣称集数({new_info_num})，"
                          f"保留旧info '{old_info_val}'")
                detail["info"] = old_info_val
            
            # 如果新 info 的集数并没有比旧 info 大（或者无法提取数字但内容不同且自己集数不占优）
            elif new_info_num <= old_info_num and own_max_ep <= protected_max_ep:
                if new_info_val != old_info_val:
                    print(f"     [Info保持] 新info集数({new_info_num}) 未超过 旧info集数({old_info_num})，"
                          f"且自己渠道集数({own_max_ep}) <= 受保护渠道({protected_max_ep})，保留旧info '{old_info_val}'")
                detail["info"] = old_info_val
                
            # 其他情况（新 info 集数更大且真实集数达标，或者自己渠道集数反超了受保护渠道），正常更新
            else:
                if new_info_val != old_info_val:
                    print(f"     ✅[Info更新] 允许更新 info: '{old_info_val}' -> '{new_info_val}' (真实最大集数: {actual_max_ep})")

        # =====================【修复位置开始】=====================
        # 受保护源合并、info回滚逻辑全部执行完成后，再打印真实变更日志
        if is_update and old_entry:
            old_info = old_entry.get("info", "")
            final_info = detail.get("info", "")
            old_pl = old_entry.get("playlist", [])
            new_pl = detail.get("playlist", [])
            # 使用落地后的final_info对比，不再使用原始item["info"]
            info_changed = (old_info != final_info)
            pl_changed = (old_pl != new_pl)
            if info_changed and pl_changed:
                print(f"     ✅[Info+Playlist更新] {item['name']} (Info: {old_info} -> {final_info})")
            elif info_changed:
                print(f"     ✅[仅Info更新] {item['name']} (Info: {old_info} -> {final_info})")
            elif pl_changed:
                print(f"     ✅[仅Playlist更新] {item['name']}")
        # =====================【修复位置结束】=====================

        if matched_by_path_only:
            print(f"     [更名同步] {key[0]} -> {item['name']} (已强行保留旧名 {key[0]})")

        # ==========================================
        # 细粒度字段合并与更新
        # ==========================================
        if is_update and old_entry:
            # 【固定规则】仅新增时写入 update，更新永远不修改 update
            detail["update"] = old_entry.get("update", detail.get("update", ""))

            for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]:
                old_val = old_entry.get(field)
                new_val = detail.get(field)
                if not old_val and new_val:
                    print(f"     [补全字段] {field}: (空) -> {new_val}")
                else:
                    detail[field] = old_val

            old_date = old_entry.get("date", "")
            new_date = detail.get("date", "")
            if new_date and (not old_date or len(new_date) > len(old_date)):
                print(f"     [更新日期] date: {old_date or '(空)'} -> {new_date}")
            else:
                detail["date"] = old_date

            old_rating = old_entry.get("评分", {})
            if not isinstance(old_rating, dict):
                old_rating = {"豆瓣": "", "IMDB": ""}
            new_rating = detail.get("评分", {})

            final_rating = {}
            for platform in ["豆瓣", "IMDB"]:
                old_score = old_rating.get(platform, "")
                new_score = new_rating.get(platform, "")
                if not old_score and new_score:
                    final_rating[platform] = new_score
                    print(f"     [补全评分] {platform}: (空) -> {new_score}")
                else:
                    final_rating[platform] = old_score
            detail["评分"] = final_rating

        # ===== 字段排序重构 =====
        ordered_detail = {}
        ordered_detail["name"] = detail["name"]

        if is_update and old_entry:
            ordered_detail["url"] = old_entry.get("url", "")
        else:
            ordered_detail["url"] = detail["url"]

        if (is_special_6vdy_update or matched_by_name_only) and old_entry:
            new_url = detail.get("url", "")
            added_key = append_new_url_fields(old_entry, ordered_detail, new_url)

            if added_key:
                if matched_by_name_only:
                    print(f"     [同名合并] 已将新抓取的 URL 写入为 {added_key}: {new_url}")
                else:
                    print(f"     [受保护源特殊合并] 已将新抓取的 URL 写入为 {added_key}: {new_url}")
            else:
                if matched_by_name_only:
                    print(f"     [同名合并] 新 URL 已存在于旧条目，跳过追加")
                else:
                    print(f"     [受保护源特殊合并] 新 URL 已存在于旧条目，跳过追加")

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

        # =============================================================
        # 跨分类数据写入与索引重构
        # =============================================================
        result = "skipped"
        if is_update:
            # chnland 风格：
            # 只要命中已有记录，就优先写回旧记录所在分类。
            # 不因为本次抓取分类不同而移动条目。
            write_category = old_category if old_category else cat_name

            if write_category not in all_data:
                all_data[write_category] = []

            if old_category != cat_name:
                print(
                    f"     [分类保持] 已有记录位于 {old_category}，"
                    f"本次抓取分类为 {cat_name}，按已有分类 {write_category} 写回，不移动"
                )

            if target_list_idx is not None and target_list_idx < len(all_data[write_category]):
                all_data[write_category][target_list_idx] = detail
            else:
                replaced = False
                for i, old in enumerate(all_data[write_category]):
                    old_path = get_url_path(old.get("url", ""))
                    if (
                        old.get("name") == key[0]
                        or old_path == item_path
                    ):
                        all_data[write_category][i] = detail
                        replaced = True
                        break

                if not replaced:
                    all_data[write_category].append(detail)

            result = "updated"
        else:
            if cat_name not in all_data:
                all_data[cat_name] = []
            all_data[cat_name].append(detail)
            result = "new"

        if matched_by_path_only and key in global_index:
            del global_index[key]

        global_index.clear()
        global_index.update(build_index(all_data))

        save_data(all_data)
        log(f"     [已实时保存到磁盘]", force=True)
        return result
    except Exception as e:
        import traceback
        print(f"     [解析失败] {e}")
        traceback.print_exc()
        return "skipped"


# =============================================================
# 抓取普通分类（列表页模式）
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
                sort_type=sort_type                 # ← 新增
            )
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

    return new_count, updated_count




# =============================================================
# 【新增】：抓取首页推荐（首页模式，不看评分）
# =============================================================
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
            print(f"跳过首页分类: {cat_name} (在 index 配置中未启用)")
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
                skip_score_filter=True,   # 首页不看评分
                idx_i=idx_i, total=len(items),
                sort_type="index"          # ← 新增
            )
            if result == "new":
                new_n += 1
            elif result == "updated":
                upd_n += 1


        print(f"  -> [首页] 分类 {cat_name} 新增 {new_n} 条，更新 {upd_n} 条")




def clean_existing_data(data: dict):
    for cat in data:
        if isinstance(data[cat], list):
            new_list = []
            for item in data[cat]:
                item.pop("update_pk", None)  # 删掉历史残留字段
                if item.get("playlist"):
                    new_list.append(item)
            data[cat] = new_list


# ==========================================
# 防止休眠控制
# ==========================================
_caffeinate_proc = None


def start_caffeinate():
    """启动 caffeinate 以防止系统休眠"""
    global _caffeinate_proc
    try:
        _caffeinate_proc = subprocess.Popen(["caffeinate", "-idmu"])
        print(">>> [系统] 已开启防休眠模式 (caffeinate)")
    except Exception as e:
        print(f">>> [系统] 无法启动 caffeinate: {e}")


def stop_caffeinate():
    """停止 caffeinate"""
    global _caffeinate_proc
    if _caffeinate_proc:
        _caffeinate_proc.terminate()
        print(">>> [系统] 已关闭防休眠模式")


atexit.register(stop_caffeinate)


def main():
    start_caffeinate()


    final = load_existing(OUTPUT_FILE)
    clean_existing_data(final) 
    
    global_index = build_index(final)
    print(f"已有数据分类数: {len(final)}；"
          f"总条目数: {sum(len(v) for v in final.values() if isinstance(v, list))}")


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


            # ==========================================
            # 【新增】：首页推荐模式单独处理（一次性抓全部 4 个栏目）
            # ==========================================
            if sort_type == "index":
                for cat_name in categories_cfg:
                    if cat_name not in final:
                        final[cat_name] = []
                crawl_homepage(categories_cfg, final, global_index)
                continue


            for cat_name, cat_cfg in categories_cfg.items():
                if cat_name not in final: final[cat_name] = []


                if not cat_cfg.get("enabled"):
                    print(f"跳过分类: {cat_name}(在 [{sort_type}/{year or '无'}] 配置中未启用)")
                    continue


                new_n, upd_n = crawl_category(
                    cat_name, cat_cfg,
                    final, global_index,
                    year, sort_type
                )
                print(f"  -> [{sort_type}] year={year or '无'} 分类 {cat_name} "
                      f"新增 {new_n} 条,更新 {upd_n} 条")


    print(f"\n✅ 全部抓取任务结束。")




if __name__ == "__main__":
    main()