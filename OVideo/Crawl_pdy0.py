import json
import os
import time
import random
import re
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
PROTECTED_SOURCES = {"xb6v"}

# ==========================================
# 抓取任务总配置
# ==========================================
# 顺序就是执行顺序：先跑 score,再跑 hits
# 每组有独立的 enabled 开关,关闭后整组跳过
TASKS = [
    {
        "sort_type": "score",
        "enabled": True,           # ← score 模式总开关
        "jobs": [
            {
                "year": "2026",
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 2},
                    "Drama": {"id": 2, "enabled": True,  "pages": 2},
                    "Show":  {"id": 3, "enabled": True,  "pages": 2},
                    "Anime": {"id": 4, "enabled": True,  "pages": 2},
                }
            },
            {
                "year": "2025",
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 4},
                    "Drama": {"id": 2, "enabled": True,  "pages": 2},
                    "Show":  {"id": 3, "enabled": True, "pages": 1},
                    "Anime": {"id": 4, "enabled": True,  "pages": 2},
                }
            },
            {
                "year": "2024",
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 4},
                    "Drama": {"id": 2, "enabled": True,  "pages": 2},
                    "Show":  {"id": 3, "enabled": True, "pages": 1},
                    "Anime": {"id": 4, "enabled": True,  "pages": 2},
                }
            },
            {
                "year": "2023",
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 3},
                    "Drama": {"id": 2, "enabled": True,  "pages": 1},
                    "Show":  {"id": 3, "enabled": True, "pages": 1},
                    "Anime": {"id": 4, "enabled": True,  "pages": 1},
                }
            },
            {
                "year": "2022",
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 3},
                    "Drama": {"id": 2, "enabled": True,  "pages": 1},
                    "Show":  {"id": 3, "enabled": True, "pages": 1},
                    "Anime": {"id": 4, "enabled": True,  "pages": 1},
                }
            },
            # --- 新增：score 模式，不需要年份 ---
            {
                "year": "",  # 这里留空
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
        "enabled": True,           # ← hits 模式总开关
        "jobs": [
            {
                # hits 模式不需要年份,留空字符串即可
                "year": "",
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 2},
                    "Drama": {"id": 2, "enabled": True,  "pages": 2},
                    "Show":  {"id": 3, "enabled": True, "pages": 1},
                    "Anime": {"id": 4, "enabled": True,  "pages": 2},
                }
            },
        ]
    },
    {
        "sort_type": "time",
        "enabled": True,           # ← time 模式总开关
        "jobs": [
            {
                "year": "",        # time 模式也不需要年份
                "categories": {
                    "Movie": {"id": 1, "enabled": True,  "pages": 2},
                    "Drama": {"id": 2, "enabled": True,  "pages": 2},
                    "Show":  {"id": 3, "enabled": True, "pages": 1},
                    "Anime": {"id": 4, "enabled": True,  "pages": 2},
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
# 输出 JSON 文件路径
OUTPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
# 封面图片保存目录
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"

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

def save_data(data: dict):
    """
    实时保存数据到 JSON 文件。
    使用临时文件替换法，防止写入过程中断导致 JSON 损坏。
    """
    temp_file = OUTPUT_FILE + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        # 写入成功后，替换原文件
        os.replace(temp_file, OUTPUT_FILE)
    except Exception as e:
        print(f"  [错误] 实时保存失败: {e}")

def get_url_path(url: str) -> str:
    """提取 URL 的路径部分，用于忽略域名差异进行去重。例如提取 /mv/466215.html"""
    try:
        return urlparse(url).path
    except Exception:
        return url

def download_cover(img_url: str, video_id: str) -> str:
    """
    图片下载 - 新策略(节省时间):
      1) curl_cffi 单次尝试(chrome 指纹)
      2) 失败立即走第三方图片代理(经验证最稳)
      3) 代理也失败再回头试 TLS 降级 / 标准 requests / 多 impersonate 重试
    """
    if not img_url:
        return ""

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

    # 协议切换候选
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
                print(f"     [封面已下载|curl_cffi/chrome] {filename}")
                return filename
            else:
                print(f"     [curl_cffi HTTP {resp.status_code}] {url}")
        except Exception as e:
            short = str(e).split("See https")[0].strip()
            print(f"     [curl_cffi 单次失败] {short}")

    # ---------- 策略 2:第三方图片代理(主要兜底,经验证最稳) ----------
    print("     [快速降级] 直接走第三方图片代理...")
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
                    print(f"     [封面已下载|proxy/{method}] {filename} via {via}")
                    return filename
                else:
                    print(f"     [proxy HTTP {resp.status_code}] {proxy_url[:100]}")
            except Exception as e:
                print(f"     [proxy 失败] {str(e)[:120]}")

    # ---------- 策略 3:深度兜底(仅当代理也挂了才执行) ----------
    print("     [深度兜底] 代理也失败,尝试 TLS 降级 + 多 impersonate 重试...")

    # 3a) 自定义 TLS Adapter
    for url in url_candidates:
        try:
            resp = _tls_session.get(url, headers=headers,
                                    timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200 and _save(resp.content):
                print(f"     [封面已下载|tls_session] {filename}")
                return filename
        except Exception as e:
            print(f"     [tls_session 失败] {str(e)[:120]}")

    # 3b) 标准 requests
    for url in url_candidates:
        try:
            resp = _std_session.get(url, headers=headers,
                                    timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200 and _save(resp.content):
                print(f"     [封面已下载|requests] {filename}")
                return filename
        except Exception as e:
            print(f"     [requests 失败] {str(e)[:120]}")

    # 3c) curl_cffi 轮换指纹 + 短退避(最后挣扎)
    for attempt in range(RETRY_TIMES):
        impersonate = _IMPERSONATE_POOL[attempt % len(_IMPERSONATE_POOL)]
        for url in url_candidates:
            try:
                resp = c_requests.get(url, headers=headers,
                                      timeout=REQUEST_TIMEOUT,
                                      impersonate=impersonate, verify=False)
                if resp.status_code == 200 and _save(resp.content):
                    print(f"     [封面已下载|curl_cffi/{impersonate}] {filename}")
                    return filename
            except Exception as e:
                short = str(e).split("See https")[0].strip()
                print(f"     [curl_cffi 失败 {attempt+1}/{RETRY_TIMES} impersonate={impersonate}] {short}")
        time.sleep(random.uniform(2, 4))

    print(f"     [❌ 最终失败] {img_url}")
    return ""


def extract_video_id(url: str, name: str) -> str:
    """从详情页 URL 中提取数字 ID；提取不到则用清洗后的 name。"""
    m = re.search(r"/(?:mv|vod|detail)/(\d+)", url)
    if m:
        return m.group(1)
    # 兜底：用 name 清洗成安全文件名
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
# 已有数据读取 / 去重索引
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
    返回 {category: {(name, path): {"info": info, "update": update, "image": image}}},
    用于判断该条目是否已存在、info / update 是否变化,以及图片是否缺失。
    """
    idx = {}
    for cat, items in existing.items():
        m = {}
        if isinstance(items, list):
            for it in items:
                name = it.get("name", "")
                url = it.get("url", "")
                info = it.get("info", "")
                update = it.get("update", "")
                image = it.get("image", "")
                
                # 【新增】：判断旧数据的 playlist 中是否包含 name 为 xb6v 的源
                playlist = it.get("playlist", [])
                has_xb6v = any(p.get("name") == "xb6v" for p in playlist)

                # 检查旧数据的 episodes 格式是否为 list (如果是 list 则需要重抓转换为 dict)
                is_old_episodes = False
                for p in playlist:
                    if isinstance(p.get("episodes"), list):
                        is_old_episodes = True
                        break

                if name and url:
                    path = get_url_path(url)
                    m[(name, path)] = {
                        "info": info,
                        "update": update,
                        "image": image,
                        "has_xb6v": has_xb6v,
                        "is_old_episodes": is_old_episodes,  # ← 记录是否是旧集数格式
                    }
        idx[cat] = m
    return idx


# =============================================================
# 解析列表页
# =============================================================
def parse_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("div.vod-list ul.row > li"):
        a = li.select_one("div.name h3 a")
        if not a:
            continue
        name = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")
        if not href:
            continue
        full_url = urljoin(DETAIL_BASE_URL, href)

        # info：取 .pic span.s1 中的文本（如 "更新至第14集"、"78集全"、"HD" 等）
        info = ""
        s1 = li.select_one(".pic span.s1")
        if s1:
            # 复制后去掉 <i> 图标
            tmp = BeautifulSoup(str(s1), "html.parser")
            for i in tmp.find_all("i"):
                i.decompose()
            info = clean_ws(tmp.get_text(" ", strip=True))

        items.append({
            "name": name,
            "url": full_url,
            "info": info
        })
    return items


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
                      info: str = "") -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    # ====== 提取最后更新时间 ======
    # HTML 结构: <div class="otherbox">当前为<em>HD</em>资源，最后更新于<em>2026-05-14 13:33:05</em></div>
    update_time = ""
    otherbox = soup.select_one("div.vod-info .otherbox") or soup.select_one(".otherbox")
    if otherbox:
        ems = otherbox.find_all("em")
        # 最后一个 <em> 通常是时间戳
        if ems:
            last_text = clean_ws(ems[-1].get_text(strip=True))
            # 校验一下是不是时间格式,避免错误抓到 HD/资源类型
            if re.search(r"\d{4}-\d{2}-\d{2}", last_text):
                update_time = last_text
            elif len(ems) >= 2:
                # 兜底:取倒数第一个 em 的文本
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
        "playlist": [],
    }

    # ====== 封面图 ======
    img_url = ""
    pic_img = soup.select_one("div.vod-info .pic img")
    if pic_img:
        # 优先 data-original（高清原图），src 是懒加载占位图
        img_url = (pic_img.get("data-original")
                   or pic_img.get("data-src")
                   or pic_img.get("src")
                   or "").strip()
        # 处理协议相对地址
        if img_url.startswith("//"):
            img_url = "https:" + img_url

    if img_url:
        video_id = extract_video_id(url, name)
        data["image"] = download_cover(img_url, video_id)
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    info_block = soup.select_one("div.vod-info .info") or soup

    # 提取字段
    span = _find_span_by_label(info_block, "导演：")
    if span:
        directors = _split_by_slash(span)
        data["导演"] = directors[0] if directors else ""

    # 编剧
    span = _find_span_by_label(info_block, "编剧：")
    if span:
        data["编剧"] = _split_by_slash(span)

    # 主演
    span = info_block.select_one("span.zksq-actor") or _find_span_by_label(info_block, "主演：")
    if span:
        data["主演"] = _split_by_slash(span)

    # 类型
    span = _find_span_by_label(info_block, "类型：")
    if span:
        data["类型"] = _split_by_slash(span)

    # 地区
    span = _find_span_by_label(info_block, "地区：")
    if span:
        regions = _split_by_slash(span)
        data["地区"] = regions[0] if regions else ""

    # 上映 / 又名
    for span in info_block.find_all("span"):
        text = span.get_text(" ", strip=True)
        if text.startswith("上映："):
            # 1. 先清理空白
            cleaned = clean_ws(text)
            # 2. 去掉前缀 "上映："
            cleaned = cleaned.replace("上映：", "", 1)
            # 3. 如果需要去掉 "(美国网络)" 中的 "网络" 二字，可以使用正则替换
            # 这里的意思是把 "(...网络)" 替换为 "(...)"
            cleaned = re.sub(r"\((.*?)(网络)\)", r"(\1)", cleaned)
            data["date"] = cleaned
        elif text.startswith("又名："):
            data["alias"] = clean_ws(text)

    # ---- 评分（豆瓣 / IMDB） ----
    span = _find_span_by_label(info_block, "评分：")
    if span:
        for s in span.find_all("span"):
            t = clean_ws(s.get_text(" ", strip=True))
            if t:
                # 使用正则提取平台名称和分数，兼容 "豆瓣 7.2" 或 "IMDB --"
                match = re.search(r"(豆瓣|IMDB)\s*([0-9.]+|--)", t, re.IGNORECASE)
                if match:
                    platform = match.group(1)
                    if platform.upper() == "IMDB":
                        platform = "IMDB"
                    score = match.group(2)
                    
                    # 只有当分数不是 "--" 时，才写入字典
                    if score != "--":
                        data["评分"][platform] = score

    # 剧情介绍
    intro_box = soup.select_one("div.more-box.zksq-content")
    if intro_box:
        # 去掉 "[展开...]" 之类的展开链接
        for a in intro_box.find_all("a"):
            a.decompose()
        intro_text = intro_box.get_text(" ", strip=True)
        
        # --- 修改部分开始 ---
        # 去除开头可能存在的 "剧情介绍：" 或 "剧情介绍:"
        intro_text = re.sub(r"^剧情介绍[:：]", "", intro_text)
        # --- 修改部分结束 ---

        # 压缩多余空白
        data["intro"] = re.sub(r"\s+", "", intro_text)

    # 播放列表（仅在线观看）
    data["playlist"] = parse_playlist(soup)

    # 【新增逻辑】：如果播放列表为空，说明没有有效资源，直接返回 None
    if not data["playlist"]:
        print(f"     [警告] 没有有效播放源，跳过该条目: {name}")
        return None

    return data


def parse_playlist(soup) -> list[dict]:
    """
    只解析『在线观看』tab（#url-content1）下的播放列表。
    【已修改】：将 episodes 结构从 list 更改为 dict {"集数名": "播放链接"}
    """
    playlist = []

    # 关键改动：把搜索范围锁定到 #url-content1
    online_section = soup.select_one("#url-content1")
    if not online_section:
        return []

    allowed_playlist = []   # 存放正常的播放源
    excluded_playlist = []  # 存放黑名单中的播放源

    tabs = online_section.select(".playlist-tab ul.swiper-wrapper > li.swiper-slide")
    for tab in tabs:
        target = tab.get("data-target", "")  # 如 #ewave-playlist-1
        # 频道名 = li 直接文本（不含 <span>/<em>）
        channel_name = ""
        for content in tab.contents:
            if isinstance(content, str) and content.strip():
                channel_name = content.strip()
                break
        if not channel_name:
            channel_name = tab.get_text(strip=True)

        # 去除可能包含的引号或多余空格
        channel_name = channel_name.replace('"', '').replace('“', '').replace('”', '').strip()

        ul_id = target.lstrip("#")
        # 同样限制在 online_section 内
        ul = online_section.find("ul", id=ul_id)
        
        # 【修改处】：将 episodes 更改为 dict 结构
        episodes = {}
        if ul:
            for a in ul.select("li a"):
                href = a.get("href", "")
                ep_name = a.get_text(strip=True) # 获取如 "第01集"
                if href and ep_name:
                    episodes[ep_name] = urljoin(DETAIL_BASE_URL, href)
        
        # 如果解析到了剧集，则根据黑名单进行分类存放
        if episodes:
            playlist_item = {"name": channel_name, "episodes": episodes}
            if channel_name in EXCLUDED_SOURCES:
                excluded_playlist.append(playlist_item)
            else:
                allowed_playlist.append(playlist_item)

    # ==========================================
    # 核心逻辑：
    # 如果有正常的源，优先返回正常的源。
    # 如果正常的源为空，说明只有黑名单里的源，则返回黑名单源作为兜底。
    # ==========================================
    if allowed_playlist:
        return allowed_playlist
    else:
        return excluded_playlist


# =============================================================
# 主流程
# =============================================================
def build_list_url(cat_id: int, page: int, year: str, sort_type: str) -> str:
    """
    根据传入的 sort_type 和 year 生成不同的列表页 URL。
      - score 模式: /ms/1--score------2---2026.html  (需要 year)
      - hits  模式: /ms/1--hits------2---.html       (不需要 year)
      - time  模式: /ms/1--time------2---.html       (不需要 year)
    """
    if sort_type == "score":
        # 如果有年份，拼接年份；如果没有，则不拼接
        if year:
            return f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---{year}.html"
        else:
            return f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---.html"
    elif sort_type == "hits":
        return f"{LIST_BASE_URL}/ms/{cat_id}--hits------{page}---.html"
    elif sort_type == "time":
        return f"{LIST_BASE_URL}/ms/{cat_id}--time------{page}---.html"
    else:
        raise ValueError(f"未知的 sort_type: {sort_type}")


def crawl_category(cat_name: str, cat_cfg: dict,
                   existing_list: list, index_map: dict,
                   all_data: dict, year: str, sort_type: str) -> tuple[int, int]:
    print(f"\n=== 开始抓取分类: {cat_name} "
          f"(sort={sort_type}, id={cat_cfg['id']}, pages={cat_cfg['pages']}, year={year or '无'}) ===")
    new_count = 0
    updated_count = 0

    for page in range(1, cat_cfg["pages"] + 1):
        list_url = build_list_url(cat_cfg["id"], page, year, sort_type)
        print(f"\n[列表页] {list_url}")
        html = fetch(list_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if not html:
            continue

        items = parse_list_page(html)
        print(f"  -> 共找到 {len(items)} 部")

        for idx_i, item in enumerate(items, 1):
            item_path = get_url_path(item["url"])
            key = (item["name"], item_path)
            old_data = index_map.get(key)

            if old_data is not None:
                old_info   = old_data.get("info", "")
                old_update = old_data.get("update", "")
                old_image  = old_data.get("image", "")
                has_xb6v   = old_data.get("has_xb6v", False)
                is_old_episodes = old_data.get("is_old_episodes", False) # 是否是旧的列表集数格式
                
                # 【修改处】：如果 info 没变，或者虽然变了但已经有 xb6v 源，都认为满足 info 条件
                info_condition_met = (old_info == item["info"]) or has_xb6v

                # 【修改处】：如果 episodes 格式是旧的，则不能跳过，必须强制重抓以更新为 dict 格式
                if (info_condition_met and old_image and old_update and not is_old_episodes):
                    print(f"  ({idx_i}/{len(items)}) [跳过-未更新] {item['name']}  info={item['info']}")
                    continue

            # 判定本次是新增 / 补图 / 补update / 补episode / 普通更新
            is_update = old_data is not None
            if is_update:
                if old_data.get("is_old_episodes", False):
                    tag = "[补episode]"  # ← 核心要求：当检测到旧格式时，日志输出 [补episode]
                elif not old_data.get("update"):
                    tag = "[补update]"
                elif old_data.get("info") == item["info"] and not old_data.get("image"):
                    tag = "[补图]"
                else:
                    tag = "[更新]"
            else:
                tag = "[新增]"

            print(f"  ({idx_i}/{len(items)}) {tag} {item['name']}  {item['url']}  info={item['info']}")

            detail_html = fetch(item["url"])
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            if not detail_html:
                continue

            try:
                # 【修改处】：接收返回值
                detail = parse_detail_page(detail_html, item["name"], item["url"], info=item["info"])
                
                # 【新增逻辑】：如果返回 None，说明没资源，直接跳过本次循环
                if detail is None:
                    continue

                # 详情页解析完拿到了新的 update... (后续逻辑保持不变)
                if is_update and old_data.get("update") and old_data.get("update") != detail.get("update", ""):
                    print(f"     [update 变化] {old_data.get('update')} → {detail.get('update')}")

                if is_update:
                    replaced = False
                    for i, old in enumerate(existing_list):
                        old_path = get_url_path(old.get("url", ""))
                        if old.get("name") == item["name"] and old_path == item_path:
                            existing_list[i] = detail
                            replaced = True
                            break
                    if not replaced:
                        existing_list.append(detail)
                    updated_count += 1
                else:
                    existing_list.append(detail)
                    new_count += 1

                # 【新增】：提取最新的播放列表中是否包含 xb6v
                new_has_xb6v = any(p.get("name") == "xb6v" for p in detail.get("playlist", []))

                # 检查新解析的集数格式是否已经成功转为 dict
                new_is_old = False
                for p in detail.get("playlist", []):
                    if isinstance(p.get("episodes"), list):
                        new_is_old = True
                        break

                # 索引同步更新
                index_map[key] = {
                    "info":   item["info"],
                    "update": detail.get("update", ""),
                    "image":  detail.get("image", ""),
                    "has_xb6v": new_has_xb6v,
                    "is_old_episodes": new_is_old,
                }
                save_data(all_data)
                print(f"     [已实时保存到磁盘]")
            except Exception as e:
                print(f"     [解析失败] {e}")

    return new_count, updated_count

def clean_existing_data(data: dict):
    for cat in data:
        if isinstance(data[cat], list):
            # 过滤掉 playlist 为空的条目
            data[cat] = [item for item in data[cat] if item.get("playlist")]


def main():
    final = load_existing(OUTPUT_FILE)
    clean_existing_data(final) # <--- 加上这一行即可清理旧的无效数据
    index = build_index(final)
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

            for cat_name, cat_cfg in categories_cfg.items():
                if cat_name not in final: final[cat_name] = []
                if cat_name not in index: index[cat_name] = {}

                if not cat_cfg.get("enabled"):
                    print(f"跳过分类: {cat_name}(在 [{sort_type}/{year or '无'}] 配置中未启用)")
                    continue

                new_n, upd_n = crawl_category(
                    cat_name, cat_cfg,
                    final[cat_name], index[cat_name],
                    final, year, sort_type
                )
                print(f"  → [{sort_type}] year={year or '无'} 分类 {cat_name} "
                      f"新增 {new_n} 条,更新 {upd_n} 条")

    print(f"\n✅ 全部抓取任务结束。")


if __name__ == "__main__":
    main()