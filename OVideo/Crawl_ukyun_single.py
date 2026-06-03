# -*- coding: utf-8 -*-
"""
独立详情页抓取工具：输入URL + 分类，自动写入 OVideos.json
与原爬虫 gg8.ukuzy0.com 完全兼容
"""
import os
import re
import json
import time
import hashlib
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ===================== 【必须和你原爬虫一样】 =====================
BASE_DOMAIN = "https://gg8.ukuzy0.com"
JSON_PATH = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
CHANNEL_NAME = "ukyun"
PLAY_TYPE_PREFER = "ukm3u8"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_DOMAIN + "/",
}

REQUEST_TIMEOUT = 20
RETRY = 3

# ============================ 工具函数 ============================
def fetch(url):
    last_err = None
    for i in range(RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.encoding = r.apparent_encoding or "utf-8"
            if r.status_code == 200 and r.text:
                return r.text
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(1)
    print(f"[ERROR] 抓取失败: {url} -> {last_err}")
    return None

def load_json():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"Movie": [], "Drama": [], "Show": [], "Anime": []}
    return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

def save_json(data):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def split_list_field(value):
    if not value:
        return []
    parts = re.split(r"[，,/、\|\s]+", value)
    return [p.strip() for p in parts if p.strip()]

def normalize_episode_name(name):
    if not name:
        return name
    if re.search(r'^\d+P$', name, re.IGNORECASE) or name.upper() == '4K':
        return name
    m = re.search(r"第\s*(\d+)\s*[集话期]", name)
    if m:
        return f"第{int(m.group(1)):02d}集"
    m = re.search(r"^(\d+)\s*[集话期]?$", name)
    if m:
        return f"第{int(m.group(1)):02d}集"
    return name

def image_filename_from_url(url, name=""):
    if not url:
        return ""
    parsed = urlparse(url)
    base = os.path.basename(parsed.path)
    if not re.search(r'\.(jpg|jpeg|png|webp|gif)$', base, re.IGNORECASE):
        h = hashlib.md5((name or url).encode("utf-8")).hexdigest()[:10]
        base = f"{h}.jpg"
    return base

def download_image(url, filename):
    if not url or not filename:
        return False
    os.makedirs(IMAGE_DIR, exist_ok=True)
    target = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[图片] 已存在: {filename}")
        return True
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
        if r.status_code == 200:
            with open(target, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            print(f"[图片] 下载成功: {filename}")
            return True
    except:
        print(f"[图片] 下载失败")
    return False

def reorder_item_keys(item):
    new_item = {}
    if "name" in item:
        new_item["name"] = item["name"]
    if "url" in item:
        new_item["url"] = item["url"]
    url_keys = []
    for k in item.keys():
        if k.startswith("url") and k != "url":
            match = re.match(r"^url(\d+)$", k)
            if match:
                url_keys.append((int(match.group(1)), k))
    url_keys.sort()
    for _, k in url_keys:
        new_item[k] = item[k]
    preferred_order = [
        "info", "update", "image", "导演", "编剧", "主演",
        "类型", "地区", "date", "alias", "intro", "评分", "playlist"
    ]
    for k in preferred_order:
        if k in item:
            new_item[k] = item[k]
    for k, v in item.items():
        if k not in new_item:
            new_item[k] = v
    return new_item

def find_next_url_key(item):
    if not item.get("url"):
        return "url"
    i = 1
    while item.get(f"url{i}"):
        i += 1
    return f"url{i}"

# ===================== 【核心：解析详情页】 =====================
def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "image_url": "", "alias": "", "导演": "", "编剧": [], "主演": [],
        "类型": [], "地区": "", "date": "", "update": "", "intro": "",
        "playlist_episodes": []
    }

    # ===================== 【正确抓取：name + info】 =====================
    # 抓取 name：<h2>甜性涩爱</h2>
    name = ""
    h2_tag = soup.select_one(".vod .vodh h2")
    if h2_tag:
        name = h2_tag.get_text(strip=True)

    # 抓取 info：<span>超清</span>
    info = ""
    info_tag = soup.select_one(".vod .vodh span")
    if info_tag:
        info = info_tag.get_text(strip=True)

    # update 时间（留空不影响）
    update = ""

    # 封面图
    img = soup.select_one("div.vodImg img")
    if img:
        raw_url = (img.get("data-original") or img.get("src") or "").strip()
        if "url=" in raw_url:
            try:
                qs = parse_qs(urlparse(raw_url).query)
                if 'url' in qs:
                    raw_url = qs['url'][0]
            except:
                pass
        data["image_url"] = urljoin(BASE_DOMAIN + "/", raw_url)

    # 详情信息
    info_box = soup.select_one("div.vodinfobox")
    if info_box:
        for li in info_box.find_all("li"):
            label_text = li.get_text(" ", strip=True)
            span = li.find("span")
            value = span.get_text(" ", strip=True) if span else ""
            if "别名" in label_text:
                data["alias"] = value
            elif "导演" in label_text:
                data["导演"] = value
            elif "编剧" in label_text:
                data["编剧"] = split_list_field(value)
            elif "主演" in label_text:
                data["主演"] = split_list_field(value)
            elif "类型" in label_text:
                data["类型"] = split_list_field(value)
            elif "地区" in label_text:
                data["地区"] = value
            elif "上映" in label_text:
                data["date"] = value
            elif "更新" in label_text:
                data["update"] = value

    # 简介
    play_infos = soup.select("div.vodplayinfo")
    if play_infos:
        data["intro"] = play_infos[0].get_text(" ", strip=True)

    # 播放列表
    chosen = None
    for play_div in soup.select('div[id^="play_"]'):
        suf = play_div.select_one("span.suf")
        if suf and suf.get_text(strip=True).lower() == PLAY_TYPE_PREFER:
            chosen = play_div
            break

    if chosen:
        for li in chosen.select("ul li"):
            a = li.find("a")
            if not a:
                continue
            raw_text = (a.get("title") or a.get_text(" ", strip=True)).strip()
            href_attr = a.get("href", "").strip()
            m = re.search(r'(https?://[^\s]+)', raw_text)
            if m:
                url = m.group(1)
                name_ep = raw_text[:m.start()].replace('$', '').strip()
            elif href_attr.startswith("http"):
                url = href_attr
                name_ep = raw_text.replace('$', '').strip()
            else:
                continue
            if not name_ep:
                name_ep = "第1集"
            data["playlist_episodes"].append((name_ep, url))

    return name, info, update, data

