#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣 + IMDb 一次性抓取与回写  (v5 - 联想稳定等待 + 搜索结果页兜底)

流程：
  剪贴板取名字 → 在 OVideos.json 找项目 →
  【豆瓣】
     ① JS 激活 #inp-query → 粘贴名字 → 等待 #search_suggest 联想「稳定」→
        按「名字匹配 + 年份(ACTIVE_YEARS)」挑选 → 命中则进入详情页
     ② 联想为空 / 无符合条目 → 输入框保留字串直接回车 → 搜索结果页
        (search.douban.com/movie/subject_search) → 解析 .item-root →
        按「名字 + 年份」挑选（可翻页）→ 进入详情页
     ③ 两者都无 → 整个程序停止（不进入 IMDb 阶段）
     进入详情页后 → 插件抓取 → 写回
  【IMDb】
     ┌ 豆瓣带 IMDb ID → 直达 https://www.imdb.com/title/ttXXXX/
     └ 否则 → JS 激活 #suggestion-search → 粘贴检索词 → 读取联想 DOM →
              按「名字匹配 + 年份(区间覆盖)」挑选 → 直达该 tt → 插件抓取
              （联想 DOM 无法解析时才降级为图片识别兜底）
  → 写回 → 结束

前置（一次性）：Chrome 菜单 显示 → 开发者 → 允许 Apple 事件中的 JavaScript
              未开启时自动降级为原来的图片识别流程。
