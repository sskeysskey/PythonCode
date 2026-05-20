# -*- coding: utf-8 -*-
"""
xb6v.com 最新剧集爬取脚本
- 抓取首页 "最新剧集" 列表
- 进入子页面解析详细信息
- 校验播放列表不为空后，再下载封面图到 cover_image 目录
- 把结果合并写入 OVideos.json 的 Drama 分组
- 【新增规则】如果抓取到的播放列表为空，则不写入，直接跳过，且不下载图片，并打印日志
- 【新增规则】当剧集更新成功时，自动将 info 字段更新为 “更新至A集”，并打印 info 变更日志
"""

import os
import re
import json
import time
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

# ============== 配置 ==============
BASE_URL    = "https://www.xb6v.com/qian50m.html"
JSON_PATH   = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
GROUP_KEY   = "Drama"          # 写入的分组
PLAYLIST_NAME = "xb6v"         # playlist 里的 name
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0           # 每抓一个子页面之间的休眠秒数

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
}

# ============== 工具函数 ==============
def fetch(url, is_binary=False):
    """统一请求函数，自动处理编码"""
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if is_binary:
        return resp.content
    # xb6v 站点是 gb2312/gbk 编码，明确指定一下
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def normalize_text(s):
    """清理 HTML 里的特殊符号 & 空白"""
    if not s:
        return ""
    s = s.replace("&middot;", "·").replace("·", "·")
    s = s.replace("\xa0", " ").replace("&nbsp;", " ")
    s = re.sub(r"[，；;]\s*$", "", s)   # 去尾部多余的中文逗号/分号
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·•")
    return s


def split_name_info(raw_title):
    """
    根据规则拆分 name 与 info:
    碰到 '[' '［' 或者第一个空白符就分割
    """
    raw_title = raw_title.strip()
    # 找最早出现的分隔符位置
    m = re.search(r"[[\［\s]", raw_title)
    if not m:
        return raw_title, ""
    idx = m.start()
    name = raw_title[:idx].strip()
    info = raw_title[idx:].strip()
    return name, info


def safe_filename(url):
    """从图片 URL 提取文件名"""
    return os.path.basename(url.split("?")[0])


# ============== 播放列表（提取为字典结构）==============
def extract_episodes(soup):
    for widget in soup.select("div.widget.box.row"):
        h3 = widget.find("h3")
        if h3 and "播放地址（无需安装插件" in h3.get_text():
            eps = {}
            for a in widget.select("a.lBtn[href]"):
                href = a["href"]
                if "DownSys/play" in href:
                    # 获取剧集名称，优先取 a 标签内的文本，若为空则取 title 属性
                    ep_name = a.get_text(strip=True) or a.get("title", "").strip()
                    if ep_name:
                        eps[ep_name] = urljoin(BASE_URL, href)
            return eps
    return {}


# ============== 字段正则（兼容 主演/演员）==============
FIELD_PATTERNS = {
    "译名":     r"[◎®@]\s*译\s*名\s*[:：]?\s*(.+)",
    "片名":     r"[◎®@]\s*片\s*名\s*[:：]?\s*(.+)",
    "年代":     r"[◎®@]\s*年\s*代\s*[:：]?\s*(.+)",
    "产地":     r"[◎®@]\s*产\s*地\s*[:：]?\s*(.+)",
    "类别":     r"[◎®@]\s*类\s*别\s*[:：]?\s*(.+)",
    "上映":     r"[◎®@]\s*上映日期\s*[:：]?\s*(.+)",
    "IMDb评分": r"[◎®@]\s*IMDb评分\s*[:：]?\s*(.+)",
    "豆瓣评分": r"[◎®@]\s*豆瓣评分\s*[:：]?\s*(.+)",
    "导演":     r"[◎®@]\s*导\s*演\s*[:：]?\s*(.+)",
    "编剧":     r"[◎®@]\s*编\s*剧\s*[:：]?\s*(.+)",
    "主演":     r"[◎®@]\s*(?:主\s*演|演\s*员)\s*[:：]?\s*(.+)",
    "简介":     r"[◎®@]\s*简\s*介\s*[:：]?\s*(.*)",
}


