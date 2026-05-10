import json
import os
import time
import random
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from curl_cffi import requests as c_requests

import ssl
from urllib3.util.ssl_ import create_urllib3_context

# 标准 requests 的 Session（作为 curl_cffi 失败时的兜底）
_std_session = requests.Session()

# 候选 impersonate 列表，失败时轮换
_IMPERSONATE_POOL = ["chrome", "chrome120", "chrome110", "safari17_0", "edge101"]


# ==========================================
# 抓取模式配置
# ==========================================
# 切换为 "score" 即可使用新规则
SORT_TYPE = "score" 

# ==========================================
# 多年份抓取任务配置 (核心修改点)
# ==========================================
# 你可以在这里自由配置多个年份，每个年份可以有完全不同的分类、是否启用(enabled)以及抓取页数(pages)
TASKS = [
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
            "Show":  {"id": 3, "enabled": False, "pages": 1},
            "Anime": {"id": 4, "enabled": True,  "pages": 2},
            # "Short": {"id": 30, "enabled": True, "pages": 1},
        }
    },
    # {
    #     "year": "2024",
    #     "categories": {
    #         "Movie": {"id": 1, "enabled": True,  "pages": 1},
    #         "Drama": {"id": 2, "enabled": True,  "pages": 1},
    #     }
    # }
]

# 1. 创建一个全局的 Session 对象
# 这样可以复用 TCP/TLS 连接，极大减少握手错误 (Error 35)
# 强制使用 HTTP/1.1 (http_version=1) 可以避免很多 CDN 的 HTTP/2 握手 Bug
http_session = c_requests.Session(
    impersonate="chrome", 
    http_version=1  # 强制降级到 HTTP/1.1，解决 WRONG_VERSION_NUMBER 报错
)

# 配置区域
# 列表页所在域名
LIST_BASE_URL = "https://www.pdy0.com"
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
    图片下载 - 多策略降级：
      1) curl_cffi 短连接（不复用 Session）+ 轮换 impersonate
      2) 协议切换（https <-> http）
      3) 标准 requests 兜底
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
    headers["Connection"] = "close"  # 关键：不要 Keep-Alive

    # 构造 URL 候选列表：原始 + 协议切换
    url_candidates = [img_url]
    if img_url.startswith("https://"):
        url_candidates.append("http://" + img_url[8:])
    elif img_url.startswith("http://"):
        url_candidates.append("https://" + img_url[7:])

    def _save(content: bytes) -> bool:
        if not content:
            return False
        with open(filepath, "wb") as f:
            f.write(content)
        if os.path.getsize(filepath) > 0:
            return True
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

    # ---------- 策略 1：curl_cffi 短连接 + 轮换指纹 ----------
    for attempt in range(RETRY_TIMES):
        impersonate = _IMPERSONATE_POOL[attempt % len(_IMPERSONATE_POOL)]
        for url in url_candidates:
            try:
                # 每次新建一个临时 session，用完即弃，避免连接池污染
                resp = c_requests.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    impersonate=impersonate,
                    verify=False,          # 容错：部分 CDN 证书链不完整
                )
                if resp.status_code == 200 and _save(resp.content):
                    print(f"     [封面已下载|curl_cffi/{impersonate}] {filename}")
                    return filename
                else:
                    print(f"     [curl_cffi HTTP {resp.status_code}] {url}")
            except Exception as e:
                msg = str(e)
                # 只打印关键信息，避免刷屏
                short = msg.split("See https")[0].strip()
                print(f"     [curl_cffi 失败 {attempt+1}/{RETRY_TIMES} impersonate={impersonate}] {short}")

        # 轻量退避
        time.sleep(random.uniform(1.5, 3.0))

    # ---------- 策略 2：标准 requests 兜底 ----------
    print("     [降级] 切换到标准 requests 库重试...")
    for url in url_candidates:
        try:
            resp = _std_session.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                verify=False,
                stream=False,
            )
            if resp.status_code == 200 and _save(resp.content):
                print(f"     [封面已下载|requests] {filename}")
                return filename
            else:
                print(f"     [requests HTTP {resp.status_code}] {url}")
        except Exception as e:
            print(f"     [requests 失败] {e}")

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
    返回 {category: {(name, path): {"info": info, "image": image}}}，
    用于判断该条目是否已存在、info 是否变化，以及图片是否缺失。
    注意：这里使用 URL 的 path（忽略域名）作为 key，实现多域名去重。
    """
    idx = {}
    for cat, items in existing.items():
        m = {}
        if isinstance(items, list):
            for it in items:
                name = it.get("name", "")
                url = it.get("url", "")
                info = it.get("info", "")
                image = it.get("image", "")
                if name and url:
                    # 提取路径，忽略域名差异
                    path = get_url_path(url)
                    m[(name, path)] = {"info": info, "image": image}
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
                      info: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "name": name,
        "url": url,
        "info": info,
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
        # 压缩多余空白
        data["intro"] = re.sub(r"\s+", "", intro_text)

    # 播放列表（仅在线观看）
    data["playlist"] = parse_playlist(soup)

    return data


def parse_playlist(soup) -> list[dict]:
    """只解析『在线观看』tab（#url-content1）下的播放列表。"""
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

        # 找到对应 ul
        ul_id = target.lstrip("#")
        # 同样限制在 online_section 内
        ul = online_section.find("ul", id=ul_id)
        episodes = []
        if ul:
            for a in ul.select("li a"):
                href = a.get("href", "")
                if href:
                    episodes.append(urljoin(DETAIL_BASE_URL, href))
        
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
def build_list_url(cat_id: int, page: int, year: str) -> str:
    """
    根据当前的 SORT_TYPE 配置和传入的 year，生成不同的 URL 结构
    """
    if SORT_TYPE == "score":
        # 新规律: https://www.pdy0.com/ms/1--score------2---2026.html
        return f"{LIST_BASE_URL}/ms/{cat_id}--score------{page}---{year}.html"
    else:
        # 原规律: https://www.pdy0.com/ms/1--hits------2---.html
        # 如果不是 score 模式，通常不需要年份参数，这里保持原样
        return f"{LIST_BASE_URL}/ms/{cat_id}--hits------{page}---.html"


