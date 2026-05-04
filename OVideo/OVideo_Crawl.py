import json
import time
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# =============================================================
# 配置区域 (原 config.py)
# =============================================================
# 列表页所在域名
LIST_BASE_URL = "https://www.pdy0.com"
# 详情页所在域名
DETAIL_BASE_URL = "https://www.pys1.com"
# 输出 JSON 文件路径
OUTPUT_FILE = "/Users/yanzhang/Downloads/OVideos.json"

# 分类配置
CATEGORIES = {
    "Movie": {"id": 1, "enabled": True,  "pages": 2},
    "Drama": {"id": 2, "enabled": True,  "pages": 2},
    "Show":  {"id": 3, "enabled": False, "pages": 2},
    "Anime": {"id": 4, "enabled": False, "pages": 2},
    "Short": {"id": 5, "enabled": False, "pages": 2},
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


# =============================================================
# 工具函数
# =============================================================
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


# =============================================================
# 解析列表页：提取 (name, detail_url) 列表
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
        items.append({"name": name, "url": full_url})
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


def parse_detail_page(html: str, name: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "time": now_str(),
        "name": name,
        "url": url,
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

    info_block = soup.select_one("div.vod-info .info") or soup

    # 提取字段
    span = _find_span_by_label(info_block, "导演：")
    if span:
        directors = _split_by_slash(span)
        data["导演"] = directors[0] if directors else ""

    # ---- 编剧 ----
    span = _find_span_by_label(info_block, "编剧：")
    if span:
        data["编剧"] = _split_by_slash(span)

    # ---- 主演 ----
    span = info_block.select_one("span.zksq-actor") or _find_span_by_label(info_block, "主演：")
    if span:
        data["主演"] = _split_by_slash(span)

    # ---- 类型 ----
    span = _find_span_by_label(info_block, "类型：")
    if span:
        data["类型"] = _split_by_slash(span)

    # ---- 地区 ----
    span = _find_span_by_label(info_block, "地区：")
    if span:
        regions = _split_by_slash(span)
        data["地区"] = regions[0] if regions else ""

    # ---- 上映 / 又名 ----
    for span in info_block.find_all("span"):
        text = span.get_text(" ", strip=True)
        if text.startswith("上映："):
            data["date"] = text
        elif text.startswith("又名："):
            data["alias"] = text

    # ---- 评分（豆瓣 / IMDB） ----
    span = _find_span_by_label(info_block, "评分：")
    if span:
        for s in span.find_all("span"):
            t = s.get_text(" ", strip=True)
            if t and ("豆瓣" in t or "IMDB" in t):
                data["评分"].append(t)

    # ---- 剧情介绍 intro ----
    intro_box = soup.select_one("div.more-box.zksq-content")
    if intro_box:
        # 去掉 "[展开...]" 之类的展开链接
        for a in intro_box.find_all("a"):
            a.decompose()
        intro_text = intro_box.get_text(" ", strip=True)
        # 压缩多余空白
        data["intro"] = re.sub(r"\s+", "", intro_text)

    # ---- 播放列表 playlist ----
    data["playlist"] = parse_playlist(soup)

    return data


def parse_playlist(soup) -> list[dict]:
    """解析播放列表：tab 名字 + 对应 ul 中的 episodes 链接"""
    playlist = []

    # tabs
    tabs = soup.select(".playlist-tab ul.swiper-wrapper > li.swiper-slide")
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
        ul = soup.find("ul", id=ul_id)
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


def crawl_category(cat_name: str, cat_cfg: dict) -> list[dict]:
    print(f"\n=== 开始抓取分类: {cat_name} (id={cat_cfg['id']}, pages={cat_cfg['pages']}) ===")
    results = []
    for page in range(1, cat_cfg["pages"] + 1):
        list_url = build_list_url(cat_cfg["id"], page)
        print(f"\n[列表页] {list_url}")
        html = fetch(list_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if not html:
            continue

        items = parse_list_page(html)
        print(f"  -> 共找到 {len(items)} 部")

        for idx, item in enumerate(items, 1):
            print(f"  ({idx}/{len(items)}) {item['name']}  {item['url']}")
            detail_html = fetch(item["url"])
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            if not detail_html:
                continue
            try:
                detail = parse_detail_page(detail_html, item["name"], item["url"])
                results.append(detail)
            except Exception as e:
                print(f"     [解析失败] {e}")
    return results


def main():
    final = {}
    for cat_name, cat_cfg in CATEGORIES.items():
        if not cat_cfg.get("enabled"):
            print(f"跳过分类: {cat_name}（未启用）")
            final[cat_name] = []
            continue
        final[cat_name] = crawl_category(cat_name, cat_cfg)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=4)
    print(f"\n✅ 完成，已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()