# ===================== 合并到 JSON =====================
def merge_item(group_list, new_data, detail_url):
    name = new_data["name"]
    existing = None
    for it in group_list:
        if it.get("name") == name:
            existing = it
            break

    merged_types = []
    for t in new_data.get("类型", []):
        if t and t not in merged_types:
            merged_types.append(t)

    ukyun_channel = {"name": CHANNEL_NAME, "episodes": {}}
    for ep_title, ep_url in new_data.get("playlist_episodes", []):
        key = normalize_episode_name(ep_title)
        if key and ep_url:
            ukyun_channel["episodes"][key] = ep_url

    # 新建
    if existing is None:
        item = {
            "name": name,
            "url": detail_url,
            "info": new_data.get("info", ""),
            "update": new_data.get("update", ""),
            "image": "",
            "导演": new_data.get("导演", ""),
            "编剧": new_data.get("编剧", []),
            "主演": new_data.get("主演", []),
            "类型": merged_types,
            "地区": new_data.get("地区", ""),
            "date": new_data.get("date", ""),
            "alias": new_data.get("alias", ""),
            "intro": new_data.get("intro", ""),
            "评分": {"豆瓣": "", "IMDB": ""},
            "playlist": [ukyun_channel] if ukyun_channel["episodes"] else [],
        }
        item = reorder_item_keys(item)
        group_list.append(item)
        return item, True

    # 合并
    next_key = find_next_url_key(existing)
    existing[next_key] = detail_url
    if new_data.get("info"):
        existing["info"] = new_data["info"]
    if new_data.get("update"):
        existing["update"] = new_data["update"]

    def fill(key, val):
        if val and not existing.get(key):
            existing[key] = val
    fill("导演", new_data.get("导演"))
    fill("编剧", new_data.get("编剧"))
    fill("主演", new_data.get("主演"))
    fill("地区", new_data.get("地区"))
    fill("date", new_data.get("date"))
    fill("alias", new_data.get("alias"))
    fill("intro", new_data.get("intro"))

    if ukyun_channel["episodes"]:
        pl = existing.get("playlist", [])
        idx = next((i for i, ch in enumerate(pl) if ch.get("name") == CHANNEL_NAME), -1)
        if idx == -1:
            pl.insert(0, ukyun_channel)
        else:
            pl[idx]["episodes"].update(ukyun_channel["episodes"])
        existing["playlist"] = pl

    ordered = reorder_item_keys(existing)
    existing.clear()
    existing.update(ordered)
    return existing, False

# ===================== 主程序 =====================
def main():
    print("===== 独立详情页抓取工具 =====")
    url = input("请输入详情页URL：").strip()
    cate = input("请输入分类 (Movie/Drama/Show/Anime)：").strip()

    if cate not in ["Movie", "Drama", "Show", "Anime"]:
        print("分类错误！")
        return

    print("正在抓取...")
    html = fetch(url)
    if not html:
        return

    name, info, update, d = parse_detail(html)
    print(f"抓取成功：{name} | {info}")

    new_data = {
        "name": name,
        "info": info,
        "update": update,
        "类型": d["类型"],
        "导演": d["导演"],
        "编剧": d["编剧"],
        "主演": d["主演"],
        "地区": d["地区"],
        "date": d["date"],
        "alias": d["alias"],
        "intro": d["intro"],
        "image_url": d["image_url"],
        "playlist_episodes": d["playlist_episodes"],
    }

    data = load_json()
    group = data[cate]
    item, is_new = merge_item(group, new_data, url)

    # 下载图片
    if d["image_url"] and not item.get("image"):
        fn = image_filename_from_url(d["image_url"], name)
        if download_image(d["image_url"], fn):
            item["image"] = fn

    save_json(data)
    print(f"\n✅ 成功写入：{cate} -> {name}")
    print("✅ 已保存到 OVideos.json")

if __name__ == "__main__":
    main()