import json
import os
import time
import random
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
PROTECTED_SOURCES = {"xb6v", "6vdy"}

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
            "Movie": {"id": 1, "enabled": True,  "pages": 1},
            "Drama": {"id": 2, "enabled": True,  "pages": 1},
            "Show":  {"id": 3, "enabled": True,  "pages": 1},
            "Anime": {"id": 4, "enabled": True,  "pages": 1},
        }
    }

historical_jobs = [get_year_config(str(y)) for y in range(2026, 2025, -1)]

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
                "Movie": {"id": 1, "enabled": True, "pages": 0},
                "Drama": {"id": 2, "enabled": True, "pages": 0},
                "Show": {"id": 3, "enabled": True, "pages": 1},
                "Anime": {"id": 4, "enabled": True, "pages": 0}
                }
            },
        ]
    },
    {
        "sort_type": "time",
        "enabled": False,
        "jobs": [
            {"year": "",
             "categories": {
                 "Movie": {"id": 1, "enabled": True, "pages": 1},
                 "Drama": {"id": 2, "enabled": True, "pages": 1},
                 "Show": {"id": 3, "enabled": True, "pages": 1},
                 "Anime": {"id": 4, "enabled": True, "pages": 1}
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

def format_date_str(date_str: str) -> str:
    """
    将日期字符串转换为 'YYYY-MM-DD' 格式。
    支持处理包含分隔符 '/' 的复杂字符串，取最后一个 '/' 后的内容进行解析。
    """
    if not date_str:
        return date_str

    # 1. 预处理：如果包含 '/' 或 '／'，取最后一个分隔符后面的内容
    # 使用正则表达式匹配英文斜杠 / 或中文全角斜杠 ／
    if '/' in date_str or '／' in date_str:
        # 使用 re.split 分割，取最后一部分
        # re.split(r'[/／]', date_str) 会返回一个列表，[-1] 取最后一个元素
        parts = re.split(r'[/／]', date_str)
        date_str = parts[-1].strip()

    try:
        # 2. 使用正则提取所有数字
        parts = re.findall(r'\d+', date_str)
        
        if len(parts) >= 3:
            # 提取年、月、日
            year, month, day = parts[0], parts[1], parts[2]
            # 使用 zfill 补零，确保月和日是两位数
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        elif len(parts) == 2:
            # 处理只有年月的情况，如 '2026年4月'
            return f"{parts[0]}-{parts[1].zfill(2)}"
        
        elif len(parts) == 1:
            # 处理只有年份的情况
            return parts[0]
            
    except Exception:
        pass
    
    # 如果解析失败，返回原字符串
    return date_str

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
            pass

    return ""


def extract_video_id(url: str, name: str) -> str:
    """从详情页 URL 中提取数字 ID；提取不到则用清洗后的 name。"""
    m = re.search(r"/(?:mv|vod|detail)/(\d+)", url)
    if m:
        return m.group(1)
    # 兜底：用 name 清洗成 safe 文件名
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
    返回 {category: {(name, path): {"info": info, "update": update, "image": image, "list_idx": idx}}},
    支持扫描 url, url1, url2 ... 等所有 urlX 字段。
    用于判断该条目是否已存在、update 是否变化,以及图片是否缺失。
    同时建立一个辅助索引，用于通过 path 快速反查其对应的真实 key (name, path)。
    """
    idx = {}
    for cat, items in existing.items():
        m = {}
        if isinstance(items, list):
            for list_idx, it in enumerate(items):
                name = it.get("name", "")
                info = it.get("info", "")
                update = it.get("update", "")
                image = it.get("image", "")

                if name:
                    # 找出所有以 "url" 开头的键（如 url, url1, url2...）
                    url_keys = [k for k in it.keys() if k == "url" or (k.startswith("url") and k[3:].isdigit())]
                    for key_name in url_keys:
                        url_val = it.get(key_name, "")
                        if url_val:
                            path = get_url_path(url_val)
                            # 将该 name 与每一个 url 对应的 path 组合，都存入索引中
                            m[(name, path)] = {
                                "info": info,
                                "update": update,
                                "image": image,
                                "real_name": name, # 记录在库中的真实名字
                                "real_path": path,  # 记录在库中的真实 path
                                "list_idx": list_idx # 【关键修改】：记录该条目在 existing_list 中的绝对位置
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

        # info：取 .pic span.s1 中的文本（如 "更新至14集"、"78集全"、"HD" 等）
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

    # ====== 提取播放列表并校验（前置逻辑） ======
    playlist = parse_playlist(soup)
    if not playlist:
        log(f"     [警告] 没有有效播放源，跳过该条目: {name}")
        return None

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

    # 【修改】：如果是新增项目，初始化时在 update 下方添加 update_pk，且初始值与 update 相同
    data = {
        "name": name,
        "url": url,
        "info": info,
        "update": update_time,
        "update_pk": update_time,  # 新增项目：初始时 update_pk 与 update 保持一致
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
        "playlist": playlist,  # 直接使用前面解析好的 playlist
    }

    # ====== 确认有播放源后，才开始下载封面图 ======
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

    # 提取其他字段
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
            # 3. 如果需要去掉 "(美国网络)" 中的 "网络" 二字
            cleaned = re.sub(r"\((.*?)(网络)\)", r"(\1)", cleaned)
            data["date"] = format_date_str(cleaned)
        elif text.startswith("又名："):
            data["alias"] = clean_ws(text)

    # ---- 评分（豆瓣 / IMDB） ----
    span = _find_span_by_label(info_block, "评分：")
    if span:
        for s in span.find_all("span"):
            t = clean_ws(s.get_text(" ", strip=True))
            if t:
                # 使用正则提取 platform 名称和分数，兼容 "豆瓣 7.2" 或 "IMDB --"
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
        log(f"\n[列表页] {list_url}", force=True)
        html = fetch(list_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if not html:
            continue

        items = parse_list_page(html)
        log(f"  -> 共找到 {len(items)} 部", force=True)

        for idx_i, item in enumerate(items, 1):
            item_path = get_url_path(item["url"])
            
            # 【核心修改 1】：多维度去重判定
            # 1. 首先尝试用 (name, path) 查找
            key = (item["name"], item_path)
            old_data = index_map.get(key)
            matched_by_path_only = False

            # 2. 如果没找到，再通过 path 唯一性查找（解决名字微调问题，如 "木乃伊2026" 变 "木乃伊"）
            if old_data is None:
                for idx_key, idx_val in index_map.items():
                    if idx_val.get("real_path") == item_path:
                        old_data = idx_val
                        key = idx_key # 锁定旧的索引 key
                        matched_by_path_only = True
                        break

            if old_data is not None:
                old_info   = old_data.get("info", "")
                old_update = old_data.get("update", "")
                old_image  = old_data.get("image", "")

                # 【核心修改 2】：恢复对 info 的比对。只有当 image, update 都有值，且 info 未发生改变时，才跳过
                if old_image and old_update and (old_info == item["info"]):
                    log(f"  ({idx_i}/{len(items)}) [跳过-未更新] {item['name']} (info一致)")
                    continue

            # 判定本次是新增 / 补图 / 补update / 普通更新
            is_update = old_data is not None
            if is_update:
                if matched_by_path_only:
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
                continue

            try:
                # 接收返回值
                detail = parse_detail_page(detail_html, item["name"], item["url"], info=item["info"])

                # 没抓到任何在线源 → 跳过
                if detail is None:
                    continue

                # 【修改处】：只有当确认有有效播放源，且不会被跳过时，才打印新增/更新的日志
                log(f"  ({idx_i}/{len(items)}) {tag} {item['name']}  {item['url']}  info={item['info']}", force=True)

                # ===== 【核心修改 1：任何更新名字 name 不要改】 =====
                if is_update:
                    # 强制还原为库中的旧名字（如 "木乃伊2026"），防止更名同步时覆盖
                    detail["name"] = key[0]

                # ===== 【核心修改 3：合并受保护源，并控制 6vdy 置顶】 =====
                old_entry = None
                target_list_idx = None # 💡 记录在 existing_list 中的绝对位置
                if is_update:
                    # 💡 核心修复：直接利用 index_map 中记录 of list_idx 索引位置，精准找到旧数据字典
                    target_list_idx = old_data.get("list_idx")
                    if target_list_idx is not None and target_list_idx < len(existing_list):
                        old_entry = existing_list[target_list_idx]

                if old_entry:
                    old_playlist = old_entry.get("playlist", [])
                    # 提取旧数据中属于 PROTECTED_SOURCES (xb6v, 6vdy) 的源
                    protected_in_old = [
                        p for p in old_playlist
                        if p.get("name") in PROTECTED_SOURCES
                    ]
                    if protected_in_old:
                        # 过滤掉新抓取数据中同名的受保护源
                        new_playlist = [
                            p for p in detail.get("playlist", [])
                            if p.get("name") not in PROTECTED_SOURCES
                        ]
                        
                        # 重新组装 playlist，确保 6vdy 始终放在第一位
                        final_playlist = []
                        
                        # 1. 先把 6vdy 找出来放最前面
                        vdy_source = next((p for p in protected_in_old if p.get("name") == "6vdy"), None)
                        if vdy_source:
                            final_playlist.append(vdy_source)
                            
                        # 2. 放入 xb6v 等其他可能存在的受保护源
                        for p in protected_in_old:
                            if p.get("name") != "6vdy":
                                final_playlist.append(p)
                                
                        # 3. 放入新抓取的其他源
                        final_playlist.extend(new_playlist)
                        
                        detail["playlist"] = final_playlist
                        kept_names = [p.get("name") for p in protected_in_old]
                        print(f"     [保留受保护源] {kept_names} (已置顶 6vdy)")

                    # 【新增逻辑插入点】
                    if is_update and old_entry:
                        old_info = old_entry.get("info", "")
                        new_info = item["info"]
                        old_pl = old_entry.get("playlist", [])
                        new_pl = detail.get("playlist", [])
                        
                        if old_info != new_info and old_pl != new_pl:
                            print(f"     [Info+Playlist更新] {item['name']} (Info: {old_info} -> {new_info})")

                    # 如果发生了更名，更新新数据中的字段，但保留其他历史字段
                    if matched_by_path_only:
                        print(f"     [更名同步] {key[0]} -> {item['name']} (已强行保留旧名 {key[0]})")

                # ===== 【核心修改：更新项目的 update/update_pk 处理逻辑】 =====
                if is_update and old_entry:
                    # 1. 强制保留旧的 update 字段值不被覆盖
                    detail["update"] = old_entry.get("update", "")
                    # 2. 将新抓取到的最新时间写入 update_pk 字段
                    # 这里的 detail["update_pk"] 已经在 parse_detail_page 里被提取并初始化为最新抓取的时间了
                    # 所以无需额外赋值，直接在下面重构字典时写入即可。
                    pass

                # ===== 【核心修改 2：字段排序重构（确保 url1 挨着 url，且 update_pk 挨着 update） =====
                # 重新构建 detail 字典，确保字段顺序符合规范
                ordered_detail = {}
                # 1. 放入 name
                ordered_detail["name"] = detail["name"]
                
                # 2. 放入主 url (如果是更新，强制使用老数据中的主 url，绝不覆盖！)
                if is_update and old_entry:
                    ordered_detail["url"] = old_entry.get("url", "")
                else:
                    ordered_detail["url"] = detail["url"]
                
                # 3. 紧接着放入旧条目中的所有 urlX 字段 (url1, url2 等)
                if old_entry:
                    for k, v in old_entry.items():
                        if k.startswith("url") and k != "url":
                            ordered_detail[k] = v
                
                # 4. 放入 info 字段
                if "info" in detail:
                    ordered_detail["info"] = detail["info"]

                # 5. 依次放入 update 和 update_pk，确保 update_pk 紧挨在 update 下面
                if "update" in detail:
                    ordered_detail["update"] = detail["update"]
                # 无论是新增（本来就有）还是更新（如果老数据没有就自动补上），都写入最新抓取的时间
                ordered_detail["update_pk"] = detail.get("update_pk", "")

                # 6. 放入剩余的所有其他字段
                for k, v in detail.items():
                    if k not in ordered_detail:
                        ordered_detail[k] = v
                
                # 用重新排序后的字典替换原 detail
                detail = ordered_detail

                # update_pk 变化提示
                if is_update and old_entry:
                    old_upk = old_entry.get("update_pk", "")
                    new_upk = detail.get("update_pk", "")
                    if old_upk != new_upk:
                        if not old_upk:
                            print(f"     [新增 update_pk 并更新] -> {new_upk}")
                        else:
                            print(f"     [update_pk 变化] {old_upk} → {new_upk}")

                if is_update:
                    # 💡 核心修复：直接通过记录的 target_list_idx 索引，精准替换，绝不 append 新增！
                    if target_list_idx is not None and target_list_idx < len(existing_list):
                        existing_list[target_list_idx] = detail
                    else:
                        # 兜底（极少发生，防止索引越界）
                        replaced = False
                        for i, old in enumerate(existing_list):
                            old_path = get_url_path(old.get("url", ""))
                            if (old.get("name") == key[0] and old_path == item_path) or (old_path == item_path):
                                existing_list[i] = detail
                                target_list_idx = i
                                replaced = True
                                break
                        if not replaced:
                            existing_list.append(detail)
                            target_list_idx = len(existing_list) - 1
                    updated_count += 1
                else:
                    existing_list.append(detail)
                    target_list_idx = len(existing_list) - 1
                    new_count += 1

                # 索引同步更新
                # 如果发生了更名，我们需要清理旧的索引 key，写入新的
                if matched_by_path_only and key in index_map:
                    del index_map[key]
                
                new_key = (item["name"], item_path)
                index_map[new_key] = {
                    "info":   item["info"],
                    "update": detail.get("update", ""),
                    "image":  detail.get("image", ""),
                    "real_name": item["name"],
                    "real_path": item_path,
                    "list_idx": target_list_idx # 💡 记录或更新当前的索引位置
                }
                save_data(all_data)
                log(f"     [已实时保存到磁盘]", force=True)
            except Exception as e:
                import traceback
                print(f"     [解析失败] {e}")
                traceback.print_exc()

    return new_count, updated_count

def clean_existing_data(data: dict):
    for cat in data:
        if isinstance(data[cat], list):
            # 过滤掉 playlist 为空的条目
            data[cat] = [item for item in data[cat] if item.get("playlist")]

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

# 注册程序退出时自动关闭
atexit.register(stop_caffeinate)

def main():
    # --- 新增：开启防休眠 ---
    start_caffeinate()

    final = load_existing(OUTPUT_FILE)
    clean_existing_data(final) # <--- 加上这一行即可清理旧 of 无效数据
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