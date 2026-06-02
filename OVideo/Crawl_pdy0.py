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
            "Movie": {"id": 1, "enabled": True,  "pages": 0},
            "Drama": {"id": 2, "enabled": True,  "pages": 5},
            "Show":  {"id": 3, "enabled": True,  "pages": 0},
            "Anime": {"id": 4, "enabled": True,  "pages": 0},
        }
    }

historical_jobs = [get_year_config(str(y)) for y in range(2019, 2010, -1)]

# 3. 组装 TASKS
TASKS = [
    {
        "sort_type": "score",
        "enabled": True,
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

# 【新增】：最低评分过滤配置
# 低于该分数的视频将直接在列表页阶段被过滤，不请求详情页
MIN_SCORE_LIMIT = 7.0

# ==========================================
# 【新增】：剧集数量限制配置
# ==========================================
DRAMA_MAX_EPISODES_LIMIT = 50  # 电视剧分类最大剧集限制（超过则跳过不抓）
ANIME_MAX_EPISODES_LIMIT = 30  # 动漫分类最大剧集限制（超过则跳过不抓）

# ==========================================
# 【新增】：电视剧分类（Drama）允许抓取的地区过滤集合
# ==========================================
DRAMA_ALLOWED_REGIONS = {"美国", "韩国", "英国", "日本", "泰国"}

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


def should_skip_info_update(old_info: str, new_info: str) -> bool:
    """
    判断是否应该跳过 info 的更新。
    如果新旧 info 均包含“第X集”或“X集”，且新集数 <= 旧集数，则返回 True（跳过更新，维持原样）。
    """
    if not old_info or not new_info:
        return False
        
    # 正则匹配“第X集”或“X集”或“更新至X”中的数字
    pattern = r'(?:更新至|第)?(\d+)(?:集|期)?'
    
    old_match = re.search(pattern, old_info)
    new_match = re.search(pattern, new_match) if 'new_match' in locals() else re.search(pattern, new_info)
    
    if old_match and new_match:
        try:
            old_num = int(old_match.group(1))
            new_num = int(new_match.group(1))
            # 如果新集数小于或等于旧集数，说明是倒退或未变，跳过更新
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
    支持扫描 url, url1, url2 ... 等所有 urlX 字段。
    用于判断该条目是否已存在、update 是否变化,以及图片是否缺失。
    同时建立一个辅助索引，用于通过 path 快速反查其对应的真实 key (name, path)。
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
                    # 找出所有以 "url" 开头的键（如 url, url1, url2...）
                    url_keys = [k for k in it.keys() if k == "url" or (k.startswith("url") and k[3:].isdigit())]
                    for key_name in url_keys:
                        url_val = it.get(key_name, "")
                        if url_val:
                            path = get_url_path(url_val)
                            # 全局扁平化索引，记录其所属分类 category
                            idx[(name, path)] = {
                                "info": info,
                                "update": update,
                                "image": image,
                                "real_name": name,
                                "real_path": path,
                                "category": cat,       # 记录所属分类
                                "list_idx": list_idx   # 记录在该分类列表中的绝对位置
                            }
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

        # 【新增】：提取评分 <span class="s2">
        score_val = 0.0
        s2 = li.select_one(".pic span.s2")
        if s2:
            score_text = clean_ws(s2.get_text(strip=True))
            # 如果评分是 "--" 或者为空，则视为 0.0 分
            if score_text and score_text != "--":
                try:
                    score_val = float(score_text)
                except ValueError:
                    score_val = 0.0

        # 【新增修改】：提取列表项中的年份和地区信息（用于 Show 和 Drama 分类的特殊过滤）
        # 结构：<p class="item-status text-overflow">2026 / 中国大陆 / 大陆综艺/汉语普通话</p>
        item_year = ""
        item_region = ""
        status_p = li.select_one("div.name p.item-status")
        if status_p:
            status_text = clean_ws(status_p.get_text(strip=True))
            # 提取开头的年份数字（如 2026）
            year_match = re.match(r"^(\d{4})", status_text)
            if year_match:
                item_year = year_match.group(1)
            
            # 使用斜杠分割提取地区（一般在第二个位置，即 index 为 1）
            parts = [p.strip() for p in re.split(r'[/／]', status_text)]
            if len(parts) >= 2:
                item_region = parts[1]

        items.append({
            "name": name,
            "url": full_url,
            "info": info,
            "score": score_val,
            "year": item_year,    # 将提取到的年份传回
            "region": item_region # 将提取到的地区传回
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
            # 修改点：先去除前缀 "又名："，然后再进行清理
            cleaned = text.replace("又名：", "", 1)
            data["alias"] = clean_ws(cleaned)

    # ---- 评分（豆瓣 / IMDB） ----
    span = _find_span_by_label(info_block, "评分：")
    if span:
        # 1. 先获取整段文本，用于处理没有明确写“豆瓣/IMDB”但有数字评分的情况
        full_span_text = clean_ws(span.get_text(" ", strip=True))
        
        # 尝试匹配具体的平台（原逻辑）
        has_platform_match = False
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
                        has_platform_match = True

        # 2. 【新增兼容】：如果上面没有匹配到明确的平台（比如你碰到的 “评分：6.6” 这种情况）
        if not has_platform_match and full_span_text:
            # 提取“评分：”后面的纯数字（支持整数和小数）
            num_match = re.search(r"评分：\s*([0-9.]+)", full_span_text)
            if num_match:
                score = num_match.group(1)
                data["评分"]["豆瓣"] = score  # 按照你的要求，默认写入到 "豆瓣" 中

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


# =============================================================
# 【已修改】：抓取分类，支持跨分类全局去重与移动
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
            # =============================================================
            # 【新增修改】：分类过滤逻辑分流
            # =============================================================
            if cat_name == "Show":
                # 综艺分类：不看评分，只看年份是否为 2026
                if item["year"] != "2026":
                    log(f"  ({idx_i}/{len(items)}) [跳过-年份不符] {item['name']} (年份: '{item['year']}' != '2026')")
                    continue
            elif cat_name == "Drama":
                # 电视剧分类：不仅过滤最低评分限制，同时增加地区过滤规则
                if item["score"] < MIN_SCORE_LIMIT:
                    log(f"  ({idx_i}/{len(items)}) [跳过-评分过低] {item['name']} (当前评分: {item['score']} < {MIN_SCORE_LIMIT})")
                    continue
                if item["region"] not in DRAMA_ALLOWED_REGIONS:
                    log(f"  ({idx_i}/{len(items)}) [跳过-地区不符] {item['name']} (地区: '{item['region']}' 不在允许列表中)")
                    continue
            else:
                # 电影、动漫分类：沿用原本的 7.0 评分过滤
                if item["score"] < MIN_SCORE_LIMIT:
                    log(f"  ({idx_i}/{len(items)}) [跳过-评分过低] {item['name']} (当前评分: {item['score']} < {MIN_SCORE_LIMIT})")
                    continue

            item_path = get_url_path(item["url"])
            
            # =============================================================
            # 【核心修改】：跨分类多维度去重判定
            # =============================================================
            key = (item["name"], item_path)
            old_data = global_index.get(key)
            matched_by_path_only = False
            is_special_6vdy_update = False

            # 1. 如果通过 (name, path) 没找到，进行跨分类全局 path 查找
            if old_data is None:
                for idx_key, idx_val in global_index.items():
                    if idx_val.get("real_path") == item_path:
                        old_data = idx_val
                        key = idx_key
                        matched_by_path_only = True
                        break

            # 2. 如果仍然没找到，进行跨分类全局同名 6vdy 规则判定
            if old_data is None:
                for cat, existing_list in all_data.items():
                    if not isinstance(existing_list, list):
                        continue
                    for list_idx, existing_item in enumerate(existing_list):
                        if existing_item.get("name") == item["name"]:
                            all_urls = {k: v for k, v in existing_item.items() if k == "url" or (k.startswith("url") and k[3:].isdigit())}
                            if len(all_urls) == 1 and "url" in all_urls:
                                old_url_val = all_urls["url"]
                                if "6vdy.org" in old_url_val:
                                    is_special_6vdy_update = True
                                    old_data = {
                                        "info": existing_item.get("info", ""),
                                        "update": existing_item.get("update", ""),
                                        "image": existing_item.get("image", ""),
                                        "real_name": existing_item.get("name"),
                                        "real_path": get_url_path(old_url_val),
                                        "category": cat,       # 记录当时所在的分类
                                        "list_idx": list_idx
                                    }
                                    key = (existing_item.get("name"), get_url_path(old_url_val))
                                    break
                    if is_special_6vdy_update:
                        break

            # 3. 拦截未更新、抢先版、集数未增加
            if old_data is not None and not is_special_6vdy_update:
                old_info   = old_data.get("info", "")
                old_update = old_data.get("update", "")
                old_image  = old_data.get("image", "")

                # 1. 只有当 image, update 都有值，且 info 未发生改变时，才跳过
                if old_image and old_update and (old_info == item["info"]):
                    log(f"  ({idx_i}/{len(items)}) [跳过-未更新] {item['name']} (info一致)")
                    continue

                # 2. 如果 info 发生了变化，但新 info 包含抢先版关键字，则不更新（跳过）
                if old_image and old_update and (old_info != item["info"]):
                    # 2a. 抢先版拦截
                    block_keywords = ['TC', 'TS', '抢先', 'HC']
                    new_info_upper = item["info"].upper()
                    if any(kw.upper() in new_info_upper for kw in block_keywords):
                        log(f"  ({idx_i}/{len(items)}) [跳过-抢先版拦截] {item['name']} (新info '{item['info']}' 包含抢先关键字)")
                        continue
                    
                    # 2b. 集数倒退/未增加拦截
                    if should_skip_info_update(old_info, item["info"]):
                        log(f"  ({idx_i}/{len(items)}) [跳过-集数未增加] {item['name']} (旧info '{old_info}' -> 新info '{item['info']}'，集数未增加)")
                        continue

            # 判定本次是新增 / 补图 / 补update / 普通更新 / 6vdy特殊更新
            is_update = (old_data is not None) or is_special_6vdy_update
            if is_update:
                if is_special_6vdy_update:
                    tag = "[6vdy特殊更新]"
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
                continue

            try:
                # 接收返回值
                detail = parse_detail_page(detail_html, item["name"], item["url"], info=item["info"])

                # 没抓到任何在线源 → 跳过
                if detail is None:
                    continue

                # =============================================================
                # 【新增修改】：针对 Drama 和 Anime 的最大剧集数限制过滤
                # =============================================================
                if detail.get("playlist"):
                    # 获取所有渠道中 episodes 字典大小的最大值
                    max_episodes = max(len(p.get("episodes", {})) for p in detail["playlist"])
                    
                    if cat_name == "Drama" and max_episodes > DRAMA_MAX_EPISODES_LIMIT:
                        log(f"  ({idx_i}/{len(items)}) [跳过-剧集数超限] {item['name']} (最大集数: {max_episodes} > {DRAMA_MAX_EPISODES_LIMIT})", force=True)
                        continue
                    elif cat_name == "Anime" and max_episodes > ANIME_MAX_EPISODES_LIMIT:
                        log(f"  ({idx_i}/{len(items)}) [跳过-剧集数超限] {item['name']} (最大集数: {max_episodes} > {ANIME_MAX_EPISODES_LIMIT})", force=True)
                        continue

                # 【修改处】：只有当确认有有效播放源，且不会被跳过时，才打印新增/更新的日志
                log(f"  ({idx_i}/{len(items)}) {tag} {item['name']}  {item['url']}  info={item['info']}", force=True)

                # ===== 【核心修改 1：任何更新名字 name 不要改】 =====
                if is_update:
                    # 强制还原为库中的旧名字（如 "木乃伊2026"），防止更名同步时覆盖
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

                # 合并受保护源
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

                # ==========================================
                # 【新增规则核心】：细粒度字段合并与更新
                # ==========================================
                if is_update and old_entry:
                    # 1. 强制保留旧的 update 字段值不被覆盖
                    detail["update"] = old_entry.get("update", "")

                    # 2. 针对 导演/编剧/主演/类型/地区/alias/intro 字段：
                    # 如果旧数据为空，而新抓取的数据不为空，则更新写入
                    for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]:
                        old_val = old_entry.get(field)
                        new_val = detail.get(field)
                        if not old_val and new_val:
                            print(f"     [补全字段] {field}: (空) -> {new_val}")
                        else:
                            # 否则保留旧值
                            detail[field] = old_val

                    # 3. 针对 date：如果旧数据为空，或者新抓取的内容长度大于旧内容，则更新写入
                    old_date = old_entry.get("date", "")
                    new_date = detail.get("date", "")
                    if new_date and (not old_date or len(new_date) > len(old_date)):
                        print(f"     [更新日期] date: {old_date or '(空)'} -> {new_date}")
                    else:
                        detail["date"] = old_date

                    # 4. 针对 评分（豆瓣/IMDB）：如果旧数据为空，新抓取的不为空，则更新写入
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
                # 1. 放入 name
                ordered_detail["name"] = detail["name"]
                
                # 2. 放入主 url (如果是更新，强制使用老数据中的主 url，绝不覆盖！)
                if is_update and old_entry:
                    ordered_detail["url"] = old_entry.get("url", "")
                else:
                    ordered_detail["url"] = detail["url"]
                
                # 处理 urlX 字段
                if is_special_6vdy_update and old_entry:
                    # 【核心修改】：将新抓取的 URL 作为 url1 插入，紧挨在 url 下方
                    ordered_detail["url1"] = detail["url"]
                    print(f"     [6vdy特殊合并] 已将新抓取的 URL 写入为 url1: {detail['url']}")
                elif old_entry:
                    # 普通更新：依次保留旧条目中的所有 urlX 字段 (url1, url2 等)
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

                # =============================================================
                # 【核心修改】：跨分类数据写入与索引重构
                # =============================================================
                if is_update:
                    # 判断是否发生了跨分类漂移
                    if old_category != cat_name:
                        print(f"     [跨分类移动] 检测到分类漂移: {old_category} ➔ {cat_name}")
                        # 1. 从旧分类列表中移除
                        if old_category in all_data and target_list_idx is not None:
                            if target_list_idx < len(all_data[old_category]):
                                all_data[old_category].pop(target_list_idx)
                        # 2. 追加到当前新分类中
                        if cat_name not in all_data:
                            all_data[cat_name] = []
                        all_data[cat_name].append(detail)
                        
                        # 3. 跨分类移动后，原有的 list_idx 全部失效，必须重新构建全局索引
                        global_index.clear()
                        global_index.update(build_index(all_data))
                    else:
                        # 同分类更新：直接利用 list_idx 精准替换
                        if target_list_idx is not None and target_list_idx < len(all_data[cat_name]):
                            all_data[cat_name][target_list_idx] = detail
                        else:
                            # 兜底
                            replaced = False
                            for i, old in enumerate(all_data[cat_name]):
                                old_path = get_url_path(old.get("url", ""))
                                if (old.get("name") == key[0] and old_path == item_path) or (old_path == item_path):
                                    all_data[cat_name][i] = detail
                                    replaced = True
                                    break
                            if not replaced:
                                all_data[cat_name].append(detail)
                    updated_count += 1
                else:
                    # 全新新增
                    if cat_name not in all_data:
                        all_data[cat_name] = []
                    all_data[cat_name].append(detail)
                    new_count += 1

                # 4. 重新构建/刷新全局索引（保证下一次循环时 list_idx 100% 准确）
                if matched_by_path_only and key in global_index:
                    del global_index[key]
                
                # 重新生成索引以确保所有分类的 list_idx 保持最新
                global_index.clear()
                global_index.update(build_index(all_data))

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
    start_caffeinate()

    final = load_existing(OUTPUT_FILE)
    clean_existing_data(final) 
    
    # 【已修改】：构建全局去重索引
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

            for cat_name, cat_cfg in categories_cfg.items():
                if cat_name not in final: final[cat_name] = []

                if not cat_cfg.get("enabled"):
                    print(f"跳过分类: {cat_name}(在 [{sort_type}/{year or '无'}] 配置中未启用)")
                    continue

                # 【已修改】：传入全局 final 和全局 global_index
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