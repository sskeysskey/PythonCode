# -*- coding: utf-8 -*-
"""
抓取 gg8.ukuzy0.com 的电影/剧集/综艺/动漫/纪录片，并合并写入本地 OVideos.json
"""
import os
import re
import json
import time
import hashlib
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ============================ 配置区 ============================
PAGE = 1  # 当前抓取页码（后续要抓更多页改这里即可）

BASE_DOMAIN = "https://gg8.ukuzy0.com"

# id -> 写入 JSON 的分组键
CATEGORIES = [
    # {"id": 1,  "group": "Movie", "label": "电影"},
    # {"id": 2,  "group": "Drama", "label": "剧集"},
    {"id": 3,  "group": "Show",  "label": "综艺"},
    # {"id": 4,  "group": "Anime", "label": "动漫"},
    # {"id": 24, "group": "Movie", "label": "纪录片"},  # 纪录片也并入 Movie
]

JSON_PATH = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_DOMAIN + "/",
}

REQUEST_TIMEOUT = 20
SLEEP_BETWEEN = 0.8       # 每次请求之间的间隔(秒)，礼貌一点
RETRY = 3

CHANNEL_NAME = "ukyun"    # 写入 playlist 的渠道名
PLAY_TYPE_PREFER = "ukm3u8"  # 详情页里取这种类型的播放地址


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
        time.sleep(1.5 * (i + 1))
    print(f"  [ERROR] fetch fail: {url} -> {last_err}")
    return None


def load_json():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 读取 JSON 失败：{e}，将以空结构开始。")
    return {"Movie": [], "Drama": [], "Show": [], "Anime": []}


def save_json(data):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    tmp = JSON_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp, JSON_PATH)
    except Exception as e:
        print(f"  [ERROR] 写入 JSON 失败: {e}")


def split_list_field(value):
    """把 '张三,李四 / 王五、赵六' 这种切成列表"""
    if not value:
        return []
    parts = re.split(r"[，,/、\|\s]+", value)
    return [p.strip() for p in parts if p.strip()]


def normalize_episode_name(name):
    """
    优化后的集数名称格式化
    - 识别 "第X集", "第X话", "X集" 等格式
    - 排除 "720P", "1080P" 等画质标签
    """
    if not name:
        return name
    
    # 1. 排除明显的画质标签 (如 720P, 1080P, 4K)
    if re.search(r'^\d+P$', name, re.IGNORECASE) or name.upper() == '4K':
        return name

    # 2. 尝试匹配 "第X集", "第X话", "第X期"
    m = re.search(r"第\s*(\d+)\s*[集话期]", name)
    if m:
        return f"第{int(m.group(1)):02d}集"
    
    # 3. 尝试匹配纯数字，或者 "X集" 这种格式
    # 注意：这里需要更严格一点，防止把 "720P" 误判
    # 只有当字符串本身就是数字，或者以 "集/话/期" 结尾时才转换
    m = re.search(r"^(\d+)\s*[集话期]?$", name)
    if m:
        return f"第{int(m.group(1)):02d}集"

    # 4. 如果都不匹配，原样返回（例如 "720P" 就会走到这里原样返回）
    return name