依赖: pyautogui, 以及你已有的 screenshot.py
退出码: 0=完成  1=豆瓣阶段失败/致命错误(未进行 IMDb)  2=豆瓣完成但 IMDb 失败
"""

import os
import re
import sys
import time
import json
import glob
import unicodedata
import datetime
import argparse
import subprocess
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs

PYTHON_CODE_DIR = '/Users/yanzhang/Coding/python_code'
sys.path.insert(0, PYTHON_CODE_DIR)

import pyautogui
from screenshot import ScreenDetector

# ================= 配置区域 =================
OVIDEOS_JSON  = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
DOWNLOADS_DIR = Path.home() / 'Downloads'

# —— 只抓这些年份的条目（豆瓣联想/搜索页年份必须命中；IMDb 允许区间覆盖）——
TARGET_YEARS = ['2026']
ACTIVE_YEARS = list(TARGET_YEARS)   # 运行时会被 main() 覆盖
# —— 豆瓣年份容差：除目标年份外，也接受「目标年 + N」（0 = 关闭）——
DOUBAN_YEAR_TOLERANCE_NEXT = 1      # 2026 时也接受 2027；设 2 则接受 2027、2028

# —— 未来年份回退：JSON 年份晚于系统年份时（如 2027），主年份未命中则回退 ——
FUTURE_YEAR_FALLBACK_ENABLED = True
FUTURE_YEAR_FALLBACK_OFFSETS = [0]   # 0 = 系统当年；-1 = 系统年份减一；可改成 [0] 只用系统年
FALLBACK_LEVEL = 2                       # 回退年份的年份级别（数字越大优先级越低，主年份为 0/1）
FALLBACK_YEARS = []                      # 运行时由 main() 计算

# —— 日期规则：评分达标（或无评分）时，date 开头的日期改为系统当天 ——
DATE_RULE_ENABLED           = True     # 总开关；False = 完全沿用豆瓣日期
DATE_RULE_MIN_RATING        = 5.6      # 豆瓣/IMDb 最高分 ≥ 该值 → date 改为今天
DATE_RULE_NO_RATING_USE_TODAY = True   # 两边都没评分时是否也改为今天
DATE_TODAY_FORMAT           = '%Y-%m-%d'

# —— 日期规则适用的分类（JSON 里的顶层 key）——
DATE_RULE_CATEGORIES = {'Movie', 'Drama'}   # Show / Anime 不在此集合中 → 沿用豆瓣原始日期

# —— 站点首页（当前标签页没有搜索框时跳过去）——
DOUBAN_HOME = 'https://movie.douban.com/'
IMDB_HOME   = 'https://www.imdb.com/'

# —— 豆瓣标签页识别关键字（电影首页/详情页 + 电影搜索结果页）——
DOUBAN_TAB_KEYWORDS = ['movie.douban.com', 'search.douban.com/movie']
IMDB_TAB_KEYWORDS   = ['imdb.com']

# —— 豆瓣搜索结果页 ——
DOUBAN_SEARCH_URL       = 'https://search.douban.com/movie/subject_search?search_text={q}&cat=1002'
DOUBAN_SEARCH_PAGE_SIZE = 15     # 豆瓣搜索每页条数
DOUBAN_SEARCH_MAX_PAGES = 2      # 搜索结果最多翻几页（1 = 只看第一页）

# —— 输入框选择器（按优先级）——
DOUBAN_INPUT_SELECTORS = ['#inp-query', 'input[name="search_text"]']
IMDB_INPUT_SELECTORS = [
    '#suggestion-search',
    'input[aria-controls="react-autowhatever-navSuggestionSearch"]',
    'input.imdb-header-search__input',
    'form[role="search"] input[name="q"]',
]

# —— 图片兜底模板 ——（input 用相对文件名，走 ScreenDetector 默认目录；popup 用绝对路径）
DOUBAN_INPUT_IMG = 'douban_input.png'
DOUBAN_POPUP_IMG = '/Users/yanzhang/Coding/python_code/Resource/douban_popup.png'
IMDB_INPUT_IMG   = 'imdb_input.png'
IMDB_POPUP_IMG   = '/Users/yanzhang/Coding/python_code/Resource/imdb_popup.png'

DOUBAN_IMAGE_FALLBACK = True   # 仅在「Apple 事件 JS」不可用时启用
IMDB_IMAGE_FALLBACK   = True   # JS 不可用 或 IMDb 联想 DOM 无法解析时启用

IMDB_REQUIRE_YEAR    = True    # IMDb 联想是否也要求年份规则
IMDB_MAX_QUERY_TRIES = 3       # IMDb 最多尝试几个检索词候选

# —— 插件下载文件名模式 ——
DOUBAN_DOWNLOAD_GLOB = 'douban_result*.json'
IMDB_DOWNLOAD_GLOB   = 'imdb_result*.json'

# —— IMDb 直达 ——
IMDB_TITLE_URL = 'https://www.imdb.com/title/{}/'

# —— 等待时间（秒）——
POLL_INTERVAL           = 0.4
WAIT_AFTER_PASTE        = 2
WAIT_POPUP_APPEAR       = 20
WAIT_PAGE_LOAD          = 4    # JS 不可用时的固定等待
WAIT_PAGE_READY_TIMEOUT = 20   # JS 可用时：等待 URL+readyState 的上限
WAIT_PAGE_SETTLE        = 1.5  # 页面就绪后再额外稳一下
WAIT_SUGGEST_TIMEOUT    = 8    # IMDb 等待联想列表
WAIT_DOWNLOAD_TIMEOUT   = 30
WAIT_NAV_TIMEOUT        = 15
SECOND_CLICK_Y_OFFSET   = 50   # 图片兜底：第二次点击相对输入框中心的 Y 偏移

# —— 豆瓣联想（需求1：放慢判定，等列表稳定）——
DOUBAN_SUGGEST_TIMEOUT       = 12   # 联想等待上限
DOUBAN_SUGGEST_MIN_WAIT      = 2.0  # 输入后至少等这么久才下结论
DOUBAN_SUGGEST_STABLE_ROUNDS = 3    # 连续 N 次轮询内容不变才认为稳定（≈N×POLL_INTERVAL 秒）

# —— 豆瓣搜索结果页（需求2）——
DOUBAN_SUBMIT_NAV_TIMEOUT    = 8    # 回车后等待跳转到搜索页的上限
DOUBAN_SEARCH_RESULT_TIMEOUT = 15   # 等待搜索结果渲染的上限
DOUBAN_SEARCH_MIN_WAIT       = 1.5
DOUBAN_SEARCH_STABLE_ROUNDS  = 2
DOUBAN_SEARCH_EMPTY_ROUNDS   = 3    # 页面数据明确为空时，连续确认 N 次再判定「真没有」

# —— 抓取阶段（解决「已到详情页却不下载」）——
SCRAPE_PREFER_DIRECT_JS      = True    # JS 可用时优先在页面内直接抓取（不依赖快捷键/下载）；设 False 则只用插件
BACKGROUND_JS_PATH           = Path(__file__).resolve().parent / 'background.js'   # 抓取函数源码来源
SCRAPE_JS_ATTEMPTS           = 3       # 页面内直接抓取的最大尝试次数
CONTENT_READY_TIMEOUT        = {'douban': 25, 'imdb': 45}      # 等详情页内容渲染的上限（IMDb 更慢）
CONTENT_READY_FALLBACK_SLEEP = {'douban': 5,  'imdb': 10}      # JS 不可用时的固定等待
IMDB_NO_RATING_GRACE         = 6       # IMDb 有标题但迟迟没评分：readyState=complete 后再宽限几秒（可能本来就没评分）
HOTKEY_MAX_ATTEMPTS          = 4       # 快捷键兜底：最多按几次
WAIT_DOWNLOAD_PER_ATTEMPT    = 8       # 快捷键兜底：每次按键后最多等多久下载
HOTKEY_RETRY_PAUSE           = 1.5     # 重试间隔基数（第 n 次失败后等 n×该值）
HOTKEY_REREADY_TIMEOUT       = 10      # 每次重试前，重新确认页面就绪的上限

# —— 名字回退（完整名失败 → 去掉英文部分再试）——
NAME_FALLBACK_ENABLED = True                                   # 总开关
NAME_FALLBACK_LOG     = Path(__file__).resolve().parent / 'name_fallback.log'
NAME_FALLBACK_NOTIFY  = True                                   # macOS 通知中心弹窗提醒

pyautogui.FAILSAFE = True

EXIT_OK          = 0
EXIT_DOUBAN_FAIL = 1
EXIT_IMDB_FAIL   = 2


# ------------------ 基础工具 ------------------
# 匹配末尾的年份后缀：英雄2026 / 英雄 2026 / 英雄-2026 / 英雄(2026) / 英雄（2026）
RE_TRAILING_YEAR = re.compile(
    r'^(?P<name>.*?\S)[\s\-－—_·]*[\(（\[【]?\s*(?P<year>(?:19|20)\d{2})\s*[\)）\]】]?$'
)


def split_name_year(raw: str):
    """
    '英雄2026' -> ('英雄', '2026')
    '英雄'     -> ('英雄', '')
    '2012'     -> ('2012', '')   # 整个串只是年份时不拆
    """
    s = (raw or '').strip()
    m = RE_TRAILING_YEAR.match(s)
    if not m:
        return s, ''
    return m.group('name').strip(), m.group('year')


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    """原子写入：先写临时文件再替换，防止中途崩溃写坏原文件。"""
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_clipboard() -> str:
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
#                语种判定 / 检索词挑选
# ============================================================
RE_LATIN   = re.compile(r'[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]')
RE_HAN     = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]')
RE_KANA    = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\uFF66-\uFF9D]')
RE_HANGUL  = re.compile(r'[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]')
RE_OTHER   = re.compile(r'[\u0400-\u04FF\u0370-\u03FF\u0590-\u05FF'
                        r'\u0600-\u06FF\u0900-\u097F\u0E00-\u0E7F]')
RE_REGION_TAG = re.compile(r'[\(\uFF08\[\uFF3B\u3010][^\)\uFF09\]\uFF3D\u3011]{0,12}'
                           r'[\)\uFF09\]\uFF3D\u3011]')
RE_LATIN_RUN = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF0-9'\u2019\-\.\:\&, ]+")

_STRIP_CHARS = " \t\u3000-\u2013\u2014:\uFF1A,\uFF0C\u3001.\u00b7\"\u201c\u201d'\u2018\u2019"

TIER_PURE_LATIN  = 0
TIER_MIXED_LATIN = 1
TIER_NON_CN_EN   = 2
TIER_CHINESE     = 3
TIER_DROP        = 9


def clean_candidate(text: str) -> str:
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
    runs = [r.strip(_STRIP_CHARS).strip() for r in RE_LATIN_RUN.findall(t)]
    runs = [r for r in runs if RE_LATIN.search(r) and len(r) >= 2]
    return max(runs, key=len) if runs else ''


def is_chinese(text: str) -> bool:
    t = str(text or '')
    f = _script_flags(t)
    return f['han'] and not (f['kana'] or f['hangul'] or f['other'])


def is_english(text: str) -> bool:
    t = clean_candidate(text)
    if not t:
        return False
    f = _script_flags(t)
    non_latin = f['han'] or f['kana'] or f['hangul'] or f['other']
    if f['latin'] and not non_latin:
        return True
    return (not non_latin) and t.isascii() and any(c.isalnum() for c in t)


def classify_candidate(text: str):
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
    if t.isascii() and any(c.isalnum() for c in t):
        return TIER_PURE_LATIN, t
    return TIER_DROP, ''


def split_aka(aka: str):
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
    m = re.search(r'tt\d{6,}', str(v or ''), re.I)
    return m.group(0).lower() if m else ''


# ============================================================
#           联想结果匹配规则（名字 + 年份）
# ============================================================
_RE_ZERO_WIDTH = re.compile(r'[\u200b-\u200f\u2060\ufeff\u202a-\u202e]')


def norm_title(s) -> str:
    """NFKC 归一（全角→半角、全角冒号/空格统一）、去零宽/方向控制字符、合并空白、大小写不敏感。"""
    t = unicodedata.normalize('NFKC', str(s or ''))
    t = _RE_ZERO_WIDTH.sub('', t).replace('\u00a0', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    return t.casefold()


def _is_boundary(ch: str) -> bool:
    """名字后面紧跟的字符：只要不是字母/汉字/假名等『文字』，就算边界（空格、冒号、数字、各种符号）。"""
    return not ch.isalpha()


def title_match_level(candidate, query, allow_reverse=False):
    """
    0 = 完全一致
    1 = 候选以 query 开头，且后面紧跟边界字符（如「火线 第一季」「火线：xx」「火线2」）
    2 = （仅 allow_reverse）query 以候选开头 + 边界（如 query「The Wire Season 1」vs 标题「The Wire」）
    None = 不匹配
    """
    c, q = norm_title(candidate), norm_title(query)
    if not c or not q:
        return None
    if c == q:
        return 0
    if c.startswith(q) and _is_boundary(c[len(q)]):
        return 1
    if allow_reverse and q.startswith(c) and _is_boundary(q[len(c)]):
        return 2
    return None


RE_YEAR_RANGE = re.compile(r'((?:19|20)\d{2})(\s*[\u2013\u2014\-]\s*((?:19|20)\d{2})?)?')


def imdb_year_level(text, years):
    """0 = 起始年命中；1 = 区间覆盖目标年（剧集 2020– / 2017–2026）；None = 不符。"""
    m = RE_YEAR_RANGE.search(str(text or ''))
    if not m:
        return None
    start = int(m.group(1))
    if m.group(3):
        end = int(m.group(3))
    elif m.group(2):
        end = 9999          # 「2020–」仍在播
    else:
        end = start
    ys = {int(y) for y in years}
    if start in ys:
        return 0
    if any(start <= y <= end for y in ys):
        return 1
    return None


def resolve_primary_years(item, cli_years, year_hint):
    """主年份：命令行 --years > 项目名后缀年份 > JSON 的 date 开头年份 > TARGET_YEARS"""
    if cli_years:
        return list(cli_years)
    if year_hint:
        return [year_hint]
    m = re.match(r'\s*((?:19|20)\d{2})', str(item.get('date', '')))
    if m:
        return [m.group(1)]                  # "2027(未定)" -> ['2027']
    return list(TARGET_YEARS)


def build_fallback_years(primary_years):
    """主年份晚于系统年份时，生成回退年份列表，例如 2027 -> ['2026', '2025']"""
    if not FUTURE_YEAR_FALLBACK_ENABLED:
        return []
    sys_year = datetime.date.today().year
    nums = [int(y) for y in primary_years if str(y).strip().isdigit()]
    if not nums or max(nums) <= sys_year:
        return []                            # 主年份不是未来年份，不需要回退
    primary_set = {str(n) for n in nums}
    out = []
    for off in FUTURE_YEAR_FALLBACK_OFFSETS:
        y = str(sys_year + off)
        if y not in primary_set and y not in out:
            out.append(y)
    return out


def year_label(ylvl):
    if ylvl == 0:
        return '精确'
    if ylvl == FALLBACK_LEVEL:
        return '回退年份'
    return f'容差+{ylvl}'

def douban_year_levels(years, fallback=None):
    """
    返回 {年份字符串: 年份级别}
      0 = 主年份精确命中
      1 = 主年份 + N 的容差命中
      2 = 未来年份回退（系统年 / 系统年-1）
    """
    levels = {str(y).strip(): 0 for y in years if str(y).strip().isdigit()}
    for y in list(levels):
        for n in range(1, DOUBAN_YEAR_TOLERANCE_NEXT + 1):
            levels.setdefault(str(int(y) + n), 1)
    for y in (FALLBACK_YEARS if fallback is None else fallback):
        levels.setdefault(str(y), FALLBACK_LEVEL)
    return levels

def pick_douban_suggestion(items, name, years):
    ylevels = douban_year_levels(years)
    cands, name_only = [], []
    for it in items:
        lvl = title_match_level(it.get('title', ''), name)
        if lvl is None:
            for s in it.get('sub') or []:
                l2 = title_match_level(s, name)
                if l2 is not None:
                    lvl = 2 + l2          # 外文副标题命中，优先级低于中文主标题
                    break
        if lvl is None:
            continue

        year = str(it.get('year', '')).strip()
        if year in ylevels:
            cands.append((lvl, ylevels[year], it.get('idx', 0), it))
        else:
            name_only.append(it)

    print("  豆瓣联想列表：")
    for it in items:
        print(f"    #{it.get('idx')}  {it.get('title', '')}  [{it.get('year', '') or '?'}]  "
              f"{' | '.join(it.get('sub') or [])}")

    if not cands:
        if name_only:
            print(f"  ❌ 联想中名字匹配但年份不在 {sorted(ylevels)}："
                  + '；'.join(f"{x.get('title')}({x.get('year') or '?'})" for x in name_only))
        else:
            print(f"  ❌ 联想中没有名字与「{name}」匹配的条目")
        return None

    cands.sort(key=lambda x: (x[1] >= FALLBACK_LEVEL, x[0], x[1], x[2]))   # 主年份候选永远排在回退年份之前
    best_lvl, best_ylvl, _, best = cands[0]
    ylabel = year_label(best_ylvl)
    print(f"  ✅ 选中：#{best.get('idx')} {best.get('title')} ({best.get('year')})  "
          f"名字级别={best_lvl}  年份={ylabel}  {best.get('link')}")
    return best


# —— 豆瓣搜索结果页：标题解析与匹配 ——
RE_SEARCH_TITLE_YEAR = re.compile(r'[\(（]\s*((?:19|20)\d{2})\s*[\)）]\s*$')
RE_LATIN_START = re.compile(r'[a-z\u00c0-\u024f]')


def parse_search_title(raw: str):
    """'暗流 \u200e (2026)' -> ('暗流', '2026')；'肖申克的救赎 The Shawshank Redemption (1994)' -> (..., '1994')"""
    t = unicodedata.normalize('NFKC', str(raw or ''))
    t = _RE_ZERO_WIDTH.sub('', t).replace('\u00a0', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    m = RE_SEARCH_TITLE_YEAR.search(t)
    if not m:
        return t, ''
    return t[:m.start()].strip(), m.group(1)


def douban_search_match_level(title, name):
    """
    搜索结果页标题形如「中文名 外文原名」：
      0 = 完全一致，或「name + 空格 + 拉丁字母开头的外文原名（不含汉字）」
      1 = 以 name 开头 + 边界（如「暗流 第二季」「暗流2」）
      None = 不匹配（如「暗流涌动」）
    """
    lvl = title_match_level(title, name)
    if lvl == 1:
        t, q = norm_title(title), norm_title(name)
        rest = t[len(q):].strip()
        if rest and RE_LATIN_START.match(rest) and not RE_HAN.search(rest):
            lvl = 0
    return lvl


def pick_douban_search_result(items, name, years, page=0):
    ylevels = douban_year_levels(years)
    cands, name_only = [], []
    print(f"  豆瓣搜索结果（第 {page + 1} 页）：")
    for it in items:
        title, year = parse_search_title(it.get('raw_title', ''))
        it['title'], it['year'] = title, year
        subs = [s.strip() for s in re.split(r'[/／]', it.get('abstract', '') or '') if s.strip()]
        print(f"    #{it.get('idx')}  {title}  [{year or '?'}]  {it.get('abstract', '')}  "
              f"({it.get('src')})")

        lvl = douban_search_match_level(title, name)
        if lvl is None:
            for s in subs:
                l2 = title_match_level(s, name)
                if l2 is not None:
                    lvl = 2 + l2
                    break
        if lvl is None:
            continue

        if year in ylevels:
            cands.append((lvl, ylevels[year], it.get('idx', 0), it))
        else:
            name_only.append(it)

    if not cands:
        if name_only:
            print(f"  ❌ 搜索页名字匹配但年份不在 {sorted(ylevels)}："
                  + '；'.join(f"{x['title']}({x['year'] or '?'})" for x in name_only))
        else:
            print(f"  ❌ 搜索页没有名字与「{name}」匹配的条目")
        return None

    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    best_lvl, best_ylvl = cands[0][0], cands[0][1]
    best = cands[0][3]
    same = [c for c in cands if c[0] == best_lvl and c[1] == best_ylvl]
    if len(same) > 1:
        print(f"  ⚠️ 有 {len(same)} 个同级候选，按豆瓣排序取第一个："
              + '；'.join(f"{c[3]['title']}({c[3]['year']})" for c in same))
    ylabel = year_label(best_ylvl)
    print(f"  ✅ 选中：#{best.get('idx')} {best['title']} ({best['year']})  "
          f"名字级别={best_lvl}  年份={ylabel}  {best.get('link')}")
    return best


def pick_imdb_suggestion(items, query, years):
    cands, name_only = [], []
    print("  IMDb 联想列表：")
    for it in items:
        print(f"    #{it.get('idx')}  [{it.get('kind')}] {it.get('title', '')}  "
              f"{it.get('year_text', '')}  {it.get('id', '')}")
        if it.get('kind') != 'title' or not it.get('id'):
            continue
        lvl = title_match_level(it.get('title', ''), query, allow_reverse=True)
        if lvl is None:
            continue
        ylvl = 0
        if IMDB_REQUIRE_YEAR:
            ylvl = imdb_year_level(it.get('year_text', ''), years)
            if ylvl is None and FALLBACK_YEARS:
                if imdb_year_level(it.get('year_text', ''), FALLBACK_YEARS) is not None:
                    ylvl = FALLBACK_LEVEL
        if ylvl is None:
            name_only.append(it)
            continue
        cands.append((lvl, ylvl, it.get('idx', 0), it))

    if not cands:
        if name_only:
            print("  ❌ 名字匹配但年份不符：" + '；'.join(
                f"{x.get('title')}({x.get('year_text') or '?'})" for x in name_only))
        else:
            print(f"  ❌ 联想中没有与「{query}」匹配的条目")
        return None

    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    best = cands[0][3]
    print(f"  ✅ 选中：#{best.get('idx')} {best.get('title')} ({best.get('year_text')})  "
          f"{best.get('id')}  名字级别={cands[0][0]} 年份级别={cands[0][1]}")
    return best


# ------------------ 在 json 里按名字找项目 ------------------
def find_item_by_name(data, name):
    target = str(name).strip()
    if not target:
        return None, None, None

    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if isinstance(item, dict) and str(item.get('name', '')).strip() == target:
                return category, idx, item

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
    if isinstance(v, list):
        return len(v)
    if v is None:
        return 0
    return len(str(v).strip())


def insert_key_after(d: dict, after_key: str, new_key: str, new_value):
    new_items = []
    found_after = False
    for k, v in d.items():
        if k == new_key:
            continue
        new_items.append((k, v))
        if k == after_key:
            new_items.append((new_key, new_value))
            found_after = True
    if not found_after:
        new_items.append((new_key, new_value))
    d.clear()
    d.update(new_items)


def _should_write(old, new):
    if isinstance(new, list):
        if not new:
            return False
    else:
        if not str(new).strip():
            return False
    if _content_len(old) == 0:
        return True
    return _content_len(new) > _content_len(old)


RE_DOUBAN_DATE = re.compile(r'^\d{4}(?:-\d{2}){0,2}')


def is_valid_douban_date(s: str) -> bool:
    return bool(RE_DOUBAN_DATE.match(str(s or '').strip()))


# ------------------ 写回逻辑 ------------------
def update_douban(item, scraped) -> bool:
    date   = str(scraped.get('date', '')).strip()
    douban = str(scraped.get('douban_rating', '')).strip()
    changed = False

    print("  ┌────────────── 豆瓣写回 ──────────────")
    if is_valid_douban_date(date):
        old_date = str(item.get('date', '')).strip()
        if old_date != date:
            item['date'] = date
            insert_key_after(item, after_key='date', new_key='date_re', new_value=date)
            changed = True
            print(f"  │ 日期 date    : {old_date or '空'} -> {date}")
            print(f"  │ 同步 date_re : {date}")
        else:
            print(f"  │ 日期 date : {date}（无变化）")
        # 新增：date 没变化但 date_re 仍是旧值/待定值时，也同步为豆瓣的具体日期
        # （仅当豆瓣日期含月份，避免用 "2026" 这种年份降级已有的具体日期）
        if re.search(r'\d{4}-\d{2}', date):
            old_re = str(item.get('date_re', '')).strip()
            if old_re != date:
                insert_key_after(item, after_key='date', new_key='date_re', new_value=date)
                changed = True
                print(f"  │ 同步 date_re : {old_re or '空'} -> {date}")
    else:
        print(f"  │ 日期未抓到/格式不符，保持原样（抓到：{date or '空'}）")

    if douban:
        rating = item.get('评分')
        if not isinstance(rating, dict):
            rating = {}
            item['评分'] = rating
        old = str(rating.get('豆瓣', '')).strip()
        if old != douban:
            rating['豆瓣'] = douban
            changed = True
            print(f"  │ 豆瓣评分 : {old or '空'} -> {douban}")
        else:
            print(f"  │ 豆瓣评分 : {douban}（无变化）")
    else:
        print("  │ 豆瓣评分 : 页面未抓到，保持原样")

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

    director = str(scraped.get('director', '')).strip()
    if _should_write(item.get('导演'), director):
        old = item.get('导演')
        item['导演'] = director
        changed = True
        print(f"  │ 导演    : {old or '空'} -> {director}")
    else:
        print(f"  │ 导演    : 不满足写入条件，保持原样（抓到：{director or '空'}）")

    screenwriters = [str(x).strip() for x in (scraped.get('screenwriters') or []) if str(x).strip()]
    if _should_write(item.get('编剧'), screenwriters):
        item['编剧'] = screenwriters
        changed = True
        print(f"  │ 编剧    : {screenwriters}")
    else:
        print(f"  │ 编剧    : 不满足写入条件，保持原样（抓到：{screenwriters or '空'}）")

    starring = [str(x).strip() for x in (scraped.get('starring') or []) if str(x).strip()]
    if _should_write(item.get('主演'), starring):
        item['主演'] = starring
        changed = True
        print(f"  │ 主演    : {starring}")
    else:
        print(f"  │ 主演    : 不满足写入条件，保持原样（抓到：{starring or '空'}）")

    genres = [str(x).strip() for x in (scraped.get('genres') or []) if str(x).strip()]
    if _should_write(item.get('类型'), genres):
        item['类型'] = genres
        changed = True
        print(f"  │ 类型    : {genres}")
    else:
        print(f"  │ 类型    : 不满足写入条件，保持原样（抓到：{genres or '空'}）")

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
    """写回 IMDb 评分；必须是 /title/tt 条目页，且与期望 ID 一致。"""
    imdb = str(scraped.get('imdb_rating', '')).strip()
    got_id = normalize_imdb_id(scraped.get('imdb_id', '') or scraped.get('url', ''))
    exp_id = normalize_imdb_id(expected_id)

    print("  ┌────────────── IMDb写回 ──────────────")
    print(f"  │ 落地页    : {scraped.get('title', '') or '?'}  {got_id or ''}")

    if not got_id:
        print("  │ ❌ 落地页不是 IMDb 条目页（无 tt 编号），拒绝写入")
        print("  └──────────────────────────────────────")
        return False

    if exp_id and exp_id != got_id:
        print(f"  │ ❌ ID 不匹配（期望 {exp_id} / 实际 {got_id}），拒绝写入")
        print("  └──────────────────────────────────────")
        return False

    if not imdb:
        print("  │ IMDb评分 : 页面未抓到，跳过写入")
        print("  └──────────────────────────────────────")
        return False

    changed = False
    rating = item.get('评分')
    if not isinstance(rating, dict):
        rating = {}
        item['评分'] = rating
    old = str(rating.get('IMDB', '')).strip()
    if old != imdb:
        rating['IMDB'] = imdb
        changed = True
        print(f"  │ IMDb评分 : {old or '空'} -> {imdb}")
    else:
        print(f"  │ IMDb评分 : {imdb}（无变化）")

    if not normalize_imdb_id(item.get('imdb_id', '')):
        item['imdb_id'] = got_id
        changed = True
        print(f"  │ imdb_id : 空 -> {got_id}")

    print("  └──────────────────────────────────────")
    return changed

# ------------------ 日期规则（评分达标 → date 改为系统当天） ------------------
RE_RATING_NUM  = re.compile(r'\d+(?:\.\d+)?')
RE_DATE_PREFIX = re.compile(r'^\d{4}(?:-\d{1,2}){0,2}')   # 开头的 YYYY / YYYY-MM / YYYY-MM-DD


def parse_rating(v):
    """'7.3' -> 7.3；'' / '暂无评分' / '0' / 超出 0~10 -> None"""
    m = RE_RATING_NUM.search(str(v or ''))
    if not m:
        return None
    try:
        x = float(m.group(0))
    except ValueError:
        return None
    return x if 0 < x <= 10 else None


def replace_date_prefix(date_str, new_date):
    """只替换最前面的日期部分，后缀（地区/时间等）原样保留。
       '2026-10-22(英国)' -> '2026-10-26(英国)'；'2026-10-22 20:00(中国大陆)' -> '2026-10-26 20:00(中国大陆)'"""
    s = str(date_str or '').strip()
    m = RE_DATE_PREFIX.match(s)
    if not m:
        return s
    return new_date + s[m.end():]


def apply_date_rule(item, douban_scraped, imdb_scraped=None, expected_imdb_id='', category='') -> bool:
    """
    在豆瓣、IMDb 两阶段都结束后调用，只修改 item['date']（不碰 date_re）。
      · 最高分 ≥ DATE_RULE_MIN_RATING → 开头日期改为系统当天
      · 两边都没评分且 DATE_RULE_NO_RATING_USE_TODAY → 同上
      · 最高分 < 阈值 → 使用豆瓣原始日期
    基准始终是「本次从豆瓣抓到的原始日期」，因此重复运行结果稳定。
    返回 item['date'] 是否发生变化。
    """
    if not DATE_RULE_ENABLED:
        return False

    # ★ 分类门控：不在 DATE_RULE_CATEGORIES 内的分类（Show / Anime）不应用规则
    if category not in DATE_RULE_CATEGORIES:
        raw_date = str(douban_scraped.get('date', '')).strip()
        old = str(item.get('date', '')).strip()
        print("  ┌────────────── 日期规则 ──────────────")
        print(f"  │ 分类 [{category}] 不在日期规则适用范围内，沿用豆瓣原始日期")
        if is_valid_douban_date(raw_date) and old != raw_date:
            item['date'] = raw_date      # 同时纠正之前可能被写成“今天”的旧值
            print(f"  │ date : {old or '空'} -> {raw_date}")
            print("  └──────────────────────────────────────")
            return True
        print(f"  │ date : {old or '空'}（无变化）")
        print("  └──────────────────────────────────────")
        return False

    print("  ┌────────────── 日期规则 ──────────────")
    base = str(douban_scraped.get('date', '')).strip()
    if not is_valid_douban_date(base):
        print(f"  │ 未抓到有效的豆瓣日期（{base or '空'}），跳过日期规则")
        print("  └──────────────────────────────────────")
        return False

    d_rating = parse_rating(douban_scraped.get('douban_rating'))

    # IMDb 评分只在「落地页是条目页且 ID 与期望一致」时才算数（与 update_imdb 的校验一致）
    i_rating = None
    if imdb_scraped:
        got_id = normalize_imdb_id(imdb_scraped.get('imdb_id', '') or imdb_scraped.get('url', ''))
        exp_id = normalize_imdb_id(expected_imdb_id)
        if got_id and (not exp_id or exp_id == got_id):
            i_rating = parse_rating(imdb_scraped.get('imdb_rating'))
        else:
            print("  │ IMDb 结果无效（非条目页或 ID 不匹配），不参与评分判断")

    print(f"  │ 豆瓣评分: {d_rating if d_rating is not None else '无'}   "
          f"IMDb评分: {i_rating if i_rating is not None else '无'}   "
          f"阈值: {DATE_RULE_MIN_RATING}")

    rated = [r for r in (d_rating, i_rating) if r is not None]
    if rated:
        top = max(rated)
        use_today = top + 1e-9 >= float(DATE_RULE_MIN_RATING)
        reason = (f"最高分 {top} ≥ {DATE_RULE_MIN_RATING}，date 改为今天" if use_today
                  else f"最高分 {top} < {DATE_RULE_MIN_RATING}，保持豆瓣原始日期")
    else:
        use_today = bool(DATE_RULE_NO_RATING_USE_TODAY)
        reason = "豆瓣与 IMDb 均无评分，" + ("date 改为今天" if use_today else "保持豆瓣原始日期")
    print(f"  │ {reason}")

    today = datetime.date.today().strftime(DATE_TODAY_FORMAT)
    target = replace_date_prefix(base, today) if use_today else base

    old = str(item.get('date', '')).strip()
    if old == target:
        print(f"  │ date : {target}（无变化）")
        print("  └──────────────────────────────────────")
        return False

    item['date'] = target          # 只改 date；date_re 保持豆瓣原始值
    print(f"  │ date : {old or '空'} -> {target}   （date_re 不动）")
    print("  └──────────────────────────────────────")
    return True


def finalize_date(data, item, douban_scraped, imdb_scraped=None, expected_imdb_id='', category=''):
    """应用日期规则；有变化才再保存一次。"""
    if apply_date_rule(item, douban_scraped, imdb_scraped, expected_imdb_id, category):
        save_json(OVIDEOS_JSON, data)
        print("💾 日期规则调整已写回 OVideos.json。")


# ============================================================
#                    Chrome 控制（AppleScript）
# ============================================================
def _osa(script: str) -> str:
    proc = subprocess.run(["osascript", "-e", script],
                          capture_output=True, encoding="utf-8")
    return (proc.stdout or '').strip()


def _osa_argv(lines, args, timeout=20):
    """以 argv 方式传参执行 AppleScript，避免字符串转义问题。返回 (rc, stdout, stderr)。"""
    cmd = ['osascript']
    for ln in lines:
        cmd += ['-e', ln]
    cmd += [str(a) for a in args]
    try:
        p = subprocess.run(cmd, capture_output=True, encoding='utf-8', timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, '', 'timeout'
    return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()


def bring_chrome_front():
    """发送快捷键前确保 Chrome 在最前台，避免按键打到别的 App。"""
    _osa('tell application "Google Chrome" to activate')
    time.sleep(0.2)


class ChromeJSUnavailable(Exception):
    pass


_JS_OK = None   # None=未探测/暂未确定 / True / False(明确不可用)


def chrome_exec_js(js: str, timeout=20):
    rc, out, err = _osa_argv([
        'on run argv',
        'tell application "Google Chrome"',
        'set r to execute active tab of window 1 javascript (item 1 of argv)',
        'end tell',
        'return r',
        'end run',
    ], [js], timeout)
    if rc == 0:
        return out
    if 'JavaScript' in err and 'Apple' in err:
        raise ChromeJSUnavailable(err)
    return None


def js_available() -> bool:
    """只有「明确未开启 Apple 事件 JS」才永久降级；临时失败（页面加载中等）下次会重新探测。"""
    global _JS_OK
    if _JS_OK is not None:
        return _JS_OK
    for _ in range(3):
        try:
            out = chrome_exec_js("'pong'", timeout=10)
        except ChromeJSUnavailable:
            print("⚠️ Chrome 未开启「允许 Apple 事件中的 JavaScript」。")
            print("   开启方法：Chrome 菜单栏 → 显示 → 开发者 → 允许 Apple 事件中的 JavaScript")
            print("   本次降级为图片识别流程。")
            _JS_OK = False
            return False
        if out == 'pong':
            print("✅ Chrome 页面 JS 通道可用（DOM 精准定位模式）")
            _JS_OK = True
            return True
        time.sleep(0.6)
    print("⚠️ 当前标签暂时无法执行 JS（可能是 chrome:// 页面或正在加载），本次按不可用处理。")
    return False


JS_PRELUDE = r'''
function vis(el){
  if(!el) return false;
  var r = el.getBoundingClientRect();
  var cs = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
}
function findInput(sels){
  var first = null;
  for (var i = 0; i < (sels || []).length; i++){
    var list = document.querySelectorAll(sels[i]);
    for (var j = 0; j < list.length; j++){
      if (!first) first = list[j];
      if (vis(list[j])) return list[j];
    }
  }
  return first;
}
'''


def run_page_js(body: str, params=None, timeout=20):
    """在当前活动标签执行 JS 片段（body 内用 return 返回对象），返回解析后的 Python 对象。"""
    global _JS_OK
    js = ("(function(){var P=" + json.dumps(params or {}) + ";" + JS_PRELUDE +
          "try{var __r=(function(){\n" + body + "\n})();"
          "return JSON.stringify(__r===undefined?null:__r);}"
          "catch(e){return JSON.stringify({__error:String((e&&e.message)||e)});}})();")
    try:
        out = chrome_exec_js(js, timeout)
    except ChromeJSUnavailable:
        _JS_OK = False
        return None
    if not out or out == 'missing value':
        return None
    try:
        res = json.loads(out)
    except Exception:
        return None
    if isinstance(res, dict) and '__error' in res:
        print(f"  [JS 错误] {res['__error']}")
        return None
    return res


JS_READY_STATE = r'''return {rs: document.readyState, href: location.href};'''

JS_FOCUS_INPUT = r'''
var el = findInput(P.selectors);
if (!el) return {ok:false, reason:'no_input'};
var toggled = false;
if (!vis(el) && P.openImdbSearch){
  var cb = document.querySelector('input[type="checkbox"][id*="searchstate" i]');
  if (cb && !cb.checked){
    cb.checked = true;
    cb.dispatchEvent(new Event('change', {bubbles:true}));
    toggled = true;
  }
  el = findInput(P.selectors);
}
try { el.scrollIntoView({block:'nearest'}); } catch(e) {}
el.focus();
try { el.select(); } catch(e) {}
return {ok:true, visible:vis(el), focused:(document.activeElement === el),
        hasFocus:document.hasFocus(), value:el.value || '', toggled:toggled};
'''

JS_GET_VALUE = r'''
var el = findInput(P.selectors);
return {ok:!!el, value: el ? (el.value || '') : ''};
'''

JS_SET_VALUE = r'''
var el = findInput(P.selectors);
if (!el) return {ok:false};
el.focus();
var desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
desc.set.call(el, P.text);
el.dispatchEvent(new Event('input', {bubbles:true}));
el.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, key:'Unidentified'}));
el.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, key:'Unidentified'}));
el.dispatchEvent(new Event('change', {bubbles:true}));
return {ok:true, value:el.value};
'''

JS_SUBMIT_FORM = r'''
var el = findInput(P.selectors);
if (!el) return {ok:false, reason:'no_input'};
var f = el.form;
if (!f) return {ok:false, reason:'no_form'};
if (f.requestSubmit) f.requestSubmit(); else f.submit();
return {ok:true};
'''

JS_DOUBAN_SUGGEST = r'''
var inp = findInput(P.selectors);
var box = document.getElementById('search_suggest');
if (!box) return {ready:false, reason:'no_box', value: inp ? inp.value : ''};
var lis = box.querySelectorAll('li');
var out = [];
for (var i = 0; i < lis.length; i++){
  var li = lis[i];
  var a = li.querySelector('a[href]');
  var link = li.getAttribute('data-link') || (a ? a.getAttribute('href') : '') || '';
  try { link = new URL(link, location.href).href; } catch(e) {}
  var em = li.querySelector('em');
  var title = em ? (em.textContent || '').replace(/\s+/g, ' ').trim() : '';
  var spans = Array.prototype.map.call(li.querySelectorAll('p span'), function(s){
    return (s.textContent || '').replace(/\s+/g, ' ').trim();
  }).filter(Boolean);
  var year = '';
  for (var k = 0; k < spans.length; k++){
    if (/^(19|20)\d{2}$/.test(spans[k])) { year = spans[k]; break; }
  }
  var sugg = '';
  try { sugg = new URL(link).searchParams.get('suggest') || ''; } catch(e) {}
  out.push({idx:i, title:title, year:year,
            sub:spans.filter(function(s){ return s !== year; }),
            link:link, suggest:sugg});
}
return {ready:true, shown:vis(box), value: inp ? inp.value : '', items:out};
'''

# 豆瓣搜索结果页：优先读 DOM（.item-root / a.title-text），DOM 为空时用 window.__DATA__ 兜底
JS_DOUBAN_SEARCH_RESULTS = r'''
function clean(s){
  return String(s || '').replace(/[\u200b-\u200f\u2060\ufeff\u202a-\u202e]/g, '')
                        .replace(/\s+/g, ' ').trim();
}
var out = [], seen = {};
var roots = document.querySelectorAll('.item-root');
for (var i = 0; i < roots.length; i++){
  var root = roots[i];
  var a = root.querySelector('a.title-text') || root.querySelector('.title a[href]');
  if (!a) continue;
  var href = a.href || a.getAttribute('href') || '';
  var mt = href.match(/movie\.douban\.com\/subject\/(\d+)/);
  if (!mt || seen[mt[1]]) continue;
  seen[mt[1]] = 1;
  var ab  = root.querySelector('.meta.abstract');
  var ab2 = root.querySelector('.meta.abstract_2');
  out.push({idx: out.length, sid: mt[1],
            link: 'https://movie.douban.com/subject/' + mt[1] + '/',
            raw_title: clean(a.textContent),
            abstract: ab ? clean(ab.textContent) : '',
            abstract_2: ab2 ? clean(ab2.textContent) : '',
            src: 'dom'});
}
var D = null;
try { D = window.__DATA__; } catch(e) { D = null; }
var dItems = null, total = null;
if (D && typeof D === 'object'){
  dItems = [];
  if (typeof D.total === 'number') total = D.total;
  (D.items || []).forEach(function(x){
    var u = String((x && x.url) || '');
    var m = u.match(/movie\.douban\.com\/subject\/(\d+)/);
    if (!m) return;
    dItems.push({sid: m[1], link: 'https://movie.douban.com/subject/' + m[1] + '/',
                 raw_title: clean(x.title), abstract: clean(x.abstract),
                 abstract_2: clean(x.abstract_2), src: 'data'});
  });
}
if (!out.length && dItems && dItems.length){
  out = dItems.map(function(x, k){ x.idx = k; return x; });
}
return {href: location.href, rs: document.readyState, items: out,
        dom_roots: roots.length, has_data: !!D,
        data_count: dItems ? dItems.length : null, total: total};
'''

JS_IMDB_SUGGEST = r'''
var inp = findInput(P.selectors);
var lb = document.getElementById('react-autowhatever-navSuggestionSearch');
if (!lb && inp){
  var own = inp.getAttribute('aria-controls') || '';
  if (own) lb = document.getElementById(own);
}
if (!lb) lb = document.querySelector('[id^="react-autowhatever"][role="listbox"]');
if (!lb) return {ready:false, reason:'no_listbox', value: inp ? inp.value : ''};
var lis = lb.querySelectorAll('li');
var out = [];
for (var i = 0; i < lis.length; i++){
  var li = lis[i];
  var a = li.querySelector('a[href]');
  var href = a ? (a.getAttribute('href') || '') : '';
  var lines = (li.innerText || li.textContent || '').split('\n')
                .map(function(s){ return s.trim(); }).filter(Boolean);
  var mt = href.match(/\/title\/(tt\d{6,})/i);
  if (!mt){
    out.push({idx:i, kind: /\/name\/nm\d+/i.test(href) ? 'name' : 'other',
              title: lines[0] || '', href: href});
    continue;
  }
  var tEl = li.querySelector('[class*="constTitle"]');
  var sEls = li.querySelectorAll('[class*="constSubtitle"]');
  var title = tEl ? (tEl.textContent || '').trim() : (lines[0] || '');
  var sub = sEls.length
      ? Array.prototype.map.call(sEls, function(e){ return (e.textContent || '').trim(); })
      : lines.slice(1);
  var yt = '';
  for (var k = 0; k < sub.length; k++){
    if (/(19|20)\d{2}/.test(sub[k])) { yt = sub[k]; break; }
  }
  out.push({idx:i, kind:'title', id:mt[1].toLowerCase(), title:title,
            year_text:yt, sub:sub.slice(0, 3), href:href});
}
return {ready:true, value: inp ? inp.value : '', items:out};
'''


def get_chrome_active_url() -> str:
    return _osa('tell application "Google Chrome" to return URL of '
                'active tab of window 1 as string')


def navigate_active_tab(url: str) -> bool:
    rc, _out, err = _osa_argv([
        'on run argv',
        'tell application "Google Chrome" to set URL of active tab of window 1 to (item 1 of argv)',
        'end run',
    ], [url], 15)
    if rc != 0:
        print(f"❌ 导航失败：{err}")
        return False
    print(f"➡️  跳转：{url}")
    return True


def wait_for_active_url_contains(needle: str, timeout: int) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        u = get_chrome_active_url()
        if needle.lower() in (u or '').lower():
            return True
        time.sleep(POLL_INTERVAL)
    return False


def wait_page_ready(url_needle='', timeout=WAIT_PAGE_READY_TIMEOUT) -> bool:
    """先等 URL 切换，再等文档 readyState（文档自身的 href 也要包含 needle，防止读到旧页面）。"""
    start = time.time()
    if url_needle and not wait_for_active_url_contains(url_needle, timeout):
        print(f"⚠️ 未确认 URL 包含 {url_needle}")
    if not js_available():
        time.sleep(WAIT_PAGE_LOAD)
        return True
    needle = url_needle.lower()
    while time.time() - start < timeout:
        r = run_page_js(JS_READY_STATE)
        if isinstance(r, dict) and r.get('rs') in ('interactive', 'complete') \
                and (not needle or needle in str(r.get('href', '')).lower()):
            time.sleep(WAIT_PAGE_SETTLE)
            return True
        time.sleep(POLL_INTERVAL)
    print("⚠️ 等待页面就绪超时，继续尝试")
    time.sleep(WAIT_PAGE_SETTLE)
    return False


def _activate_and_switch(keywords, open_url, label):
    print(f"\n===== 激活Chrome并查找 {label} 标签 =====")
    cond = ' or '.join(f'(tabUrl contains "{k}")' for k in keywords)
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
                if ({cond}) and tabUrl is not "" then
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
            if (count of windows) is 0 then make new window
            set index of window 1 to 1
            tell window 1 to make new tab with properties {{URL:"{open_url}"}}
            return "NOT_FOUND_OPENED"
        end if
    end tell
    '''
    result = _osa(script)
    time.sleep(0.8)
    if result == "FOUND":
        print(f"✅ 成功切换到 {label} 标签页\n")
    elif result == "NOT_FOUND_OPENED":
        print(f"✅ 未找到 {label} 标签，已打开新页面：{open_url}\n")
        wait_page_ready(keywords[0])
    else:
        print(f"⚠️ {label} 操作完成，但返回状态异常：{result}\n")


def activate_chrome_and_switch_to_douban():
    _activate_and_switch(DOUBAN_TAB_KEYWORDS, DOUBAN_HOME, "豆瓣")


def activate_chrome_and_switch_to_imdb():
    _activate_and_switch(IMDB_TAB_KEYWORDS, IMDB_HOME, "IMDb")


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


# ============================================================
#     抓取详情页：内容就绪检测 → 页面内直接抓取 → 快捷键重试兜底
# ============================================================
JS_DOUBAN_READY = r'''
var info = document.querySelector('#info');
var t = document.querySelector('span[property="v:itemreviewed"]')
     || document.querySelector('#content h1 span');
var r = document.querySelector('strong.rating_num');
return {href: location.href, host: location.hostname, rs: document.readyState,
        hasInfo: !!info,
        hasTitle: !!(t && (t.textContent || '').trim()),
        hasRating: !!(r && (r.textContent || '').trim())};
'''

JS_IMDB_READY = r'''
var h1 = document.querySelector('h1[data-testid="hero__pageTitle"]') || document.querySelector('h1');
var sc = document.querySelector('[data-testid="hero-rating-bar__aggregate-rating__score"]');
var hasLd = false, hasAgg = false;
var nodes = document.querySelectorAll('script[type="application/ld+json"]');
for (var i = 0; i < nodes.length; i++){
  try {
    var d = JSON.parse(nodes[i].textContent || '{}');
    if (d && d.name){ hasLd = true; if (d.aggregateRating) hasAgg = true; }
  } catch(e) {}
}
return {href: location.href, host: location.hostname, rs: document.readyState,
        hasTitle: !!(h1 && (h1.textContent || '').trim()),
        hasScore: !!(sc && (sc.textContent || '').trim()),
        hasLd: hasLd, hasAgg: hasAgg};
'''

JS_BLUR_FOCUS = r'''
try { if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur(); } catch(e) {}
try { window.focus(); } catch(e) {}
return true;
'''


def wait_content_ready(kind, needle, timeout=None) -> bool:
    """
    等详情页「内容真的渲染出来」，而不只是 URL 变了：
      豆瓣：#info + 标题出现；IMDb：h1 + (评分条 或 JSON-LD 评分)；
      IMDb 若始终无评分，则在 readyState=complete 后再宽限 IMDB_NO_RATING_GRACE 秒（可能尚未开分）。
    JS 不可用时退化为固定等待。返回 True=确认就绪，False=超时/未知（调用方仍会尽力尝试）。
    """
    timeout = timeout or CONTENT_READY_TIMEOUT.get(kind, 25)
    if not js_available():
        time.sleep(min(timeout, CONTENT_READY_FALLBACK_SLEEP.get(kind, 6)))
        return False

    js = JS_DOUBAN_READY if kind == 'douban' else JS_IMDB_READY
    nd = (needle or '').lower()
    t0 = time.time()
    title_seen, warned, last_log = None, False, t0
    while time.time() - t0 < timeout:
        r = run_page_js(js)
        if isinstance(r, dict):
            href = str(r.get('href', '')).lower()
            host = str(r.get('host', '')).lower()
            if kind == 'douban' and host.startswith('sec.douban.com'):
                if not warned:
                    print("  ⚠️ 豆瓣弹出了验证/风控页，请在浏览器里手动完成验证，程序会继续等待…")
                    warned = True
            elif not nd or nd in href:
                if kind == 'douban':
                    if r.get('hasInfo') and r.get('hasTitle'):
                        time.sleep(WAIT_PAGE_SETTLE)
                        print(f"  ✅ 豆瓣详情页内容已就绪（{time.time() - t0:.1f}s）")
                        return True
                else:
                    if r.get('hasTitle'):
                        if r.get('hasScore') or r.get('hasAgg'):
                            time.sleep(WAIT_PAGE_SETTLE)
                            print(f"  ✅ IMDb 详情页内容已就绪（{time.time() - t0:.1f}s）")
                            return True
                        title_seen = title_seen or time.time()
                        if r.get('rs') == 'complete' and time.time() - title_seen >= IMDB_NO_RATING_GRACE:
                            print("  ℹ️ IMDb 页面已加载完成但未见评分（可能尚未开分），继续抓取")
                            return True
        if time.time() - last_log >= 5:
            print(f"  ⏳ 等待{'豆瓣' if kind == 'douban' else 'IMDb'}详情页内容渲染…（已 {time.time() - t0:.0f}s）")
            last_log = time.time()
        time.sleep(POLL_INTERVAL)

    print(f"  ⚠️ 等待详情页内容就绪超时（{timeout}s），仍会尝试抓取")
    return False


def validate_scraped(kind, scraped, needle=''):
    """校验抓到的数据是否可信。返回 (ok, 原因)。"""
    if not isinstance(scraped, dict):
        return False, '结果不是有效 JSON'
    if scraped.get('type') == 'error':
        return False, f"插件内部报错：{scraped.get('error')}"
    url = str(scraped.get('url', ''))
    if kind == 'douban':
        if needle and needle.lower() not in url.lower():
            return False, f'URL 与目标不一致（期望含 {needle} / 实际 {url or "空"}）'
        if not (str(scraped.get('name', '')).strip() or str(scraped.get('year', '')).strip()):
            return False, '页面内容为空（可能尚未渲染）'
        return True, ''
    got = normalize_imdb_id(scraped.get('imdb_id', '') or url)
    if not got:
        return False, '落地页不是 IMDb 条目页（无 tt 编号）'
    exp = normalize_imdb_id(needle)
    if exp and exp != got:
        return False, f'ID 不匹配（期望 {exp} / 实际 {got}）'
    return True, ''


# —— 直接在页面内执行与插件「同源」的抓取函数（源码取自 background.js，避免维护两份）——
_SCRAPER_SRC = {}


def load_scraper_source(fn_name):
    if fn_name in _SCRAPER_SRC:
        return _SCRAPER_SRC[fn_name]
    src = None
    try:
        text = BACKGROUND_JS_PATH.read_text(encoding='utf-8')
        m = re.search(r'^function\s+' + re.escape(fn_name) + r'\s*\(\s*\)\s*\{', text, re.M)
        if m:
            nxt = re.search(r'^// =+', text[m.end():], re.M)   # 函数以下一个「// ====」分隔横幅为界
            end = m.end() + nxt.start() if nxt else len(text)
            cand = text[m.start():end].rstrip()
            if cand.endswith('}') and cand.count('{') == cand.count('}'):
                src = cand
    except Exception as e:
        print(f"  ⚠️ 读取 {BACKGROUND_JS_PATH} 失败：{e}")
    if not src:
        print(f"  ⚠️ 无法从 background.js 提取 {fn_name}，将不使用页面内直接抓取")
    _SCRAPER_SRC[fn_name] = src
    return src


def scrape_via_js(kind, needle, label):
    fn = 'scrapeDoubanPage' if kind == 'douban' else 'scrapeImdbPage'
    src = load_scraper_source(fn)
    if not src:
        return None
    best = None
    for n in range(1, SCRAPE_JS_ATTEMPTS + 1):
        data = run_page_js(src + f"\nreturn {fn}();", timeout=30)
        ok, why = validate_scraped(kind, data, needle)
        if ok:
            # IMDb 评分条偶尔晚一拍：没评分时多给一次机会，最后一次仍空则照单全收
            if kind == 'imdb' and not str(data.get('imdb_rating', '')).strip() and n < SCRAPE_JS_ATTEMPTS:
                best = data
                print(f"  ℹ️ {label} 第 {n}/{SCRAPE_JS_ATTEMPTS} 次未读到评分，稍后再读一次")
                time.sleep(2)
                continue
            print(f"  ✅ {label}：已在页面内直接抓取（无需快捷键/下载）")
            return data
        print(f"  ⚠️ {label} 页面内抓取第 {n}/{SCRAPE_JS_ATTEMPTS} 次不合格：{why}")
        if n < SCRAPE_JS_ATTEMPTS:
            time.sleep(2)
            wait_content_ready(kind, needle, timeout=HOTKEY_REREADY_TIMEOUT)
    return best


# ------------------ 触发插件并取结果（快捷键 + 重试 + 校验） ------------------
def _prepare_page_for_hotkey():
    """发快捷键前：Chrome 置前、页面焦点从输入框移开。"""
    bring_chrome_front()
    if _JS_OK:
        run_page_js(JS_BLUR_FOCUS)
    time.sleep(0.3)


def trigger_plugin_and_get_json(download_glob, label, kind='', needle=''):
    """
    按 Option+N 触发插件并等待下载；每次只等 WAIT_DOWNLOAD_PER_ATTEMPT 秒，
    没下载/内容不合格就重新确认页面、重按，最多 HOTKEY_MAX_ATTEMPTS 次。
    """
    if not kind:
        kind = 'douban' if 'douban' in download_glob else 'imdb'
    clear_old_downloads(download_glob)

    for attempt in range(1, HOTKEY_MAX_ATTEMPTS + 1):
        if needle:
            u = get_chrome_active_url() or ''
            if needle.lower() not in u.lower():
                print(f"  ⚠️ 当前标签页 URL 不含「{needle}」（{u or '空'}），先等待跳转…")
                wait_for_active_url_contains(needle, 10)

        _prepare_page_for_hotkey()
        pyautogui.hotkey('option', 'n', interval=0.1)
        print(f"已触发 Option+N（{label}）第 {attempt}/{HOTKEY_MAX_ATTEMPTS} 次，"
              f"等待插件下载结果（≤{WAIT_DOWNLOAD_PER_ATTEMPT}s）...")

        downloaded = wait_for_download(download_glob, WAIT_DOWNLOAD_PER_ATTEMPT)
        reason = ''
        if downloaded:
            scraped = None
            try:
                scraped = load_json(downloaded)
            except Exception as e:
                reason = f'读取下载 json 失败：{e}'
            move_to_trash(downloaded)
            if not reason:
                ok, why = validate_scraped(kind, scraped, needle)
                if ok:
                    return scraped
                reason = why
            print(f"  ⚠️ {label} 下载内容不合格：{reason}")
        else:
            print(f"  ⚠️ {label} 第 {attempt} 次按键后未检测到下载（快捷键可能被吞/插件尚未就绪）")

        if attempt < HOTKEY_MAX_ATTEMPTS:
            time.sleep(HOTKEY_RETRY_PAUSE * attempt)
            wait_content_ready(kind, needle, timeout=HOTKEY_REREADY_TIMEOUT)

    print(f"❌ {label} 经 {HOTKEY_MAX_ATTEMPTS} 次尝试仍未取得有效结果。")
    return None


def scrape_current_page(kind, needle, download_glob, label):
    """
    统一入口：kind='douban'|'imdb'；needle 用于确认页面（豆瓣 '/subject/ID'，IMDb 'ttXXXX'）。
    顺序：等内容就绪 → 页面内直接抓取 → 快捷键(带重试)兜底。
    """
    if not needle:
        needle = '/subject/' if kind == 'douban' else '/title/tt'
    print(f"\n----- 抓取 {label} 详情页 -----")
    wait_content_ready(kind, needle)

    if SCRAPE_PREFER_DIRECT_JS and js_available():
        data = scrape_via_js(kind, needle, label)
        if data:
            return data
        print("  ⚠️ 页面内直接抓取未成功，改用插件快捷键（带重试）")
    return trigger_plugin_and_get_json(download_glob, label, kind=kind, needle=needle)


# ============================================================
#                  DOM 路线：输入 + 读取联想
# ============================================================
def dom_set_input(selectors, text) -> bool:
    r = run_page_js(JS_SET_VALUE, {'selectors': selectors, 'text': text})
    return bool(r and r.get('ok'))


def dom_fill_input(selectors, text, label, open_imdb=False):
    """激活输入框并填入文本。返回 'paste' / 'js' / None(找不到输入框)。"""
    r = run_page_js(JS_FOCUS_INPUT, {'selectors': selectors, 'openImdbSearch': open_imdb})
    if not r or not r.get('ok'):
        print(f"  {label}：页面中未找到搜索框")
        return None

    if r.get('focused') and r.get('hasFocus'):
        copy_to_clipboard(text)
        pyautogui.hotkey('command', 'a')
        time.sleep(0.1)
        pyautogui.hotkey('command', 'v')
        time.sleep(0.4)
        v = run_page_js(JS_GET_VALUE, {'selectors': selectors})
        if v and norm_title(v.get('value', '')) == norm_title(text):
            print(f"  ✅ {label}：已激活搜索框并粘贴「{text}」")
            return 'paste'
        print(f"  ⚠️ {label}：粘贴后读回内容不一致，改用 JS 写值")
    else:
        print(f"  ⚠️ {label}：页面没有键盘焦点（focused={r.get('focused')}, "
              f"hasFocus={r.get('hasFocus')}），改用 JS 写值")

    if dom_set_input(selectors, text):
        print(f"  ✅ {label}：已用 JS 写入「{text}」")
        return 'js'
    return None


def wait_douban_suggestions(query, timeout=DOUBAN_SUGGEST_TIMEOUT,
                            min_wait=DOUBAN_SUGGEST_MIN_WAIT,
                            stable_rounds=DOUBAN_SUGGEST_STABLE_ROUNDS):
    """
    返回该检索词对应的 subject 联想列表（可能为空列表）；完全没出现返回 None。
    规则：输入框值 == 检索词；联想链接 ?suggest= 与检索词一致（或列表可见）；
          内容连续 stable_rounds 次不变，且距输入已过 min_wait 秒，才认定「加载完毕」。
    """
    nq = norm_title(query)
    start = time.time()
    last_sig, stable, last_subjects = None, 0, None
    while time.time() - start < timeout:
        r = run_page_js(JS_DOUBAN_SUGGEST, {'selectors': DOUBAN_INPUT_SELECTORS})
        ok, subjects, sig = False, [], None
        if isinstance(r, dict) and r.get('ready') and r.get('items') \
                and norm_title(r.get('value', '')) == nq:
            all_items = r['items']
            suggs = [it.get('suggest', '') for it in all_items if it.get('suggest')]
            if suggs:
                ok = all(norm_title(s) == nq for s in suggs)
            else:
                ok = bool(r.get('shown'))
            if ok:
                subjects = [it for it in all_items
                            if re.search(r'/subject/\d+', it.get('link', ''))]
                sig = tuple((it.get('link'), it.get('title'), it.get('year')) for it in all_items)

        if ok:
            if sig == last_sig:
                stable += 1
            else:
                last_sig, stable = sig, 0
            last_subjects = subjects
            if stable >= stable_rounds and time.time() - start >= min_wait:
                return subjects
        else:
            last_sig, stable = None, 0
        time.sleep(POLL_INTERVAL)

    if last_subjects is not None:
        print("  ℹ️ 联想列表在超时前未完全稳定，使用最后一次读取结果")
        return last_subjects
    return None


def wait_imdb_suggestions(query, timeout=WAIT_SUGGEST_TIMEOUT, min_wait=1.0):
    """返回 (status, items)；status: ok / empty / no_listbox / unparsed。"""
    nq = norm_title(query)
    start = time.time()
    saw_listbox = False
    last_sig = None
    while time.time() - start < timeout:
        r = run_page_js(JS_IMDB_SUGGEST, {'selectors': IMDB_INPUT_SELECTORS})
        if isinstance(r, dict) and r.get('ready'):
            saw_listbox = True
            items = r.get('items') or []
            if items and norm_title(r.get('value', '')) == nq and time.time() - start >= min_wait:
                sig = tuple((it.get('kind'), it.get('id') or it.get('title')) for it in items)
                if sig == last_sig:
                    if not any(it.get('kind') in ('title', 'name') for it in items):
                        return 'unparsed', items
                    return 'ok', items
                last_sig = sig
        time.sleep(POLL_INTERVAL)
    return ('empty' if saw_listbox else 'no_listbox'), []


# ------------------ 豆瓣：公共 ------------------
def ensure_douban_movie_page():
    """豆瓣阶段从 movie.douban.com 开始（若当前停留在搜索结果页等其它页面，先回电影首页）。"""
    u = get_chrome_active_url() or ''
    if 'movie.douban.com' not in u:
        print(f"  当前标签不在豆瓣电影站（{u or '空'}），先跳转电影首页")
        navigate_active_tab(DOUBAN_HOME)
        wait_page_ready('movie.douban.com')


def douban_open_subject_and_scrape(link):
    m = re.search(r'/subject/(\d+)', link or '')
    if not m:
        print(f"❌ 无法从链接解析豆瓣条目 ID：{link}")
        return None
    sid = m.group(1)
    needle = f'/subject/{sid}'
    url = f'https://movie.douban.com/subject/{sid}/'
    if not navigate_active_tab(url):
        return None
    wait_page_ready(needle)

    scraped = scrape_current_page('douban', needle, DOUBAN_DOWNLOAD_GLOB, '豆瓣')
    if not scraped:
        return None
    if needle not in str(scraped.get('url', '')):
        print(f"❌ 抓取结果 URL 与选中条目不一致（期望 {needle} / 实际 {scraped.get('url')}），丢弃。")
        return None
    got_year = str(scraped.get('year', '')).strip()
    if got_year and got_year not in douban_year_levels(ACTIVE_YEARS):
        print(f"  ⚠️ 详情页年份 {got_year} 不在目标年份 {ACTIVE_YEARS}（含容差）中，请留意（仍按选中结果写回）")
    return scraped


# ------------------ 豆瓣：搜索结果页（回车兜底） ------------------
def build_douban_search_url(name, start=0):
    url = DOUBAN_SEARCH_URL.format(q=quote(name, safe=''))
    if start:
        url += f'&start={start}'
    return url


def _qs_of(url):
    try:
        return parse_qs(urlparse(url or '').query)
    except Exception:
        return {}


def _search_text_of(url) -> str:
    return (_qs_of(url).get('search_text') or [''])[0]


def _start_of(url) -> int:
    try:
        return int((_qs_of(url).get('start') or ['0'])[0] or 0)
    except ValueError:
        return 0


def wait_douban_search_nav(name, timeout):
    """等待活动标签进入「本检索词」的搜索结果页。返回 ok / mismatch / subject / timeout。"""
    nq = norm_title(name)
    start = time.time()
    while time.time() - start < timeout:
        u = get_chrome_active_url() or ''
        if 'subject_search' in u:
            if norm_title(_search_text_of(u)) == nq:
                wait_page_ready('subject_search')
                return 'ok'
            return 'mismatch'
        if re.search(r'movie\.douban\.com/subject/\d+', u):
            return 'subject'      # 回车时选中了某条联想，进入了详情页
        time.sleep(POLL_INTERVAL)
    return 'timeout'


def douban_submit_search(name) -> bool:
    """输入框带着原字串直接回车；失败则直接打开搜索 URL。返回是否已到达正确的搜索结果页。"""
    print("\n----- 豆瓣：联想未命中 → 回车进入搜索结果页 -----")
    submitted = False
    r = run_page_js(JS_FOCUS_INPUT, {'selectors': DOUBAN_INPUT_SELECTORS, 'openImdbSearch': False})
    if r and r.get('ok'):
        if norm_title(r.get('value', '')) != norm_title(name):
            dom_set_input(DOUBAN_INPUT_SELECTORS, name)
            r = run_page_js(JS_FOCUS_INPUT, {'selectors': DOUBAN_INPUT_SELECTORS,
                                             'openImdbSearch': False})
        if r and r.get('focused') and r.get('hasFocus'):
            pyautogui.press('enter')
            submitted = True
            print(f"  ⏎ 已在搜索框（内容「{name}」）按下回车")
        else:
            s = run_page_js(JS_SUBMIT_FORM, {'selectors': DOUBAN_INPUT_SELECTORS})
            submitted = bool(s and s.get('ok'))
            print(f"  页面无键盘焦点，JS 提交表单：{'成功' if submitted else '失败'}")
    else:
        print("  页面中未找到搜索框")

    if submitted:
        st = wait_douban_search_nav(name, DOUBAN_SUBMIT_NAV_TIMEOUT)
        if st == 'ok':
            print("  ✅ 已进入搜索结果页")
            return True
        print(f"  ⚠️ 回车后未进入正确的搜索结果页（{st}），改为直接打开搜索 URL")

    if not navigate_active_tab(build_douban_search_url(name)):
        return False
    return wait_douban_search_nav(name, WAIT_PAGE_READY_TIMEOUT) == 'ok'


def wait_douban_search_results(name, start_offset, timeout=DOUBAN_SEARCH_RESULT_TIMEOUT):
    """返回 (items, total)；items: list（[] = 确认无影视结果）或 None（读不到）。"""
    nq = norm_title(name)
    t0 = time.time()
    last_sig, stable, empty_rounds = None, 0, 0
    last_items, total = None, None
    while time.time() - t0 < timeout:
        r = run_page_js(JS_DOUBAN_SEARCH_RESULTS)
        if isinstance(r, dict):
            href = r.get('href', '')
            if 'subject_search' in href and norm_title(_search_text_of(href)) == nq \
                    and _start_of(href) == start_offset:
                if r.get('total') is not None:
                    total = r.get('total')
                items = r.get('items') or []
                elapsed = time.time() - t0
                if items:
                    empty_rounds = 0
                    sig = tuple((it.get('sid'), it.get('raw_title')) for it in items)
                    if sig == last_sig:
                        stable += 1
                    else:
                        last_sig, stable = sig, 0
                    last_items = items
                    if stable >= DOUBAN_SEARCH_STABLE_ROUNDS and elapsed >= DOUBAN_SEARCH_MIN_WAIT:
                        return items, total
                elif r.get('has_data') and r.get('data_count') == 0 and r.get('rs') == 'complete':
                    empty_rounds += 1
                    if empty_rounds >= DOUBAN_SEARCH_EMPTY_ROUNDS and elapsed >= DOUBAN_SEARCH_MIN_WAIT:
                        return [], total
        time.sleep(POLL_INTERVAL)
    if last_items:
        print("  ℹ️ 搜索结果在超时前未完全稳定，使用最后一次读取结果")
        return last_items, total
    return None, total


def douban_search_page_pick(name):
    if not douban_submit_search(name):
        print("❌ 无法进入豆瓣搜索结果页。")
        return None

    total = None
    last_full = True
    for page in range(max(1, DOUBAN_SEARCH_MAX_PAGES)):
        start = page * DOUBAN_SEARCH_PAGE_SIZE
        if page > 0:
            if total is not None and start >= total:
                break
            if not last_full:
                break
            print(f"  第 {page} 页未命中，翻到第 {page + 1} 页")
            if not navigate_active_tab(build_douban_search_url(name, start)):
                break
            wait_page_ready(f'start={start}')

        items, t = wait_douban_search_results(name, start)
        if t is not None:
            total = t
        if items is None:
            print("  ❌ 搜索结果页未能读取到结果（超时）")
            break
        if not items:
            print(f"  ❌ 搜索结果页没有与「{name}」相关的影视条目")
            break

        pick = pick_douban_search_result(items, name, ACTIVE_YEARS, page)
        if pick:
            return pick
        last_full = len(items) >= DOUBAN_SEARCH_PAGE_SIZE
    return None


# ------------------ 豆瓣：DOM 路线 ------------------
def douban_stage_dom(name):
    print(f"\n----- 豆瓣（DOM 精准路线，年份要求 {ACTIVE_YEARS}）-----")
    ensure_douban_movie_page()

    method = dom_fill_input(DOUBAN_INPUT_SELECTORS, name, '豆瓣')
    if method is None:
        print("  当前豆瓣页没有搜索框，跳转电影首页重试")
        navigate_active_tab(DOUBAN_HOME)
        wait_page_ready('movie.douban.com')
        method = dom_fill_input(DOUBAN_INPUT_SELECTORS, name, '豆瓣')

    pick = None
    if method is not None:
        items = wait_douban_suggestions(name)
        if items is None and method == 'paste':
            print("  联想未出现，改用 JS 写值重试一次")
            dom_set_input(DOUBAN_INPUT_SELECTORS, name)
            items = wait_douban_suggestions(name)

        if items is None:
            print("  ⚠️ 豆瓣联想列表未出现（确实无联想）")
        elif not items:
            print("  ⚠️ 豆瓣联想中没有影视条目")
        else:
            pick = pick_douban_suggestion(items, name, ACTIVE_YEARS)
    else:
        print("  ⚠️ 豆瓣搜索框仍未找到，直接走搜索结果页")

    if pick:
        return douban_open_subject_and_scrape(pick['link'])

    # —— 需求2：联想无结果 / 无符合条目 → 回车进入搜索结果页再找 ——
    pick = douban_search_page_pick(name)
    if not pick:
        return None
    return douban_open_subject_and_scrape(pick['link'])


# ------------------ 图片路线（兜底，保持原逻辑） ------------------
def process_page_by_image(input_detector, popup_img_path, download_glob, paste_text, label):
    print(f"\n----- 开始处理 {label} 页面（图片识别兜底路线）-----")

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
        _, ploc, _pshape = popup_detector.find_images_on_screen(threshold=0.9)
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

    kind = 'douban' if label == '豆瓣' else 'imdb'
    return scrape_current_page(kind, '', download_glob, label)


# ------------------ IMDb 直达流程 ------------------
def process_imdb_by_id(imdb_id):
    url = IMDB_TITLE_URL.format(imdb_id)
    print(f"\n----- IMDb 直达路线：{url} -----")
    if not open_url_in_chrome(url, 'imdb.com'):
        return None
    if wait_page_ready(imdb_id, WAIT_NAV_TIMEOUT):
        print("✅ 已到达目标 IMDb 页面")
    else:
        print("⚠️ 未完全确认页面就绪，仍继续尝试")
    return scrape_current_page('imdb', imdb_id, IMDB_DOWNLOAD_GLOB, 'IMDb')


# ------------------ IMDb：DOM 搜索路线 ------------------
def imdb_dom_search_and_pick(query):
    """返回 (status, pick)；status: picked / no_match / dom_failed。"""
    method = dom_fill_input(IMDB_INPUT_SELECTORS, query, 'IMDb', open_imdb=True)
    if method is None:
        print("  当前 IMDb 页没有搜索框，跳转首页重试")
        navigate_active_tab(IMDB_HOME)
        wait_page_ready('imdb.com')
        method = dom_fill_input(IMDB_INPUT_SELECTORS, query, 'IMDb', open_imdb=True)
        if method is None:
            return 'dom_failed', None

    status, items = wait_imdb_suggestions(query)
    if status in ('empty', 'no_listbox') and method == 'paste':
        print("  联想未出现，改用 JS 写值重试一次")
        dom_set_input(IMDB_INPUT_SELECTORS, query)
        status, items = wait_imdb_suggestions(query)

    if status in ('no_listbox', 'unparsed'):
        print(f"  ⚠️ IMDb 联想 DOM 无法解析（{status}）")
        return 'dom_failed', None
    if status == 'empty':
        print("  IMDb 联想为空")
        return 'no_match', None

    pick = pick_imdb_suggestion(items, query, ACTIVE_YEARS)
    return ('picked', pick) if pick else ('no_match', None)


def imdb_stage_search(ranked):
    """返回 (scraped, picked_id)。"""
    queries = []
    for _t, _p, q, _s in ranked:
        if q not in queries:
            queries.append(q)
    queries = queries[:IMDB_MAX_QUERY_TRIES]

    activate_chrome_and_switch_to_imdb()

    if js_available():
        dom_broken = False
        for q in queries:
            print(f"\n🔎 [DOM] IMDb 检索：「{q}」")
            status, pick = imdb_dom_search_and_pick(q)
            if status == 'picked':
                return process_imdb_by_id(pick['id']), pick['id']
            if status == 'dom_failed':
                dom_broken = True
                break
        if not dom_broken:
            print("❌ 所有检索词都未在 IMDb 联想中命中「名字 + 年份」规则，放弃（不盲点第一项）。")
            return None, ''
        if not IMDB_IMAGE_FALLBACK:
            return None, ''
        print("⚠️ 降级为图片识别兜底（点击联想第一项）")
        dom_set_input(IMDB_INPUT_SELECTORS, '')   # 清空输入框，便于模板图匹配
        pyautogui.press('escape')
        time.sleep(0.5)
    elif not IMDB_IMAGE_FALLBACK:
        return None, ''

    q = queries[0]
    print(f"\n🔎 [图片] IMDb 检索：「{q}」")
    imdb_detector = ScreenDetector(template_names=IMDB_INPUT_IMG, clickValue='left')
    scraped = process_page_by_image(imdb_detector, IMDB_POPUP_IMG, IMDB_DOWNLOAD_GLOB,
                                    paste_text=q, label="IMDb")
    return scraped, ''

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='', help='OVideos.json 中的项目名（用于定位，可含年份）')
    ap.add_argument('--search', default='', help='豆瓣/IMDb 检索用名（不含年份）')
    ap.add_argument('--years', default='', help='目标年份，逗号分隔，如 2026,2027')
    return ap.parse_args()

# ============================================================
#            名字回退：完整名 → 去掉英文部分后的中文名
# ============================================================
RE_LATIN_CHUNK = re.compile(r"[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F0-9'\u2019\.\-:&, ]*")

RUN_INFO = {}   # 本次运行的关键信息，结束时用于写日志


def strip_latin_part(name: str) -> str:
    """'黑帮生存战TheMob' -> '黑帮生存战'；'绝命毒师 Breaking Bad' -> '绝命毒师'；无需去除时返回 ''"""
    s = unicodedata.normalize('NFKC', str(name or '')).strip()
    if not (RE_HAN.search(s) and RE_LATIN.search(s)):
        return ''
    t = RE_LATIN_CHUNK.sub(' ', s)
    t = re.sub(r'\s+', ' ', t).strip(_STRIP_CHARS).strip()
    if not RE_HAN.search(t) or norm_title(t) == norm_title(s):
        return ''
    return t


def build_name_candidates(name: str):
    names = [name]
    alt = strip_latin_part(name) if NAME_FALLBACK_ENABLED else ''
    if alt and norm_title(alt) != norm_title(name):
        names.append(alt)
    return names


def douban_stage_once(name):
    """用一个检索名跑完豆瓣阶段，返回 scraped 或 None。"""
    if js_available():
        return douban_stage_dom(name)
    if DOUBAN_IMAGE_FALLBACK:
        print("⚠️ 豆瓣走图片识别兜底（点击联想第一项，可能不准；该模式下无搜索结果页兜底）")
        detector = ScreenDetector(template_names=DOUBAN_INPUT_IMG, clickValue='left')
        return process_page_by_image(detector, DOUBAN_POPUP_IMG, DOUBAN_DOWNLOAD_GLOB,
                                     paste_text=name, label="豆瓣")
    return None


def douban_stage_with_fallback(names):
    """依次尝试候选名；返回 (scraped, 命中的检索名)。"""
    for i, nm in enumerate(names):
        if i > 0:
            print(f"\n🔁 名字回退：「{names[0]}」无合格结果，改用「{nm}」再次检索豆瓣")
            RUN_INFO['fallback_tried'] = True
        RUN_INFO.setdefault('names_tried', []).append(nm)
        scraped = douban_stage_once(nm)
        if scraped:
            return scraped, nm
    return None, ''


def _notify_mac(title, msg):
    def safe(s):
        return str(s).replace('\\', '/').replace('"', "'")
    subprocess.run(['osascript', '-e',
                    f'display notification "{safe(msg)}" with title "{safe(title)}"'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def report_name_fallback(exit_code):
    """只有真的触发过回退才写日志，并在控制台和通知中心提醒。"""
    if not RUN_INFO.get('fallback_tried'):
        return
    info = RUN_INFO
    douban_ok = bool(info.get('douban_url'))
    entry = {
        'time': datetime.datetime.now().isoformat(timespec='seconds'),
        'category': info.get('category', ''),
        'raw_name': info.get('raw_name', ''),          # JSON 原名（写回用这个）
        'names_tried': info.get('names_tried', []),
        'used_name': info.get('used_name', '') if douban_ok else '',
        'result': 'douban_ok' if douban_ok else 'douban_failed',
        'douban_url': info.get('douban_url', ''),
        'douban_page_name': info.get('douban_page_name', ''),
        'imdb_id': info.get('imdb_id', ''),
        'exit_code': exit_code,
        'note': '写回使用 raw_name；请核对 douban_page_name 是否为正确作品',
    }
    with open(NAME_FALLBACK_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    print("\n" + "!" * 60)
    print(f"🔔 名字回退日志已记录：{NAME_FALLBACK_LOG}")
    if douban_ok:
        print(f"🔔 JSON 原名「{info.get('raw_name')}」，实际用「{info.get('used_name')}」检索成功，"
              f"豆瓣页名称「{info.get('douban_page_name')}」，请人工核对！")
    else:
        print(f"🔔 名字回退后仍失败（尝试过：{info.get('names_tried')}）")
    print("!" * 60)

    if NAME_FALLBACK_NOTIFY:
        msg = (f"{info.get('raw_name')} → 用「{info.get('used_name')}」检索成功，请核对"
               if douban_ok else f"{info.get('raw_name')} 名字回退后仍失败")
        _notify_mac('名字回退提醒', msg)

# ------------------ 主流程 ------------------
def main() -> int:
    print("=== 豆瓣 + IMDb 一次性抓取启动 (v5) ===")

    args = parse_args()
    cli_name   = args.name.strip()
    cli_search = args.search.strip()
    cli_years  = [y.strip() for y in args.years.split(',') if y.strip()]

    raw = cli_name or read_clipboard()
    if not raw:
        print("❌ 剪贴板为空，无法继续。")
        return EXIT_DOUBAN_FAIL

    if cli_search:
        # 调用方已明确给出检索名：直接使用，不再从项目名里猜
        name, year_hint = cli_search, ''
    elif cli_name and cli_years:
        name, year_hint = raw, ''
    else:
        name, year_hint = split_name_year(raw)

    print(f"📋 项目名{'(命令行)' if cli_name else '(剪贴板)'}: {raw}")
    print(f"   检索名: {name}   年份后缀: {year_hint or '无'}")

    data = load_json(OVIDEOS_JSON)

    # 先用原文（带年份）查 JSON，查不到再用去年份后的名字查
    category, idx, item = find_item_by_name(data, raw)
    if item is None and name != raw:
        category, idx, item = find_item_by_name(data, name)
    if item is None:
        print(f"❌ 未在 OVideos.json 中找到「{raw}」（去年份后「{name}」也未找到），程序结束。")
        return EXIT_DOUBAN_FAIL
    print(f"✅ 已定位项目 [{category}][{idx}]")
    RUN_INFO.update({'raw_name': raw, 'category': category})

    global ACTIVE_YEARS, FALLBACK_YEARS
    ACTIVE_YEARS = resolve_primary_years(item, cli_years, year_hint)
    FALLBACK_YEARS = build_fallback_years(ACTIVE_YEARS)
    print(f"   主年份: {ACTIVE_YEARS}")
    if FALLBACK_YEARS:
        print(f"   未来年份回退: {FALLBACK_YEARS}（主年份未命中时启用，优先级低于主年份）")

    # ========== 第一阶段：豆瓣（含名字回退） ==========
    activate_chrome_and_switch_to_douban()
    names = build_name_candidates(name)
    if len(names) > 1:
        print(f"🔁 名字回退已启用，候选检索名：{names}")
    douban_scraped, used_name = douban_stage_with_fallback(names)
    if douban_scraped:
        RUN_INFO.update({
            'used_name': used_name,
            'douban_url': douban_scraped.get('url', ''),
            'douban_page_name': douban_scraped.get('name', ''),
        })

    # —— 豆瓣失败：整个流程停止（IMDb 强依赖豆瓣信息）——
    if not douban_scraped:
        print(f"\n🛑 豆瓣联想与搜索结果页均未找到「{name}」{ACTIVE_YEARS} 的匹配条目（或抓取失败），"
              f"程序停止，不进行 IMDb 阶段。")
        print("=== 结束 ===")
        return EXIT_DOUBAN_FAIL

    aka           = str(douban_scraped.get('aka', '')).strip()
    foreign_title = str(douban_scraped.get('foreign_title', '')).strip()
    imdb_id       = normalize_imdb_id(douban_scraped.get('imdb_id', ''))

    print(f"🎬 又名 (aka)            : {aka or '（空）'}")
    print(f"🎬 主标题外文 (foreign)  : {foreign_title or '（空）'}")
    print(f"🆔 豆瓣页 IMDb ID        : {imdb_id or '（空）'}")

    _q, _src, ranked = pick_imdb_search_query(aka, foreign_title, used_name or name)
    print_candidates(ranked)

    if update_douban(item, douban_scraped):
        save_json(OVIDEOS_JSON, data)
        print("💾 豆瓣数据已写回 OVideos.json。")
    else:
        print("豆瓣无有效变化，未写回。")

    # ========== 第二阶段：IMDb ==========
    imdb_scraped = None
    expected_id = imdb_id

    if imdb_id:
        imdb_scraped = process_imdb_by_id(imdb_id)
        if not imdb_scraped:
            print("⚠️ 直达路线失败，降级为搜索路线。")

    if imdb_scraped is None:
        if not ranked:
            print("\n❌ 既无 IMDb ID，也无有效检索词，无法继续 IMDb 阶段。")
            finalize_date(data, item, douban_scraped, None, expected_id, category)   # ← 新增：失败出口也要应用日期规则
            print("=== 结束 ===")
            return EXIT_IMDB_FAIL
        imdb_scraped, picked_id = imdb_stage_search(ranked)
        if picked_id:
            expected_id = picked_id

    RUN_INFO['imdb_id'] = expected_id
    if imdb_scraped:
        print(f"⭐ 抓到 IMDb 评分: {imdb_scraped.get('imdb_rating', '') or '（空）'}")
        if update_imdb(item, imdb_scraped, expected_id=expected_id):
            save_json(OVIDEOS_JSON, data)
            print("💾 IMDb 数据已写回 OVideos.json。")
        else:
            print("IMDb 无有效变化，未写回。")
    else:
        print("⚠️ IMDb 抓取失败。")
        finalize_date(data, item, douban_scraped, None, expected_id, category)       # ← 新增：失败出口也要应用日期规则
        print("\n=== 结束 ===")
        return EXIT_IMDB_FAIL

    # ← 新增：两阶段都完成后，按最高评分决定 date
    finalize_date(data, item, douban_scraped, imdb_scraped, expected_id, category)

    print("\n=== 全部完成，结束 ===")
    return EXIT_OK


if __name__ == '__main__':
    code = EXIT_DOUBAN_FAIL
    try:
        code = main()
    finally:
        report_name_fallback(code)   # 无论成功、失败还是异常，都记录回退情况
    sys.exit(code)