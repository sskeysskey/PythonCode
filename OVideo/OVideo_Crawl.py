import json
import os
import time
import random
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from curl_cffi import requests as c_requests

# 1. 创建一个全局的 Session 对象
# 这样可以复用 TCP/TLS 连接，极大减少握手错误 (Error 35)
# 强制使用 HTTP/1.1 (http_version=1) 可以避免很多 CDN 的 HTTP/2 握手 Bug
http_session = c_requests.Session(
    impersonate="chrome", 
    http_version=1  # 强制降级到 HTTP/1.1，解决 WRONG_VERSION_NUMBER 报错
)

# =============================================================
# 配置区域
# =============================================================
# 列表页所在域名
LIST_BASE_URL = "https://www.pdy0.com"
# 详情页所在域名
DETAIL_BASE_URL = "https://www.pys2.com"
# 输出 JSON 文件路径
OUTPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
# 封面图片保存目录
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"

# 分类配置
CATEGORIES = {
    "Movie": {"id": 1, "enabled": True,  "pages": 4},
    "Drama": {"id": 2, "enabled": True,  "pages": 4},
    "Show":  {"id": 3, "enabled": True, "pages": 4},
    "Anime": {"id": 4, "enabled": True, "pages": 4},
    # "Short": {"id": 30, "enabled": True, "pages": 1},
}

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

def get_url_path(url: str) -> str:
    """提取 URL 的路径部分，用于忽略域名差异进行去重。例如提取 /mv/466215.html"""
    try:
        return urlparse(url).path
    except Exception:
        return url

def download_cover(img_url: str, video_id: str) -> str:
    """
    使用 curl_cffi Session 下载图片，增加稳定性和重试退避机制
    """
    if not img_url:
        return ""

    ensure_dir(COVER_IMAGE_DIR)

    # 取扩展名（容错处理 query string）
    base = img_url.split("?")[0].split("#")[0]
    ext = os.path.splitext(base)[1].lower()
    if ext not in ALLOWED_IMG_EXT:
        ext = ".jpg"

    # —— 文件名策略：用视频 ID ——
    filename = f"{video_id}{ext}"

    filepath = os.path.join(COVER_IMAGE_DIR, filename)

    # 如果文件已存在且大小大于0，直接跳过
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return filename

    headers = dict(HEADERS)
    headers["Referer"] = DETAIL_BASE_URL

    for i in range(RETRY_TIMES):
        try:
            # 2. 使用全局的 session 发起请求，而不是 c_requests.get
            resp = http_session.get(
                img_url, 
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            
            if resp.status_code == 200:
                # 确保完整接收数据后再写入，减少 Error 23 (写入失败) 的概率
                content = resp.content
                if content:
                    with open(filepath, "wb") as f:
                        f.write(content)
                        
                    if os.path.getsize(filepath) > 0:
                        print(f"     [封面已下载] {filename}")
                        return filename
                
                # 如果内容为空或文件大小为0，删除损坏的文件并重试
                if os.path.exists(filepath):
                    os.remove(filepath)
            else:
                print(f"     [图片HTTP {resp.status_code}] {img_url}")
                
        except Exception as e:
            print(f"     [图片下载失败 {i+1}/{RETRY_TIMES}] {e}")
            
        # 3. 失败后的随机退避策略 (Random Exponential Backoff)
        # 避免立刻重试再次撞上服务器的限流防火墙
        # if i < RETRY_TIMES - 1:
        #     sleep_time = random.uniform(1.0, 3.0) * (i + 1)
        #     time.sleep(sleep_time)

        # --- 修改后的退避逻辑 ---
        # if i < RETRY_TIMES - 1:
        #     # 基础等待时间 2-5 秒，随重试次数指数增加
        #     sleep_time = random.uniform(2.0, 5.0) * (2 ** i)
        #     print(f"     [退避] 等待 {sleep_time:.2f} 秒后重试...")
        #     time.sleep(sleep_time)
        
        # 每次失败后，强制等待 3 到 9 秒之间的随机时间
        if i < RETRY_TIMES - 1:
            sleep_time = random.uniform(4.0, 9.0)
            print(f"     [退避] 等待 {sleep_time:.2f} 秒后重试...")
            time.sleep(sleep_time)
            
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


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H-%M")


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
        "time": now_str(),
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
        "评分": [],
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
    # ====== 封面图结束 ======

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
            data["date"] = clean_ws(text)
        elif text.startswith("又名："):
            data["alias"] = clean_ws(text)

    # ---- 评分（豆瓣 / IMDB） ----
    span = _find_span_by_label(info_block, "评分：")
    if span:
        for s in span.find_all("span"):
            t = clean_ws(s.get_text(" ", strip=True))
            if t and ("豆瓣" in t or "IMDB" in t):
                data["评分"].append(t)

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
        return playlist

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
        if episodes:
            playlist.append({"name": channel_name, "episodes": episodes})
    return playlist


# =============================================================
# 主流程
# =============================================================
def build_list_url(cat_id: int, page: int) -> str:
    return f"{LIST_BASE_URL}/ms/{cat_id}--hits------{page}---.html"


def crawl_category(cat_name: str, cat_cfg: dict,
                   existing_list: list, index_map: dict) -> tuple[int, int]:
    """
    existing_list: final[cat_name]，原地修改（追加 / 替换）
    index_map:    index[cat_name]，{(name, path): info}，原地更新
    返回：(新增数量, 更新数量)
    """
    print(f"\n=== 开始抓取分类: {cat_name} (id={cat_cfg['id']}, pages={cat_cfg['pages']}) ===")
    new_count = 0
    updated_count = 0

    for page in range(1, cat_cfg["pages"] + 1):
        list_url = build_list_url(cat_cfg["id"], page)
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
            except Exception as e:
                print(f"     [解析失败] {e}")

    return new_count, updated_count


def main():
    # 1. 读取已有数据，构建去重索引
    final = load_existing(OUTPUT_FILE)
    index = build_index(final)
    print(f"已有数据分类数: {len(final)}；"
          f"总条目数: {sum(len(v) for v in final.values() if isinstance(v, list))}")

    # 2. 逐分类抓取（增量追加）
    for cat_name, cat_cfg in CATEGORIES.items():
        # 确保分类键存在
        if cat_name not in final or not isinstance(final[cat_name], list):
            final[cat_name] = []
        if cat_name not in index:
            index[cat_name] = {}

        if not cat_cfg.get("enabled"):
            print(f"跳过分类: {cat_name}（未启用）")
            continue

        new_n, upd_n = crawl_category(cat_name, cat_cfg, final[cat_name], index[cat_name])
        print(f"  → 分类 {cat_name} 新增 {new_n} 条，更新 {upd_n} 条")

    # 3. 写回文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=4)
    print(f"\n✅ 完成，已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()