def crawl_category(cat_name: str, cat_cfg: dict,
                   existing_list: list, index_map: dict, all_data: dict, year: str) -> tuple[int, int]:
    """
    existing_list: final[cat_name]，原地修改（追加 / 替换）
    index_map:    index[cat_name]，{(name, path): info}，原地更新
    返回：(新增数量, 更新数量)
    """
    print(f"\n=== 开始抓取分类: {cat_name} (id={cat_cfg['id']}, pages={cat_cfg['pages']}, year={year}) ===")
    new_count = 0
    updated_count = 0

    for page in range(1, cat_cfg["pages"] + 1):
        list_url = build_list_url(cat_cfg["id"], page, year)
        print(f"\n[列表页] {list_url}")
        html = fetch(list_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if not html:
            continue

        items = parse_list_page(html)
        print(f"  -> 共找到 {len(items)} 部")

        for idx_i, item in enumerate(items, 1):
            # 提取路径，忽略域名差异
            item_path = get_url_path(item["url"])
            key = (item["name"], item_path)
            old_data = index_map.get(key)

            if old_data is not None:
                old_info = old_data.get("info", "")
                old_image = old_data.get("image", "")

                # 如果 info 没变，且 image 不为空，则跳过
                if old_info == item["info"] and old_image:
                    print(f"  ({idx_i}/{len(items)}) [跳过-未更新] {item['name']}  info={item['info']}")
                    continue

            is_update = old_data is not None
            # 根据情况打印不同的 Tag
            if is_update and old_data.get("info") == item["info"] and not old_data.get("image"):
                tag = "[补图]"
            else:
                tag = "[更新]" if is_update else "[新增]"
                
            print(f"  ({idx_i}/{len(items)}) {tag} {item['name']}  {item['url']}  info={item['info']}")

            # 2. 抓详情页
            detail_html = fetch(item["url"])
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            if not detail_html:
                continue

            try:
                detail = parse_detail_page(
                    detail_html,
                    item["name"],
                    item["url"],
                    info=item["info"]
                )

                if is_update:
                    # 替换原有项（保留位置），匹配时同样忽略域名差异
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

                # 更新索引中的 info 和 image
                index_map[key] = {
                    "info": item["info"], 
                    "image": detail.get("image", "")
                }
                # 在此处实时保存
                save_data(all_data) 
                print(f"     [已实时保存到磁盘]")
            except Exception as e:
                print(f"     [解析失败] {e}")

    return new_count, updated_count


def main():
    # 1. 读取已有数据，构建去重索引
    final = load_existing(OUTPUT_FILE)
    index = build_index(final)
    print(f"已有数据分类数: {len(final)}；"
          f"总条目数: {sum(len(v) for v in final.values() if isinstance(v, list))}")

    # 2. 遍历多任务配置（按年份和分类抓取）
    for task in TASKS:
        year = task.get("year", "")
        categories_cfg = task.get("categories", {})
        
        print(f"\n==================================================")
        print(f"🚀 开始执行年份抓取任务: {year}")
        print(f"==================================================")

        for cat_name, cat_cfg in categories_cfg.items():
            # 确保分类键存在
            if cat_name not in final: final[cat_name] = []
            if cat_name not in index: index[cat_name] = {}

            if not cat_cfg.get("enabled"):
                print(f"跳过分类: {cat_name}（在 {year} 年配置中未启用）")
                continue

            # 传入 final 对象，以便在子函数中实时保存，同时传入 year
            new_n, upd_n = crawl_category(cat_name, cat_cfg, final[cat_name], index[cat_name], final, year)
            print(f"  → 年份 {year} 分类 {cat_name} 新增 {new_n} 条，更新 {upd_n} 条")

    print(f"\n✅ 全部年份抓取任务结束。")


if __name__ == "__main__":
    main()