def parse_post_lines(post_div):
    """
    把 #post_content 里所有文本按 <br> 切成一行行的列表，方便正则匹配
    """
    # 直接拿全部文本，<br>会被换行替代
    for br in post_div.find_all("br"):
        br.replace_with("\n")
    raw = post_div.get_text("\n")
    # 去掉两端无用引号、压缩空白
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip().strip('"').strip("'").strip()
        if ln:
            lines.append(ln)
    return lines


def match_field(lines, pattern):
    """
    某些条目可能跨行（例如导演只写了"导 演"，下一行才是名字），所以我们做粘合：
    如果一行匹配到字段名但内容为空，再粘合下一行非字段开头的行。
    """
    field_starter = re.compile(r"^[◎®@]")
    for i, ln in enumerate(lines):
        m = re.search(pattern, ln)
        if m:
            value = m.group(1).strip()
            # 内容为空或太短，尝试拼接后续非新字段行
            j = i + 1
            while (not value) and j < len(lines) and not field_starter.match(lines[j]):
                value = lines[j].strip()
                j += 1
            return value, i, j
    return "", -1, -1


def collect_multi(lines, start_idx):
    """
    收集 start_idx+1 .. 直到下一个 ◎/®/@ 开头的行 之间的所有行（用于主演/编剧多行场景）
    """
    field_starter = re.compile(r"^[◎®@]")
    out = []
    for k in range(start_idx + 1, len(lines)):
        if field_starter.match(lines[k]):
            break
        out.append(lines[k].strip())
    return out


# ============== 简介（兼容两种结构）==============
def extract_intro(post):
    for p in post.find_all("p"):
        # 把 <br> 替换为换行，但只在副本上做（避免影响其它解析）
        # 这里直接修改也无妨，因为 post_content 不再被复用
        for br in p.find_all("br"):
            br.replace_with("\n")
        raw = p.get_text("\n")
        if not re.search(r"[◎®@]\s*简\s*介", raw):
            continue

        # 结构 2：◎简介 与正文在同一个 <p> 内
        lines = [ln.strip().strip('"').strip("'").strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln and not re.match(r"^[◎®@]\s*简\s*介", ln)]
        if lines:
            return " ".join(lines)

        # 结构 1：正文在下一段 <p>
        nxt = p.find_next_sibling()
        while nxt:
            if nxt.name == "p":
                t = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True)).strip()
                if t and t not in (".", "•"):
                    return t
            nxt = nxt.find_next_sibling()
        break
    return ""


# ============== 评分解析（豆瓣 0 -> 空）==============
def parse_score(s):
    if not s:
        return ""
    m = re.match(r"\s*([\d.]+)\s*/\s*10", s)
    if not m:
        return ""
    val = m.group(1)
    try:
        if float(val) == 0:
            return ""
    except ValueError:
        return ""
    return val