def image_filename_from_url(url, name=""):
    if not url:
        return ""
    parsed = urlparse(url)
    base = os.path.basename(parsed.path)
    
    # 优化：如果没有正常的图片扩展名（如 img.php 或 b6e61b7._jpg），则使用 MD5 生成安全的文件名
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
        print(f"     [图片] 已存在，跳过下载: {filename}")
        return True
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
        if r.status_code == 200:
            with open(target, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            print(f"     [图片] 下载成功: {filename} <- {url}")
            return True
        print(f"     [图片] [WARN] HTTP {r.status_code}: {url}")
    except Exception as e:
        print(f"     [图片] [WARN] 下载失败: {url} -> {e}")
    return False


def reorder_item_keys(item):
    """
    对字典的键进行重新排序：
    1. name
    2. url
    3. url1, url2, url3 ... (按数字顺序紧随其后)
    4. 其它标准字段
    """
    new_item = {}
    
    # 1. 先放 name 和 url
    if "name" in item:
        new_item["name"] = item["name"]
    if "url" in item:
        new_item["url"] = item["url"]
        
    # 2. 找出所有 urlN (如 url1, url2...) 并按数字大小排序，紧随其后
    url_keys = []
    for k in item.keys():
        if k.startswith("url") and k != "url":
            match = re.match(r"^url(\d+)$", k)
            if match:
                url_keys.append((int(match.group(1)), k))
    
    url_keys.sort()  # 升序排序
    for _, k in url_keys:
        new_item[k] = item[k]
        
    # 3. 放入其它标准字段
    preferred_order = [
        "info", "update", "image", "导演", "编剧", "主演", 
        "类型", "地区", "date", "alias", "intro", "评分", "playlist"
    ]
    for k in preferred_order:
        if k in item:
            new_item[k] = item[k]
            
    # 4. 兜底：放入可能存在的其它未知字段
    for k, v in item.items():
        if k not in new_item:
            new_item[k] = v
            
    return new_item


# ============================ 解析：列表页 ============================
def parse_listing(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    box = soup.select_one("div.xing_vb")
    if not box:
        return items

    for ul in box.find_all("ul"):
        li = ul.find("li")
        if not li:
            continue
        a = li.select_one("span.xing_vb4 a")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href:
            continue

        # info 在 em 中（类似 [更新至05集]）
        em = a.find("em")
        info = ""
        if em:
            info = em.get_text(strip=True)
            info = re.sub(r"^[[\【]|[]\】]$", "", info).strip("[]【】")
            em.extract()
        name = a.get_text(strip=True).strip(" \"'")
        if not name:
            continue

        type_span = li.select_one("span.xing_vb5")
        list_type = type_span.get_text(strip=True) if type_span else ""

        update_span = li.select_one("span.xing_vb7")
        update = update_span.get_text(strip=True) if update_span else ""

        full_url = urljoin(BASE_DOMAIN + "/", href.lstrip("/"))

        items.append({
            "name": name,
            "info": info,
            "detail_url": full_url,
            "list_type": list_type,
            "update": update,
        })
    return items


# ============================ 解析：详情页 ============================
def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "image_url": "",
        "alias": "",
        "导演": "",
        "编剧": [],
        "主演": [],
        "类型": [],
        "地区": "",
        "语言": "",
        "date": "",
        "update": "",
        "intro": "",
        "playlist_episodes": [],   # [(title, url), ...]
    }

    # 封面图解析优化
    img = soup.select_one("div.vodImg img")
    if img:
        # 优先取 data-original (懒加载)，其次取 src
        raw_url = (img.get("data-original") or img.get("src") or "").strip()
        
        # 尝试解析被代理脚本包装的真实图片地址，例如 /img.php?url=http...
        if "url=" in raw_url:
            try:
                qs = parse_qs(urlparse(raw_url).query)
                if 'url' in qs:
                    raw_url = qs['url'][0]
            except Exception:
                pass
                
        if raw_url:
            # 确保地址是绝对路径，解决 No connection adapters 报错
            data["image_url"] = urljoin(BASE_DOMAIN + "/", raw_url)

    # vodinfobox 中的 li
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
            elif "语言" in label_text:
                data["语言"] = value
            elif "上映" in label_text:
                data["date"] = value
            elif "更新时间" in label_text or "更新" in label_text:
                data["update"] = value

    # 剧情简介：第一个 div.vodplayinfo
    play_infos = soup.select("div.vodplayinfo")
    if play_infos:
        data["intro"] = play_infos[0].get_text(" ", strip=True)

    # 播放列表：找 ukm3u8 类型的 play_X
    chosen = None
    for play_div in soup.select('div[id^="play_"]'):
        suf = play_div.select_one("span.suf")
        if not suf:
            continue
        if suf.get_text(strip=True).lower() == PLAY_TYPE_PREFER:
            chosen = play_div
            break

    if chosen:
        episodes = []
        for li in chosen.select("ul li"):
            a = li.find("a")
            if not a:
                continue
            
            # 1. 获取原始文本 (优先取 title 属性，没有则取文本)
            raw_text = (a.get("title") or a.get_text(" ", strip=True)).strip()
            # 2. 获取 href (如果 href 看起来像个链接，也作为备选)
            href_attr = (a.get("href") or "").strip()

            # --- 核心修改：智能提取名称与链接 ---
            
            # 使用正则寻找 http/https 开头的起始位置
            # 匹配 http 或 https，后面跟着 ://
            m = re.search(r'(https?://[^\s]+)', raw_text)
            
            if m:
                # 找到了链接，截取链接部分
                url = m.group(1)
                # 链接之前的部分作为名称，并清理掉可能存在的 '$'
                name = raw_text[:m.start()].replace('$', '').strip()
            else:
                # 如果文本里没找到链接，尝试从 href 属性里拿
                # 有时候 href 里面就是链接，有时候 href 也是乱码，需要判断
                if href_attr.startswith("http"):
                    url = href_attr
                    name = raw_text.replace('$', '').strip()
                else:
                    # 实在解析不出链接，跳过
                    continue

            # 兜底：如果名称为空，给个默认值
            if not name:
                name = "第1集"
            
            if url:
                episodes.append((name, url))
                
        data["playlist_episodes"] = episodes

    return data


# ============================ 合并写入逻辑 ============================
def find_next_url_key(item):
    """
    如果 item['url'] 已经存在，则顺延查找 url1, url2, url3 ... 
    直到找到一个尚未被占用的 key 并返回。
    """
    if not item.get("url"):
        return "url"
    i = 1
    while item.get(f"url{i}"):
        i += 1
    return f"url{i}"


def build_new_item(new_data, merged_types, ukyun_channel):
    item = {
        "name": new_data["name"],
        "url": new_data["detail_url"],
        "info": new_data.get("info", ""),
        "update": new_data.get("update", ""),
        "image": "",  # 初始为空，稍后下载成功再写入
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
    return item


def merge_item(group_list, new_data, group_name):
    """
    返回 (item_ref, is_new, should_download_image)
    """
    name = new_data["name"]

    # 查找同名
    existing = None
    for it in group_list:
        if it.get("name") == name:
            existing = it
            break

    # 类型合并：列表页类型 + 详情页类型，去重
    merged_types = []
    for t in [new_data.get("list_type", "")] + new_data.get("类型", []):
        if t and t not in merged_types:
            merged_types.append(t)

    # 构造 ukyun 渠道
    ukyun_channel = {"name": CHANNEL_NAME, "episodes": {}}
    for ep_title, ep_url in new_data.get("playlist_episodes", []):
        key = normalize_episode_name(ep_title)
        if key and ep_url:
            ukyun_channel["episodes"][key] = ep_url

    # ---------- 全新条目 ----------
    if existing is None:
        item = build_new_item(new_data, merged_types, ukyun_channel)
        # 对全新条目也进行一次键排序（确保格式统一）
        item = reorder_item_keys(item)
        group_list.append(item)
        should_dl = bool(new_data.get("image_url"))
        print(f"     [状态] 发现全新条目，已创建。")
        print(f"     [字段] url -> {new_data['detail_url']}")
        return item, True, should_dl

    # ---------- 同名条目：按规则合并 ----------
    print(f"     [状态] 发现同名条目 (MERGED)")
    
    # 1) detail_url 顺延到下一个 urlN
    next_key = find_next_url_key(existing)
    existing[next_key] = new_data["detail_url"]
    print(f"     [字段更新] 新增链接 {next_key} -> {new_data['detail_url']}")

    # 2) info / update 覆盖（仅当抓到非空时）
    if new_data.get("info"):
        old_info = existing.get("info")
        existing["info"] = new_data["info"]
        if old_info != new_data["info"]:
            print(f"     [字段更新] info: '{old_info}' -> '{new_data['info']}'")
            
    if new_data.get("update"):
        old_update = existing.get("update")
        existing["update"] = new_data["update"]
        if old_update != new_data["update"]:
            print(f"     [字段更新] update: '{old_update}' -> '{new_data['update']}'")

    # 3) 其它字段：原为空才写入
    def fill_if_empty(key, value):
        if value in (None, "", [], {}):
            return
        cur = existing.get(key)
        if cur in (None, "", [], {}):
            existing[key] = value
            print(f"     [字段填充] {key} -> {value}")

    fill_if_empty("导演", new_data.get("导演", ""))
    fill_if_empty("编剧", new_data.get("编剧", []))
    fill_if_empty("主演", new_data.get("主演", []))
    fill_if_empty("地区", new_data.get("地区", ""))
    fill_if_empty("date", new_data.get("date", ""))
    fill_if_empty("alias", new_data.get("alias", ""))
    fill_if_empty("intro", new_data.get("intro", ""))

    # 4) 类型逻辑：【修改点】只有当目标分组是 Drama 时，才进行类型的合并与追加
    if group_name == "Drama":
        # 仅处理列表页获取的类型
        list_type = new_data.get("list_type", "")
        
        # 确保 existing 中有 "类型" 列表
        if "类型" not in existing or not isinstance(existing["类型"], list):
            existing["类型"] = []
            
        # 仅当 list_type 存在且不在现有列表中时追加
        if list_type and list_type not in existing["类型"]:
            existing["类型"].append(list_type)
            print(f"     [字段更新] 追加列表页类型 -> {list_type}")
        elif not list_type:
            print(f"     [信息] 列表页无类型，跳过追加。")
        else:
            print(f"     [信息] 类型 '{list_type}' 已存在，无需追加。")
    else:
        # 非 Drama 分组（如 Movie 等）：如果原本已经有类型，则保持原样，不追加新类型
        if not existing.get("类型"):
            existing["类型"] = merged_types
            print(f"     [字段填充] 类型 -> {merged_types}")
        else:
            print(f"     [信息] 分组为 '{group_name}'，跳过类型追加，保持原有类型：{existing['类型']}")

    if "评分" not in existing or not isinstance(existing.get("评分"), dict):
        existing["评分"] = {"豆瓣": "", "IMDB": ""}
    else:
        existing["评分"].setdefault("豆瓣", "")
        existing["评分"].setdefault("IMDB", "")

    # image：原为空才需要下载新图
    should_dl = False
    if not existing.get("image"):
        should_dl = bool(new_data.get("image_url"))
    else:
        print(f"     [信息] 库中已有封面图 '{existing.get('image')}'，不进行覆盖，跳过图片下载。")

    # 5) playlist：将 ukyun 渠道作为第一条插入；
    #    若已存在同名 ukyun 渠道，则只对其 episodes 做合并（不删旧条目，不动其他渠道）。
    if ukyun_channel["episodes"]:
        existing_pl = existing.get("playlist", []) or []
        idx_ukyun = -1
        for i, ch in enumerate(existing_pl):
            if ch.get("name") == CHANNEL_NAME:
                idx_ukyun = i
                break
        if idx_ukyun == -1:
            existing_pl.insert(0, ukyun_channel)
            print(f"     [播放源] 新增 '{CHANNEL_NAME}' 渠道，包含 {len(ukyun_channel['episodes'])} 集。")
        else:
            existing_pl[idx_ukyun].setdefault("episodes", {})
            before_count = len(existing_pl[idx_ukyun]["episodes"])
            existing_pl[idx_ukyun]["episodes"].update(ukyun_channel["episodes"])
            after_count = len(existing_pl[idx_ukyun]["episodes"])
            print(f"     [播放源] 合并 '{CHANNEL_NAME}' 渠道集数：从 {before_count} 集更新至 {after_count} 集。")
        existing["playlist"] = existing_pl

    # 在此处对 merged 条目进行原地重排键顺序，确保 url1, url2 紧随 url 之后
    ordered = reorder_item_keys(existing)
    existing.clear()
    existing.update(ordered)

    return existing, False, should_dl


# ============================ 主流程 ============================
def process_category(cat, data):
    list_url = f"{BASE_DOMAIN}/index.php/vod/type/id/{cat['id']}/page/{PAGE}.html?ac=detail"
    print(f"\n==================================================")
    print(f" 开始抓取分类 [{cat['label']}] -> 写入分组 [{cat['group']}]")
    print(f" 列表 URL: {list_url}")
    print(f"==================================================")

    html = fetch(list_url)
    if not html:
        print(f"[ERROR] 无法获取分类 [{cat['label']}] 的列表页，跳过此分类。")
        return

    items = parse_listing(html)
    total_items = len(items)
    print(f" 列表解析成功，共发现 {total_items} 个视频项目。")

    group_list = data.setdefault(cat["group"], [])

    for idx, it in enumerate(items, 1):
        print(f"\n  [{idx}/{total_items}] 正在处理: {it['name']}")
        print(f"     -> 详情页: {it['detail_url']}")
        
        time.sleep(SLEEP_BETWEEN)
        d_html = fetch(it["detail_url"])
        if not d_html:
            print("     [ERROR] 详情页抓取失败，跳过该项目。")
            continue
            
        d = parse_detail(d_html)

        # 详情页 update 优先；列表页兜底
        update = d.get("update") or it.get("update", "")

        new_data = {
            "name": it["name"],
            "detail_url": it["detail_url"],
            "info": it.get("info", ""),
            "update": update,
            "list_type": it.get("list_type", ""),
            "image_url": d.get("image_url", ""),
            "alias": d.get("alias", ""),
            "导演": d.get("导演", ""),
            "编剧": d.get("编剧", []),
            "主演": d.get("主演", []),
            "类型": d.get("类型", []),
            "地区": d.get("地区", ""),
            "date": d.get("date", ""),
            "intro": d.get("intro", ""),
            "playlist_episodes": d.get("playlist_episodes", []),
        }

        # 1. 合并数据到内存中的 data (传入 cat["group"] 作为分组标识)
        item_ref, is_new, should_dl = merge_item(group_list, new_data, cat["group"])
        
        # 2. 实时下载图片（若需要）
        if should_dl and new_data["image_url"]:
            fn = image_filename_from_url(new_data["image_url"], it["name"])
            if fn:
                # 只有下载成功，才把文件名写入字典，否则保持为空
                success = download_image(new_data["image_url"], fn)
                if success:
                    item_ref["image"] = fn
                    print(f"     [字段] 成功关联图片 -> {fn}")
                else:
                    print(f"     [字段] 图片下载失败，JSON 字段保持为空。")
        
        # 3. 实时写入 JSON 文件
        save_json(data)
        print(f"     [进度] 数据已实时保存至 JSON。")


def main():
    print("正在读取本地 JSON 数据库...")
    data = load_json()
    for k in ("Movie", "Drama", "Show", "Anime"):
        data.setdefault(k, [])

    for cat in CATEGORIES:
        try:
            process_category(cat, data)
        except Exception as e:
            print(f"[ERROR] 分类 {cat['label']} 处理失败: {e}")

    print("\n==================================================")
    print(" 任务全部完成！")
    print("==================================================")


if __name__ == "__main__":
    main()