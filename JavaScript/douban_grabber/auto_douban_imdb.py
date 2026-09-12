#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣 + IMDb 一次性抓取与回写  (v3)

流程：
  剪贴板取名字 → 在 OVideos.json 找项目 →
  抓豆瓣(日期/评分/外文标题/又名/imdb_id/导演/编剧/主演/类型/简介) → 写回 →
  ┌ 若豆瓣页面带 IMDb ID → 直接跳转 https://www.imdb.com/title/ttXXXX/（最稳，跳过搜索）
  └ 否则 → 按语种优先级挑检索词 → IMDb 搜索框 → 抓评分
  → 写回 → 结束

依赖: pyautogui, 以及同目录下你已有的 screenshot.py
"""

import os
import re
import sys
import time
import json
import glob
import subprocess
from pathlib import Path

PYTHON_CODE_DIR = '/Users/yanzhang/Coding/python_code'
sys.path.insert(0, PYTHON_CODE_DIR)

import pyautogui
from screenshot import ScreenDetector

# ================= 配置区域 =================
OVIDEOS_JSON  = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
DOWNLOADS_DIR = Path.home() / 'Downloads'

# —— 模板图 ——（input 用相对文件名，走 ScreenDetector 默认目录；popup 用绝对路径）
DOUBAN_INPUT_IMG = 'douban_input.png'
DOUBAN_POPUP_IMG = '/Users/yanzhang/Coding/python_code/Resource/douban_popup.png'
IMDB_INPUT_IMG   = 'imdb_input.png'
IMDB_POPUP_IMG   = '/Users/yanzhang/Coding/python_code/Resource/imdb_popup.png'

# —— 插件下载文件名模式 ——
DOUBAN_DOWNLOAD_GLOB = 'douban_result*.json'
IMDB_DOWNLOAD_GLOB   = 'imdb_result*.json'

# —— IMDb 直达 ——
IMDB_TITLE_URL = 'https://www.imdb.com/title/{}/'

# —— 等待时间（秒）——
WAIT_AFTER_PASTE      = 2
WAIT_POPUP_APPEAR     = 20
WAIT_PAGE_LOAD        = 4
WAIT_DOWNLOAD_TIMEOUT = 30
WAIT_NAV_TIMEOUT      = 15   # 直达跳转时等待 URL 变化
SECOND_CLICK_Y_OFFSET = 50   # 第二次点击相对图片中心的 Y 偏移（逻辑像素）
# ===========================================

pyautogui.FAILSAFE = True


# ------------------ 基础工具 ------------------
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def read_clipboard() -> str:
    """读取当前剪贴板内容（项目名）。"""
    p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
    out, _ = p.communicate()
    return out.decode('utf-8').strip()


def copy_to_clipboard(text):
    p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
    p.communicate(text.encode('utf-8'))


def clear_old_downloads(pattern):
    for f in glob.glob(str(DOWNLOADS_DIR / pattern)):
        try:
            os.remove(f)
        except Exception:
            pass


def wait_for_download(pattern, timeout):
    start = time.time()
    while time.time() - start < timeout:
        files = [f for f in glob.glob(str(DOWNLOADS_DIR / pattern))
                 if not f.endswith('.crdownload')]
        if files:
            time.sleep(0.5)
            return max(files, key=os.path.getmtime)
        time.sleep(0.5)
    return None


def move_to_trash(path):
    script = f'tell application "Finder" to delete (POSIX file "{path}" as alias)'
    subprocess.run(['osascript', '-e', script],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def click_image_center(detector, location, shape, y_offset=0):
    phys_cx = location[0] + shape[1] // 2
    phys_cy = location[1] + shape[0] // 2
    logic_x = int(phys_cx / detector.scale_factor)
    logic_y = int(phys_cy / detector.scale_factor) + y_offset
    pyautogui.click(logic_x, logic_y)
    print(f"点击(逻辑坐标): ({logic_x}, {logic_y})  y_offset={y_offset}")


# ============================================================
#                语种判定 / 检索词挑选（核心重写）
# ============================================================
# 拉丁字母（含重音扩展）
RE_LATIN   = re.compile(r'[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]')
# 汉字
RE_HAN     = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]')
# 日文假名（平/片假名、半角片假名）
RE_KANA    = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\uFF66-\uFF9D]')
# 韩文
RE_HANGUL  = re.compile(r'[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]')
# 其他非拉丁字母体系：西里尔/希腊/希伯来/阿拉伯/天城文/泰文
RE_OTHER   = re.compile(r'[\u0400-\u04FF\u0370-\u03FF\u0590-\u05FF'
                        r'\u0600-\u06FF\u0900-\u097F\u0E00-\u0E7F]')
# 括号里的地区/版本注释，如 (台) （港） [美] 【韩】
RE_REGION_TAG = re.compile(r'[\(\uFF08\[\uFF3B\u3010][^\)\uFF09\]\uFF3D\u3011]{0,12}'
                           r'[\)\uFF09\]\uFF3D\u3011]')
# 连续的「拉丁可检索片段」
RE_LATIN_RUN = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF0-9'\u2019\-\.\:\&, ]+")

_STRIP_CHARS = " \t\u3000-\u2013\u2014:\uFF1A,\uFF0C\u3001.\u00b7\"\u201c\u201d'\u2018\u2019"

TIER_PURE_LATIN  = 0   # 纯英文/拉丁
TIER_MIXED_LATIN = 1   # 拉丁 + 非拉丁混排（抽拉丁片段）
TIER_NON_CN_EN   = 2   # 非中文且非英文（日/韩/俄/印地…）
TIER_CHINESE     = 3   # 纯中文
TIER_DROP        = 9   # 丢弃


def clean_candidate(text: str) -> str:
    """清洗单个候选串：去地区注释、归一空白、剥首尾杂符号。"""
    if not text:
        return ''
    t = str(text)
    t = RE_REGION_TAG.sub(' ', t)
    t = t.replace('\u3000', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    t = t.strip(_STRIP_CHARS).strip()
    return t


def _script_flags(t: str) -> dict:
    return {
        'latin':  bool(RE_LATIN.search(t)),
        'han':    bool(RE_HAN.search(t)),
        'kana':   bool(RE_KANA.search(t)),
        'hangul': bool(RE_HANGUL.search(t)),
        'other':  bool(RE_OTHER.search(t)),
    }


def extract_latin_run(t: str) -> str:
    """从混排串里抽出最长的拉丁片段，如「Chumbak 幸福邻距离」→「Chumbak」。"""
    runs = [r.strip(_STRIP_CHARS).strip() for r in RE_LATIN_RUN.findall(t)]
    runs = [r for r in runs if RE_LATIN.search(r) and len(r) >= 2]
    return max(runs, key=len) if runs else ''


def is_chinese(text: str) -> bool:
    """纯中文判定：含汉字，且不含假名/韩文/其他文字体系。"""
    t = str(text or '')
    f = _script_flags(t)
    return f['han'] and not (f['kana'] or f['hangul'] or f['other'])


def is_english(text: str) -> bool:
    """纯拉丁判定（可含数字、标点、重音字母）。"""
    t = clean_candidate(text)
    if not t:
        return False
    f = _script_flags(t)
    non_latin = f['han'] or f['kana'] or f['hangul'] or f['other']
    if f['latin'] and not non_latin:
        return True
    # 纯 ASCII 数字标题，如 "1917"
    return (not non_latin) and t.isascii() and any(c.isalnum() for c in t)


def classify_candidate(text: str):
    """返回 (tier, 实际用于检索的字符串)。"""
    t = clean_candidate(text)
    if not t:
        return TIER_DROP, ''
    f = _script_flags(t)
    non_latin = f['han'] or f['kana'] or f['hangul'] or f['other']

    if f['latin'] and not non_latin:
        return TIER_PURE_LATIN, t
    if f['latin'] and non_latin:
        return TIER_MIXED_LATIN, (extract_latin_run(t) or t)
    if non_latin:
        if f['han'] and not (f['kana'] or f['hangul'] or f['other']):
            return TIER_CHINESE, t
        return TIER_NON_CN_EN, t
    # 无任何字母：数字/符号标题
    if t.isascii() and any(c.isalnum() for c in t):
        return TIER_PURE_LATIN, t
    return TIER_DROP, ''


def split_aka(aka: str):
    """把「又名」整段按 / ／ | ｜ 拆分、清洗、去重（保持原顺序）。"""
    if not aka:
        return []
    parts = re.split(r'[/\uFF0F|\uFF5C]', str(aka))
    out, seen = [], set()
    for p in parts:
        c = clean_candidate(p)
        if not c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def rank_imdb_candidates(aka: str, foreign_title: str, chinese_name: str = ''):
    """
    生成候选并排序。排序主键 = 语种 tier（0 英文 → 1 混排 → 2 非中非英 → 3 中文），
    次键 = 来源顺序（又名#1..n → 主标题外文 → 中文名兜底）。
    返回 [(tier, pos, query, source_label), ...]
    """
    raw = []
    for i, p in enumerate(split_aka(aka)):
        raw.append((p, f'又名#{i + 1}'))

    ft = clean_candidate(foreign_title)
    if ft:
        raw.append((ft, '主标题外文'))

    cn = clean_candidate(chinese_name)
    if cn:
        raw.append((cn, '中文名(兜底)'))

    scored, seen_q = [], set()
    for pos, (text, src) in enumerate(raw):
        tier, query = classify_candidate(text)
        if tier == TIER_DROP or not query:
            continue
        key = query.lower()
        if key in seen_q:
            continue
        seen_q.add(key)
        scored.append((tier, pos, query, src))

    scored.sort(key=lambda x: (x[0], x[1]))
    return scored


def pick_imdb_search_query(aka: str, foreign_title: str, chinese_name: str = ''):
    """返回 (query, source_label, ranked)；找不到时 query 为 ''。"""
    ranked = rank_imdb_candidates(aka, foreign_title, chinese_name)
    if not ranked:
        return '', '', []
    tier, _pos, query, src = ranked[0]
    return query, f'{src} / tier{tier}', ranked


def print_candidates(ranked, limit=8):
    if not ranked:
        print("  （无可用检索词候选）")
        return
    tier_name = {0: '纯英文', 1: '含英文混排', 2: '非中非英', 3: '纯中文'}
    print("  检索词候选（tier 越小越优先）：")
    for tier, pos, query, src in ranked[:limit]:
        print(f"    · tier{tier}({tier_name.get(tier, '?')})  [{src}]  {query}")


def normalize_imdb_id(v) -> str:
    """把任意输入规范成 ttXXXXXXX，失败返回 ''。"""
    m = re.search(r'tt\d{6,}', str(v or ''), re.I)
    return m.group(0).lower() if m else ''


# ------------------ 在 json 里按名字找项目 ------------------
def find_item_by_name(data, name):
    target = str(name).strip()
    if not target:
        return None, None, None

    # 1) 精确匹配 name
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if isinstance(item, dict) and str(item.get('name', '')).strip() == target:
                return category, idx, item

    # 2) 回退：alias 里任一分段等于目标（大小写不敏感）
    low = target.lower()
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            for part in split_aka(str(item.get('alias', ''))):
                if part.lower() == low:
                    print(f"ℹ️ 通过 alias 匹配到项目（alias 分段：{part}）")
                    return category, idx, item
    return None, None, None


# ------------------ 写入判断工具 ------------------
def _content_len(v):
    """字符串按字符数、数组按元素个数计算「长度」。"""
    if isinstance(v, list):
        return len(v)
    if v is None:
        return 0
    return len(str(v).strip())


def _should_write(old, new):
    """
    写入规则：原字段为空，或新内容比原内容「更长」才写入。
    - 字符串：比字符数
    - 数组  ：比元素个数
    new 本身若为空则一律不写。
    """
    if isinstance(new, list):
        if not new:
            return False
    else:
        if not str(new).strip():
            return False

    if _content_len(old) == 0:
        return True

    return _content_len(new) > _content_len(old)


# ------------------ 写回逻辑 ------------------
def update_douban(item, scraped) -> bool:
    """写回日期 + 豆瓣评分 + imdb_id + 导演/编剧/主演/类型/alias/intro。"""
    date   = str(scraped.get('date', '')).strip()
    douban = str(scraped.get('douban_rating', '')).strip()
    changed = False

    print("  ┌────────────── 豆瓣写回 ──────────────")
    # 日期：只要以 YYYY-MM-DD 开头即视为有效日期（保留后续地区/平台备注）
    if re.match(r'^\d{4}-\d{2}-\d{2}', date):
        old_date = str(item.get('date', '')).strip()
        if old_date != date:
            item['date'] = date
            changed = True
            print(f"  │ 日期 date : {old_date or '空'} -> {date}")
        else:
            print(f"  │ 日期 date : {date}（无变化）")
    else:
        print(f"  │ 日期未抓到/格式不符，保持原样（抓到：{date or '空'}）")

    # 豆瓣评分
    if douban:
        rating = item.get('评分')
        if not isinstance(rating, dict):
            rating = {}
            item['评分'] = rating
        old = str(rating.get('豆瓣', '')).strip()
        rating['豆瓣'] = douban
        changed = True
        if old and old != douban:
            print(f"  │ 豆瓣评分 : {old} -> {douban}")
        else:
            print(f"  │ 豆瓣评分 : {douban}")
    else:
        print("  │ 豆瓣评分 : 页面未抓到，保持原样")

    # IMDb ID（新增，最有价值的字段）
    imdb_id = normalize_imdb_id(scraped.get('imdb_id', ''))
    if imdb_id:
        old_id = normalize_imdb_id(item.get('imdb_id', ''))
        if not old_id:
            item['imdb_id'] = imdb_id
            changed = True
            print(f"  │ imdb_id : 空 -> {imdb_id}")
        elif old_id != imdb_id:
            print(f"  │ imdb_id : ⚠️ 冲突（原 {old_id} / 豆瓣 {imdb_id}），保持原样")
        else:
            print(f"  │ imdb_id : {imdb_id}（无变化）")
    else:
        print("  │ imdb_id : 页面未提供")

    # ---- 以下字段：仅当原字段为空 或 新内容更长时才写入 ----

    # 导演（字符串，多个已在插件端用 " / " 连接）
    director = str(scraped.get('director', '')).strip()
    if _should_write(item.get('导演'), director):
        old = item.get('导演')
        item['导演'] = director
        changed = True
        print(f"  │ 导演    : {old or '空'} -> {director}")
    else:
        print(f"  │ 导演    : 不满足写入条件，保持原样（抓到：{director or '空'}）")

    # 编剧（数组）
    screenwriters = [str(x).strip() for x in (scraped.get('screenwriters') or []) if str(x).strip()]
    if _should_write(item.get('编剧'), screenwriters):
        item['编剧'] = screenwriters
        changed = True
        print(f"  │ 编剧    : {screenwriters}")
    else:
        print(f"  │ 编剧    : 不满足写入条件，保持原样（抓到：{screenwriters or '空'}）")

    # 主演（数组）
    starring = [str(x).strip() for x in (scraped.get('starring') or []) if str(x).strip()]
    if _should_write(item.get('主演'), starring):
        item['主演'] = starring
        changed = True
        print(f"  │ 主演    : {starring}")
    else:
        print(f"  │ 主演    : 不满足写入条件，保持原样（抓到：{starring or '空'}）")

    # 类型（数组）
    genres = [str(x).strip() for x in (scraped.get('genres') or []) if str(x).strip()]
    if _should_write(item.get('类型'), genres):
        item['类型'] = genres
        changed = True
        print(f"  │ 类型    : {genres}")
    else:
        print(f"  │ 类型    : 不满足写入条件，保持原样（抓到：{genres or '空'}）")

    # alias（优先又名整段；无又名则回退主标题外文）
    aka = str(scraped.get('aka', '')).strip()
    foreign_title = str(scraped.get('foreign_title', '')).strip()
    alias = aka if aka else foreign_title
    if _should_write(item.get('alias'), alias):
        old = item.get('alias')
        item['alias'] = alias
        changed = True
        source_label = "又名" if aka else "主标题外文"
        print(f"  │ alias ({source_label}) : {old or '空'} -> {alias}")
    else:
        print(f"  │ alias   : 不满足写入条件，保持原样（抓到：{alias or '空'}）")

    # 简介 (intro)
    intro = str(scraped.get('intro', '')).strip()
    if _should_write(item.get('intro'), intro):
        old_intro = str(item.get('intro', '') or '')
        item['intro'] = intro
        changed = True
        old_display = (old_intro[:15] + '...') if len(old_intro) > 15 else (old_intro or '空')
        new_display = (intro[:15] + '...') if len(intro) > 15 else intro
        print(f"  │ 简介    : {old_display} -> {new_display}")
    else:
        print(f"  │ 简介    : 不满足写入条件，保持原样（抓到长度：{len(intro)}）")

    print("  └──────────────────────────────────────")
    return changed


def update_imdb(item, scraped, expected_id='') -> bool:
    """写回 IMDb 评分到 评分.IMDB；带 ID 校验，防止写错片子。"""
    imdb = str(scraped.get('imdb_rating', '')).strip()
    got_id = normalize_imdb_id(scraped.get('imdb_id', '') or scraped.get('url', ''))
    exp_id = normalize_imdb_id(expected_id)

    print("  ┌────────────── IMDb写回 ──────────────")
    print(f"  │ 落地页    : {scraped.get('title', '') or '?'}  {got_id or ''}")

    if exp_id and got_id and exp_id != got_id:
        print(f"  │ ❌ ID 不匹配（期望 {exp_id} / 实际 {got_id}），拒绝写入")
        print("  └──────────────────────────────────────")
        return False

    if not imdb:
        print("  │ IMDb评分 : 页面未抓到，跳过写入")
        print("  └──────────────────────────────────────")
        return False

    rating = item.get('评分')
    if not isinstance(rating, dict):
        rating = {}
        item['评分'] = rating
    old = str(rating.get('IMDB', '')).strip()
    rating['IMDB'] = imdb
    if old and old != imdb:
        print(f"  │ IMDb评分 : {old} -> {imdb}")
    else:
        print(f"  │ IMDb评分 : {imdb}")

    # 顺手补 imdb_id
    if got_id and not normalize_imdb_id(item.get('imdb_id', '')):
        item['imdb_id'] = got_id
        print(f"  │ imdb_id : 空 -> {got_id}")

    print("  └──────────────────────────────────────")
    return True


# ------------------ Chrome 控制 ------------------
def _osa(script: str) -> str:
    proc = subprocess.run(["osascript", "-e", script],
                          capture_output=True, encoding="utf-8")
    return (proc.stdout or '').strip()


def _activate_and_switch(keyword, open_url, label):
    print(f"\n===== 激活Chrome并查找 {label} 标签 =====")
    script = f'''
    set foundTab to missing value
    set targetWin to missing value
    set targetTabIdx to 0

    tell application "Google Chrome"
        activate
        delay 0.3
        repeat with w in every window
            set tabCount to count of tabs of w
            repeat with tIdx from 1 to tabCount
                set t to tab tIdx of w
                set tabUrl to URL of t as string
                if tabUrl contains "{keyword}" and tabUrl is not "" then
                    set foundTab to t
                    set targetWin to w
                    set targetTabIdx to tIdx
                    exit repeat
                end if
            end repeat
            if foundTab is not missing value then exit repeat
        end repeat

        if foundTab is not missing value then
            set index of targetWin to 1
            set active tab index of targetWin to targetTabIdx
            delay 0.2
            return "FOUND"
        else
            tell application "System Events"
                keystroke "t" using command down
                delay 0.5
                keystroke "{open_url}"
                delay 0.5
                key code 36
            end tell
            return "NOT_FOUND_OPENED"
        end if
    end tell
    '''
    result = _osa(script)
    time.sleep(1.8)
    if result == "FOUND":
        print(f"✅ 成功切换到 {label} 标签页\n")
    elif result == "NOT_FOUND_OPENED":
        print(f"✅ 未找到 {label} 标签，已打开新页面：{open_url}\n")
    else:
        print(f"⚠️ {label} 操作完成，但返回状态异常：{result}\n")


def activate_chrome_and_switch_to_douban():
    _activate_and_switch("douban.com",
                         "https://movie.douban.com/subject/1837856/",
                         "豆瓣")


def activate_chrome_and_switch_to_imdb():
    _activate_and_switch("imdb.com", "https://www.imdb.com/", "IMDb")


def get_chrome_active_url() -> str:
    return _osa('tell application "Google Chrome" to return URL of '
                'active tab of window 1 as string')


def open_url_in_chrome(url: str, reuse_keyword: str) -> bool:
    """优先复用含 reuse_keyword 的已有标签页，把它导航到 url；否则新开标签。"""
    script = f'''
    set targetWin to missing value
    set targetIdx to 0
    tell application "Google Chrome"
        activate
        delay 0.3
        repeat with w in every window
            set tabCount to count of tabs of w
            repeat with i from 1 to tabCount
                set u to URL of tab i of w as string
                if u contains "{reuse_keyword}" and u is not "" then
                    set targetWin to w
                    set targetIdx to i
                    exit repeat
                end if
            end repeat
            if targetWin is not missing value then exit repeat
        end repeat

        if targetWin is not missing value then
            set index of targetWin to 1
            set active tab index of targetWin to targetIdx
            set URL of active tab of window 1 to "{url}"
            return "REUSED"
        else
            if (count of windows) is 0 then
                make new window
            end if
            set index of window 1 to 1
            tell window 1 to make new tab with properties {{URL:"{url}"}}
            return "NEWTAB"
        end if
    end tell
    '''
    res = _osa(script)
    if res in ("REUSED", "NEWTAB"):
        print(f"✅ Chrome 已导航（{res}）：{url}")
        return True
    print(f"❌ Chrome 导航失败，返回：{res}")
    return False


def wait_for_active_url_contains(needle: str, timeout: int) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        u = get_chrome_active_url()
        if needle.lower() in (u or '').lower():
            return True
        time.sleep(0.4)
    return False


# ------------------ 触发插件并取结果 ------------------
def trigger_plugin_and_get_json(download_glob, label):
    clear_old_downloads(download_glob)
    pyautogui.hotkey('option', 'n')
    print(f"已触发 Option+N（{label}），等待插件下载结果...")
    downloaded = wait_for_download(download_glob, WAIT_DOWNLOAD_TIMEOUT)
    if not downloaded:
        print(f"❌ {label} 下载超时，未获取到结果。")
        return None
    try:
        scraped = load_json(downloaded)
    except Exception as e:
        print(f"读取下载 json 失败: {e}")
        scraped = None
    move_to_trash(downloaded)
    return scraped


# ------------------ 搜索框流程（豆瓣/IMDb 共用） ------------------
def process_page(input_detector, popup_img_path, download_glob, paste_text, label):
    print(f"\n----- 开始处理 {label} 页面（搜索路线）-----")

    copy_to_clipboard(paste_text)

    location, shape = None, None
    start = time.time()
    print(f"等待 {label} 输入框图片，最长 {WAIT_POPUP_APPEAR} 秒...")
    while time.time() - start < WAIT_POPUP_APPEAR:
        _, location, shape = input_detector.find_images_on_screen(threshold=0.9)
        if location:
            print(f"✅ 找到 {label} 搜索框")
            break
        time.sleep(0.5)
    if not location:
        print(f"❌ 未找到 {label} 搜索框，跳过。")
        return None

    click_image_center(input_detector, location, shape, y_offset=0)
    time.sleep(0.5)

    pyautogui.hotkey('command', 'a')
    time.sleep(0.1)
    pyautogui.hotkey('command', 'v')
    time.sleep(WAIT_AFTER_PASTE)

    print(f"侦测 {label} 弹窗（联想结果）...")
    popup_detector = ScreenDetector(template_names=popup_img_path, clickValue='left')
    popup_found = False
    start = time.time()
    while time.time() - start < WAIT_POPUP_APPEAR:
        _, ploc, pshape = popup_detector.find_images_on_screen(threshold=0.9)
        if ploc:
            popup_found = True
            print(f"✅ 找到 {label} 弹窗")
            break
        time.sleep(0.3)
    if not popup_found:
        print(f"❌ 未找到 {label} 弹窗，跳过。")
        return None

    click_image_center(input_detector, location, shape, y_offset=SECOND_CLICK_Y_OFFSET)
    time.sleep(WAIT_PAGE_LOAD)

    return trigger_plugin_and_get_json(download_glob, label)


# ------------------ IMDb 直达流程（有 imdb_id 时最优） ------------------
def process_imdb_by_id(imdb_id):
    url = IMDB_TITLE_URL.format(imdb_id)
    print(f"\n----- IMDb 直达路线：{url} -----")
    if not open_url_in_chrome(url, 'imdb.com'):
        return None
    if wait_for_active_url_contains(imdb_id, WAIT_NAV_TIMEOUT):
        print("✅ 已到达目标 IMDb 页面")
    else:
        print("⚠️ 未确认 URL 已切换，仍按固定等待继续尝试")
    time.sleep(WAIT_PAGE_LOAD)
    return trigger_plugin_and_get_json(IMDB_DOWNLOAD_GLOB, 'IMDb')


# ------------------ 主流程 ------------------
def main():
    print("=== 豆瓣 + IMDb 一次性抓取启动 (v3) ===")

    # 1. 读取剪贴板（项目名）
    name = read_clipboard()
    if not name:
        print("❌ 剪贴板为空，无法继续。")
        return
    print(f"📋 剪贴板内容（项目名）: {name}")

    # 2. 在 json 里找到对应项目
    data = load_json(OVIDEOS_JSON)
    category, idx, item = find_item_by_name(data, name)
    if item is None:
        print(f"❌ 未在 OVideos.json 中找到名为「{name}」的项目，程序结束。")
        return
    print(f"✅ 已定位项目 [{category}][{idx}]")

    # ========== 第一阶段：豆瓣 ==========
    activate_chrome_and_switch_to_douban()
    douban_detector = ScreenDetector(template_names=DOUBAN_INPUT_IMG, clickValue='left')
    douban_scraped = process_page(
        douban_detector, DOUBAN_POPUP_IMG, DOUBAN_DOWNLOAD_GLOB,
        paste_text=name, label="豆瓣"
    )

    imdb_id = ''
    imdb_query, query_src, ranked = '', '', []

    if douban_scraped:
        aka           = str(douban_scraped.get('aka', '')).strip()
        foreign_title = str(douban_scraped.get('foreign_title', '')).strip()
        imdb_id       = normalize_imdb_id(douban_scraped.get('imdb_id', ''))

        print(f"🎬 又名 (aka)            : {aka or '（空）'}")
        print(f"🎬 主标题外文 (foreign)  : {foreign_title or '（空）'}")
        print(f"🆔 豆瓣页 IMDb ID        : {imdb_id or '（空）'}")

        imdb_query, query_src, ranked = pick_imdb_search_query(aka, foreign_title, name)
        print_candidates(ranked)

        if update_douban(item, douban_scraped):
            save_json(OVIDEOS_JSON, data)
            print("💾 豆瓣数据已写回 OVideos.json。")
        else:
            print("豆瓣无有效变化，未写回。")
    else:
        print("⚠️ 豆瓣抓取失败，尝试用 OVideos.json 中已有信息继续 IMDb 阶段。")
        imdb_id = normalize_imdb_id(item.get('imdb_id', ''))
        imdb_query, query_src, ranked = pick_imdb_search_query(
            str(item.get('alias', '')), '', name)
        print_candidates(ranked)

    # ========== 第二阶段：IMDb ==========
    imdb_scraped = None

    if imdb_id:
        imdb_scraped = process_imdb_by_id(imdb_id)
        if not imdb_scraped:
            print("⚠️ 直达路线失败，降级为搜索路线。")

    if imdb_scraped is None:
        if not imdb_query:
            print("\n❌ 既无 IMDb ID，也无有效检索词，无法继续，程序结束。")
            print("=== 结束 ===")
            return
        print(f"\n🔎 用检索词「{imdb_query}」（来源：{query_src}）搜索 IMDb")
        activate_chrome_and_switch_to_imdb()
        imdb_detector = ScreenDetector(template_names=IMDB_INPUT_IMG, clickValue='left')
        imdb_scraped = process_page(
            imdb_detector, IMDB_POPUP_IMG, IMDB_DOWNLOAD_GLOB,
            paste_text=imdb_query, label="IMDb"
        )

    if imdb_scraped:
        print(f"⭐ 抓到 IMDb 评分: {imdb_scraped.get('imdb_rating', '') or '（空）'}")
        if update_imdb(item, imdb_scraped, expected_id=imdb_id):
            save_json(OVIDEOS_JSON, data)
            print("💾 IMDb 数据已写回 OVideos.json。")
        else:
            print("IMDb 无有效变化，未写回。")
    else:
        print("⚠️ IMDb 抓取失败。")

    print("\n=== 全部完成，结束 ===")


if __name__ == '__main__':
    main()