# ============== 下载并本地化图片的辅助函数 ==============
def download_and_localize_image(img_url):
    """下载图片并返回本地文件名，失败则返回空字符串"""
    if not img_url:
        return ""
    fn = safe_filename(img_url)
    local_path = os.path.join(IMG_DIR, fn)
    if not os.path.exists(local_path):
        try:
            content = fetch(img_url, is_binary=True)
            os.makedirs(IMG_DIR, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            print(f"  [图片] 已下载 -> {fn}")
        except Exception as e:
            print(f"  [图片下载失败] {img_url}: {e}")
            return ""
    return fn


# ============== 子页面解析 ==============
def parse_subpage(sub_url, default_name, default_info):
    """解析子页面，返回一条 JSON 记录（此时 image 字段仅保存原始 img_url）"""
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    # 真正的标题（h1），用作 name 的兜底
    h1 = soup.select_one(".article_container h1")
    raw_title = h1.get_text(strip=True) if h1 else default_name
    name, info = split_name_info(raw_title)
    if not name:
        name = default_name
    if not info:
        info = default_info

    post = soup.select_one("#post_content")
    if not post:
        raise RuntimeError(f"子页面没有 #post_content: {sub_url}")

    # 简介（在 <br> 被替换前先抽，因为 extract_intro 内部会改 <br>）
    intro_text = extract_intro(post)

    # 封面图 URL (这里只提取，不下载)
    img_url = ""
    img_tag = post.find("img")
    if img_tag and img_tag.get("src"):
        img_url = img_tag["src"]

    # 解析正文行
    lines = parse_post_lines(post)

    # 通用字段
    def gv(key):
        v, _, _ = match_field(lines, FIELD_PATTERNS[key])
        return normalize_text(v)

    yi_ming   = gv("译名")
    pian_ming = gv("片名")
    chan_di   = gv("产地")
    lei_bie   = gv("类别")
    shang_ying = gv("上映")
    imdb_raw  = gv("IMDb评分")
    douban_raw = gv("豆瓣评分")

    # 导演 / 编剧 / 主演（多行）
    def collect_people(field_key):
        v, i, _ = match_field(lines, FIELD_PATTERNS[field_key])
        people = []
        if v:
            people.append(normalize_text(v))
        if i >= 0:
            for ex in collect_multi(lines, i):
                ex = normalize_text(ex)
                if ex:
                    people.append(ex)
        # 去重保序
        seen, out = set(), []
        for p in people:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    director_list = collect_people("导演")
    writer_list   = collect_people("编剧")
    actor_list    = collect_people("主演")
    director = director_list[0] if director_list else ""

    imdb_score   = parse_score(imdb_raw)
    douban_score = parse_score(douban_raw)

    # alias: 英文片名 + / + 译名（按你的要求英文在前）
    alias_parts = []
    if pian_ming:
        alias_parts.append(pian_ming)
    if yi_ming:
        alias_parts.append(yi_ming)
    alias_str = " / ".join(alias_parts) if alias_parts else ""

    # 类型 -> list
    types = []
    if lei_bie:
        types = [t for t in re.split(r"[\s/、,，]+", lei_bie) if t]

    episodes = extract_episodes(soup)
    playlist = []
    if episodes:
        playlist.append({"name": PLAYLIST_NAME, "episodes": episodes})

    rating = {"豆瓣": douban_score if douban_score else ""}
    if imdb_score:
        rating["IMDB"] = imdb_score

    return {
        "name":   name,
        "url":    sub_url,
        "info":   info,
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,  # 临时存放原始图片URL，后续确认不为空时再下载替换
        "导演":   director,
        "编剧":   writer_list,
        "主演":   actor_list,
        "类型":   types,
        "地区":   chan_di,
        "date":   shang_ying,
        "alias":  alias_str,
        "intro":  intro_text or "",
        "评分":   rating,
        "playlist": playlist,
    }


# ============== JSON 读写 ==============
def load_json():
    if not os.path.exists(JSON_PATH):
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def find_existing(data, name, url, group):
    """在指定分组中，只有 name 和 url 都一致时才判定为已存在"""
    for item in data.get(group, []):
        if item.get("name") == name and item.get("url") == url:
            return item
    return None


def merge_record(data, record, group):
    """根据 name 和 url 双重唯一性去重：均一致则更新，否则追加"""
    arr = data.setdefault(group, [])
    for i, item in enumerate(arr):
        if item.get("url") == record["url"] and item.get("name") == record["name"]:
            arr[i] = record
            return "updated"
    arr.append(record)
    return "added"


def detect_group_by_episodes(episodes):
    """
    根据播放列表按钮文字判断分组:
      - 出现 '集'  -> Drama
      - 否则       -> Movie  (含 国语 / 中字 / HD / BD 等)
    episodes 为空时返回 None,让调用方决定怎么处理
    """
    if not episodes:
        return None
    
    keys = list(episodes.keys())
    if any("集" in k for k in keys):
        return "Drama"
    
    MOVIE_TAGS = ("国语", "中字", "HD", "BD", "蓝光", "4K", "粤语", "英语", "高清", "TC", "正片")
    if any(tag in k for k in keys for tag in MOVIE_TAGS):
        return "Movie"
    
    return None  # 拿不准就跳过/告警


def get_list_by_tab(tab_index):
    """tab_index: 0=最新电影, 1=最新剧集, 2=小编推荐"""
    html = fetch(BASE_URL)
    soup = BeautifulSoup(html, "lxml")
    tab_content = soup.select_one("#tab-content")
    if not tab_content:
        raise RuntimeError("找不到 #tab-content")
    
    # 过滤掉空的或者不符合预期的 ul
    uls = [ul for ul in tab_content.find_all("ul", recursive=False) if ul.find("li")]
    
    if len(uls) <= tab_index:
        print(f"警告：期望获取索引为 {tab_index} 的列表，但实际只找到 {len(uls)} 个有效列表")
        return []
        
    target_ul = uls[tab_index]
    items = []
    for a in target_ul.select("li > a[href]"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        name, info = split_name_info(title)
        items.append((name, info, urljoin(BASE_URL, href)))
    return items


def find_existing_any_group(data, name, url):
    """在 Drama 和 Movie 两个组里查找 name 和 url 均匹配的记录"""
    for g in ("Drama", "Movie"):
        for item in data.get(g, []):
            if item.get("url") == url and item.get("name") == name:
                return g, item
    return None, None


def process_recommend(data):
    print("[抓取] 小编推荐 ...")
    items = get_list_by_tab(2)
    print(f"  共发现 {len(items)} 条")
    ok, fail = 0, 0

    for idx, (name, info, url) in enumerate(items, 1):
        print(f"  ({idx}/{len(items)}) {name}  [{info}]")
        try:
            # 先看看这条 url 和 name 在两个组里是不是已经有了
            old_group, existing = find_existing_any_group(data, name, url)

            if existing:
                # 已存在: 只抓 episodes,然后做 upsert
                eps = fetch_playlist_only(url)
                status, added, total = upsert_playlist(existing, eps)
                if status == "updated":
                    old_info = existing.get("info", "")
                    new_info = f"更新至{total}集"
                    existing["info"] = new_info
                    print(f"    ✓ 更新({old_group}): 新增 {added} 集")
                    print(f"      [info字段更新] 共有 {total} 集，info由原来的「{old_info}」更新为「{new_info}」")
                    ok += 1
                elif status == "no_change":
                    print(f"    - 无更新({old_group})")
                    ok += 1
                elif status == "decreased":
                    print(f"    - 忽略({old_group}): 集数减少")
                    ok += 1
                elif status == "no_new":
                    print(f"    ! 忽略({old_group})：抓取到的播放列表为空，不作更新")
                    fail += 1
                else:
                    print(f"    ! 已存在但未抓到播放列表({old_group})")
                    fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # 新记录: 完整解析
            rec = parse_subpage(url, name, info)

            # 用 episodes 判定分组
            episodes = {}
            for pl in rec.get("playlist", []):
                if pl.get("name") == PLAYLIST_NAME:
                    episodes = pl.get("episodes", {})
                    break

            # 全新记录如果 episodes 为空，则不写入并跳过（此时图片完全未下载）
            if not episodes:
                print("    ! 忽略跳过：该新纪录未抓取到任何播放列表(episodes为空)")
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # 确定播放列表不为空，开始下载图片并本地化
            img_url = rec.get("image", "")
            rec["image"] = download_and_localize_image(img_url)

            group = detect_group_by_episodes(episodes)
            if group is None:
                # 理论上上面已经拦截了 episodes 为空的情况，这里作为兜底
                print("    ! 无 episodes,默认按 Movie 处理")
                group = "Movie"

            status = merge_record(data, rec, group)
            ep_count = len(episodes)
            print(f"    ✓ {status} -> {group} (共 {ep_count} 集/源)")
            ok += 1

        except Exception as e:
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    return ok, fail


def upsert_playlist(existing, new_episodes):
    """
    更新播放列表：
    - 返回状态码、新增集数和更新后的总集数 (status, added_count, total_count)
    - status: "no_new" (没抓到/为空), "no_change" (无变化), "decreased" (减少了), "updated" (已更新)
    """
    if not new_episodes:
        return "no_new", 0, 0

    # 查找已有的 xb6v 播放列表
    old_episodes = {}
    for pl in existing.get("playlist", []):
        if pl.get("name") == PLAYLIST_NAME:
            old_episodes = pl.get("episodes", {})
            break

    # 1. 无论内容还是条数都没有变化 -> 跳过
    if new_episodes == old_episodes:
        return "no_change", 0, len(old_episodes)

    # 2. 条目减少的时候 -> 不用写入
    if len(new_episodes) < len(old_episodes):
        return "decreased", 0, len(old_episodes)

    # 3. 发生了变化（增加或内容变更） -> 覆盖写入并更新时间
    added_count = len(new_episodes) - len(old_episodes)
    total_count = len(new_episodes)
    
    new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
    others = [pl for pl in existing.get("playlist", []) if pl.get("name") != PLAYLIST_NAME]
    
    existing["playlist"] = [new_pl] + others
    existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return "updated", added_count, total_count


def fetch_playlist_only(sub_url):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")
    return extract_episodes(soup)


# ============== 主流程 ==============
def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/3] 抓取首页最新剧集列表 ...")
    items = get_list_by_tab(1)
    print(f"  共发现 {len(items)} 条")

    data = load_json()

    print("[2/3] 逐个抓取子页面 ...")
    ok, fail = 0, 0
    for idx, (name, info, url) in enumerate(items, 1):
        print(f"  ({idx}/{len(items)}) {name}  [{info}]")
        try:
            # 传入 url，只有 name 和 url 双重一致时才算 existing
            existing = find_existing(data, name, url, "Drama")
            if existing:
                # 记录已存在，仅抓取播放列表进行比对
                eps = fetch_playlist_only(url)
                status, added_count, total_count = upsert_playlist(existing, eps)
                
                if status == "updated":
                    old_info = existing.get("info", "")
                    new_info = f"更新至{total_count}集"
                    existing["info"] = new_info
                    print(f"    ✓ 更新：发现新剧集，新增 {added_count} 集，已覆盖写入")
                    print(f"      [info字段更新] 共有 {total_count} 集，info由原来的「{old_info}」更新为「{new_info}」")
                    ok += 1
                elif status == "no_change":
                    print("    - 无更新跳过：剧集内容 and 条数均无变化")
                    ok += 1
                elif status == "decreased":
                    print("    - 忽略跳过：抓取到的剧集数量少于已有数量，不作更新")
                    ok += 1
                elif status == "no_new":
                    # 【修改点】已存在记录，但新抓取的播放列表为空时的日志标出
                    print("    ! 忽略跳过：抓取到的播放列表为空，不作更新")
                    fail += 1
                else:
                    print("    ! 重名，但未抓到播放列表")
                    fail += 1
            else:
                # 全新记录（即使 name 重名，只要 url 不同也走这里），走完整解析流程
                rec = parse_subpage(url, name, info)
                
                # --- 计算集数并检查是否为空 ---
                ep_count = 0
                if "playlist" in rec and isinstance(rec["playlist"], list):
                    for pl in rec["playlist"]:
                        if pl.get("name") == PLAYLIST_NAME:
                            ep_count = len(pl.get("episodes", {}))
                            break
                
                # 全新记录如果播放列表为空，则不写入并跳过（此时图片完全未下载）
                if ep_count == 0:
                    print("    ! 忽略跳过：该新纪录未抓取到任何播放列表(episodes/playlist为空)")
                    fail += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

                # 确定播放列表不为空，开始下载图片并本地化
                img_url = rec.get("image", "")
                rec["image"] = download_and_localize_image(img_url)

                status = merge_record(data, rec, "Drama")
                print(f"    ✓ {status} (共 {ep_count} 集)")
                ok += 1
        except Exception as e:
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    r_ok, r_fail = process_recommend(data)
    
    print("[写入] OVideos.json ...")
    save_json(data)
    print(f"完成: 剧集 成功 {ok}/失败 {fail}, 推荐 成功 {r_ok}/失败 {r_fail}")


if __name__ == "__main__":
    main()