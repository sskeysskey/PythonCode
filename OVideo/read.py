import json
import argparse
import pyperclip
import re
import os
import sys
import tempfile

# 【新增】本轮正在处理的 URL，供 write.py 精确定位要写入的 mapping key
CURRENT_URL_FILE = '/tmp/downie_current_url.txt'

# SKIP_CATEGORIES = {'Drama', 'Movie'}
SKIP_CATEGORIES = set()

# ===== 读取顺序与数量配置 =====
REVERSE_SCAN = True              # True 表示每个分类倒着读取，False 表示原样正序读取
SCAN_LIMIT_PER_CATEGORY = 15000  # 每个分类最多读取的项目数；设为 0 或 None 表示不限制

# 需要执行"地区过滤"的分类集合（模糊匹配，命中任一关键字就跳过该项目）
REGION_FILTER_CATEGORIES = {'Drama', "Anime"}
# REGION_BLOCK_KEYWORDS = ('大陆', '中国', '内地')
REGION_BLOCK_KEYWORDS = ('测试',)

# 评分过滤阈值：豆瓣或 IMDB 任一 >= 此值即通过
RATING_THRESHOLD = 3.0
RATING_FIELDS = ('豆瓣', 'IMDB')

# ===== 渠道黑名单（全分类生效：不扫描、不抓取、不计入集数与优先级） =====
BLOCKED_CHANNEL_NAMES = set()
BLOCKED_CHANNEL_KEYWORDS = ()

# ===== 渠道优先级配置 =====
TOP_PRIORITY_CHANNELS = ['shangxidq', '线路2', '线路6', 'meiju8', '暴风', '天堂', '光速', '红牛', '量子', '淘片', 'xb6v']
CLOUD_SERIES_PREFIX = '云播线路'
CHANNEL_PRIORITY = ['chnland']

# ===== Drama / Anime 特殊规则:按集数抢占最高优先级 =====
EPISODE_COUNT_PRIORITY_CATEGORIES = {'Drama', 'Anime', 'Show'}
EPISODE_COUNT_PRIORITY_GROUP = ('shangxidq', '线路2', '线路6', '暴风', '天堂', '光速', '红牛', '量子', '淘片', 'xb6v')
EPISODE_COUNT_PRIORITY_MIN_HIT = 2      # 至少命中几个渠道才触发该规则

# ===== 各分类需要"完整处理"（无黑名单）的渠道数量配置 =====
MOVIE_REQUIRED_CHANNELS = 2
SERIES_CATEGORIES = {'Drama', 'Show', 'Anime'}
EPISODE_THRESHOLD = 20          # 集数阈值
SERIES_REQUIRED_SHORT = 2       # 集数 <= 阈值时，需要的完整渠道数
SERIES_REQUIRED_LONG = 1        # 集数 > 阈值时，需要的完整渠道数

# ===== 【调整】"更全渠道补抓"规则 =====
RICHER_CHANNEL_SCAN_ENABLED = True
RICHER_CHANNEL_SCAN_CATEGORIES = {'Drama', 'Anime'}  # 移除了 'Show'，仅针对电视剧和动漫
RICHER_CHANNEL_MIN_YEAR = 2025                       # 仅超过该年份（> 2025，即 2026）才补抓
RICHER_CHANNEL_MIN_ADVANTAGE = 1
RICHER_CHANNEL_MAX_EXTRA = 2

# ===== 【新增】"满集锚点"规则 =====
# 以"已完成渠道中的最大集数"为锚点（符合更全补抓条件时以全部可用渠道最大集数为锚点），
# 只有集数 == 锚点的完整渠道才计为"完美渠道"；不足时优先从同集数的未抓渠道补齐。
ANCHOR_TIER_ENABLED = True
ANCHOR_TIER_CATEGORIES = {'Drama'}  # Movie 不建议开启（同片不同版本条目数无意义）
ANCHOR_TIER_FALLBACK = True  # 满集渠道耗尽（如被拉黑）时，降级计入集数较少的已完成渠道/按原优先级补齐

# ===== Show 全量抓取白名单 =====
SHOW_FULL_SCAN_WHITELIST = {
    '爱情岛(美国版) 第八季', '罗德岛娇妻', '荒野独居 第一季', '荒野独居 第二季', '荒野独居 第三季', '荒野独居 第四季',
    '荒野独居 第五季', '荒野独居 第六季', '荒野独居 第七季', '荒野独居 第八季', '荒野独居 第九季',
    '荒野独居 第十季', '荒野独居 第十一季', '荒野独居 第十二季', '荒野独居 第十三季'
}

DEFAULT_REQUIRED_CHANNELS = 1


# ===================== 多季渠道识别与集数解析 =====================
CN_NUM_MAP = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10
}


def _parse_season_num(text):
    """解析中文或阿拉伯数字季号。"""
    text = str(text).strip()
    if text.isdigit():
        return int(text)
    if text in CN_NUM_MAP:
        return CN_NUM_MAP[text]
    if text.startswith('十') and len(text) == 2 and text[1] in CN_NUM_MAP:
        return 10 + CN_NUM_MAP[text[1]]
    return None


def _parse_release_year(val):
    """
    智能提取年份整数：
    支持 "1994-03-28"、"1994"、1994、"1994/03/28"、"2026年" 等各类格式。
    【修复】原 \\b 在 Python3 中会把汉字视为单词字符，导致 "2026年" 解析失败；改用数字边界断言。
    解析失败返回 None。
    """
    if val is None:
        return None
    val_str = str(val).strip()
    m = re.search(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)', val_str)
    if m:
        return int(m.group(1))
    return None


def get_channel_effective_episodes(episodes, channel_name=''):
    """
    智能解析渠道的剧集。
    当检测到该渠道为多季合集（如 xb6v 的 S01E01 ~ S04E08 或 第1季/第2季），
    仅提取最新季（最高季号）对应的剧集字典用于集数统计和扫描。

    返回: (effective_episodes_dict, is_multi_season, season_label)
    """
    if not episodes or not isinstance(episodes, dict):
        return {}, False, ''

    se_pattern = re.compile(r'^[Ss](\d+)\s*[-_Ee]?\s*(\d+)', re.IGNORECASE)
    cn_pattern = re.compile(r'第\s*([0-9一二三四五六七八九十]+)\s*季')

    parsed_se = {}
    parsed_cn = {}
    matched_se = 0
    matched_cn = 0

    for ep_name, ep_url in episodes.items():
        name_str = str(ep_name).strip()
        m1 = se_pattern.search(name_str)
        if m1:
            s_num = int(m1.group(1))
            parsed_se.setdefault(s_num, {})[ep_name] = ep_url
            matched_se += 1
            continue

        m2 = cn_pattern.search(name_str)
        if m2:
            s_num = _parse_season_num(m2.group(1))
            if s_num is not None:
                parsed_cn.setdefault(s_num, {})[ep_name] = ep_url
                matched_cn += 1

    total_keys = len(episodes)
    selected_map = None

    # 当识别出多季（>=2季）且覆盖超过半数集数时，确认为多季合集
    if len(parsed_se) >= 2 and matched_se >= (total_keys * 0.5):
        selected_map = parsed_se
    elif len(parsed_cn) >= 2 and matched_cn >= (total_keys * 0.5):
        selected_map = parsed_cn

    if selected_map:
        latest_season_num = max(selected_map.keys())
        latest_eps = selected_map[latest_season_num]
        season_label = f"S{latest_season_num:02d}" if selected_map is parsed_se else f"第{latest_season_num}季"
        return latest_eps, True, season_label

    return episodes, False, ''


# ===================== 渠道黑名单相关工具 =====================
_BLOCKED_NAMES_LOWER = set()
_BLOCKED_KEYWORDS_LOWER = tuple()


def _normalize_channel_name(name):
    """统一渠道名：None -> ''，去首尾空白。"""
    return str(name or '').strip()


def rebuild_blocked_channel_cache():
    """根据 BLOCKED_CHANNEL_NAMES / BLOCKED_CHANNEL_KEYWORDS 重建匹配缓存。"""
    global _BLOCKED_NAMES_LOWER, _BLOCKED_KEYWORDS_LOWER
    _BLOCKED_NAMES_LOWER = {
        _normalize_channel_name(n).lower()
        for n in BLOCKED_CHANNEL_NAMES
        if _normalize_channel_name(n)
    }
    _BLOCKED_KEYWORDS_LOWER = tuple(
        _normalize_channel_name(k).lower()
        for k in BLOCKED_CHANNEL_KEYWORDS
        if _normalize_channel_name(k)
    )


def is_channel_blocked(name):
    """判断某个渠道名是否被拉黑（精确 + 模糊，均忽略大小写/首尾空格）。"""
    n = _normalize_channel_name(name).lower()
    if not n:
        return False
    if n in _BLOCKED_NAMES_LOWER:
        return True
    return any(kw in n for kw in _BLOCKED_KEYWORDS_LOWER)


def filter_blocked_playlists(playlists, item_label=None, verbose=True):
    kept, dropped = [], []
    for pl in playlists:
        name = _normalize_channel_name(pl.get('name')) or '未命名渠道'
        if is_channel_blocked(name):
            dropped.append(name)
        else:
            kept.append(pl)

    if verbose and dropped:
        label = item_label or '[未知项目]'
        print(f"  [渠道黑名单] {label} 跳过 {len(dropped)} 个渠道：{', '.join(dropped)}")

    return kept


def sanitize_priority_configs(verbose=True):
    global TOP_PRIORITY_CHANNELS, CHANNEL_PRIORITY, EPISODE_COUNT_PRIORITY_GROUP

    conflicts = []

    new_top = [c for c in TOP_PRIORITY_CHANNELS if not is_channel_blocked(c)]
    conflicts += [f"TOP_PRIORITY_CHANNELS:{c}"
                  for c in TOP_PRIORITY_CHANNELS if is_channel_blocked(c)]
    TOP_PRIORITY_CHANNELS = new_top

    new_prio = [c for c in CHANNEL_PRIORITY if not is_channel_blocked(c)]
    conflicts += [f"CHANNEL_PRIORITY:{c}"
                  for c in CHANNEL_PRIORITY if is_channel_blocked(c)]
    CHANNEL_PRIORITY = new_prio

    new_group = tuple(c for c in EPISODE_COUNT_PRIORITY_GROUP if not is_channel_blocked(c))
    conflicts += [f"EPISODE_COUNT_PRIORITY_GROUP:{c}"
                  for c in EPISODE_COUNT_PRIORITY_GROUP if is_channel_blocked(c)]
    EPISODE_COUNT_PRIORITY_GROUP = new_group

    if verbose and conflicts:
        print(f"[配置冲突] 以下渠道已在黑名单中，自动从优先级配置移除："
              f"{', '.join(conflicts)}")


def build_lookup_set(data):
    """
    【性能修复】把黑名单数据转为 set，O(1) 判断成员关系。
    - dict：原 `in` 判断的是 key，取 key 集合
    - list：原 `in` 只可能命中字符串元素，取其中的字符串
    - 其它类型：原样返回，保持原有语义
    """
    if isinstance(data, dict):
        return set(data.keys())
    if isinstance(data, list):
        return {x for x in data if isinstance(x, str)}
    return data


# ===================== 业务过滤与优先级工具 =====================
def get_scan_episodes(episodes, category, show_last_n, full_scan=False):
    if not episodes:
        return []

    urls_list = list(episodes.values())
    total_count = len(urls_list)

    if full_scan:
        return urls_list

    if category == 'Show':
        if total_count > 10:
            limit = show_last_n if show_last_n > 0 else 5
            return urls_list[-limit:]
        else:
            return urls_list

    return urls_list


def is_channel_viable(scan_episodes, blacklist_url):
    if not scan_episodes:
        return False
    return all(url not in blacklist_url for url in scan_episodes)


def is_channel_completed(scan_episodes, url_mapping):
    if not scan_episodes:
        return False
    return all(
        (url in url_mapping and str(url_mapping[url]).strip() != "")
        for url in scan_episodes
    )


def get_item_episode_count(playlists):
    """取该项目代表性的集数（所有未拉黑渠道里的最大有效集数，多季合集仅算最新季）。"""
    counts = []
    for pl in playlists:
        eps = pl.get('episodes', {}) or {}
        name = _normalize_channel_name(pl.get('name'))
        eff_eps, _, _ = get_channel_effective_episodes(eps, name)
        counts.append(len(eff_eps))
    return max(counts) if counts else 0


def get_required_channel_count(category, episode_count):
    if category == 'Movie':
        return MOVIE_REQUIRED_CHANNELS

    if category in SERIES_CATEGORIES:
        if episode_count > EPISODE_THRESHOLD:
            return SERIES_REQUIRED_LONG
        else:
            return SERIES_REQUIRED_SHORT

    return DEFAULT_REQUIRED_CHANNELS


def get_episode_count_priority_names(playlists, category,
                                     categories=EPISODE_COUNT_PRIORITY_CATEGORIES,
                                     group=None,
                                     min_hit=EPISODE_COUNT_PRIORITY_MIN_HIT):
    if category not in categories:
        return set()

    group = EPISODE_COUNT_PRIORITY_GROUP if group is None else group

    hit = set()
    for pl in playlists:
        name = _normalize_channel_name(pl.get('name'))
        if is_channel_blocked(name):
            continue
        if name in group and (pl.get('episodes') or {}):
            hit.add(name)

    if len(hit) >= min_hit:
        return hit
    return set()


def sort_playlists_by_priority(playlists, priority=None,
                               cloud_prefix=CLOUD_SERIES_PREFIX,
                               top_priority=None,
                               episode_priority_names=None):
    priority = CHANNEL_PRIORITY if priority is None else priority
    top_priority = TOP_PRIORITY_CHANNELS if top_priority is None else top_priority
    episode_priority_names = episode_priority_names or set()
    indexed = list(enumerate(playlists))

    def top_idx(name):
        return top_priority.index(name) if name in top_priority else len(top_priority)

    def sort_key(pair):
        original_idx, pl = pair
        name = _normalize_channel_name(pl.get('name'))

        if is_channel_blocked(name):
            return (9, 0, 0, original_idx)

        if name in episode_priority_names:
            eps = pl.get('episodes', {}) or {}
            eff_eps, _, _ = get_channel_effective_episodes(eps, name)
            ep_count = len(eff_eps)
            return (0, -ep_count, top_idx(name), original_idx)

        if name in top_priority:
            return (1, top_priority.index(name), 0, original_idx)

        if name.startswith(cloud_prefix):
            return (2, original_idx, 0, 0)

        if name in priority:
            return (3, priority.index(name), 0, original_idx)

        return (4, 0, 0, original_idx)

    indexed.sort(key=sort_key)
    return [pl for _, pl in indexed]


# ===================== 更全渠道补抓工具 =====================
def _describe_channel(rec):
    """统一的渠道描述文本，便于日志输出。"""
    if rec.get('is_multi_season'):
        return f"「{rec['name']}」({rec['season_label']}最新季 {rec['total']}集/原合集{rec['raw_total']}集)"
    return f"「{rec['name']}」({rec['total']}集)"


def _log_pick(rec, item_label, slot_text):
    """统一的"采用渠道"日志输出。"""
    extra_info = f"({rec['season_label']}最新季)" if rec['is_multi_season'] else ""
    if rec['truncated']:
        print(f"  [采用 {slot_text}] {item_label} 待抓渠道「{rec['name']}」{extra_info}"
              f"(Show 末尾 {len(rec['scan'])} 条，最新季共 {rec['total']} 集)")
    else:
        print(f"  [采用 {slot_text}] {item_label} 待抓渠道「{rec['name']}」{extra_info}"
              f"(共 {len(rec['scan'])} 集)")


def is_richer_eligible(category, item_date):
    """
    判断项目是否满足"追更全渠道"的条件（与 pick_richer_channels 使用同一套配置）。
    返回 (eligible, year, reason)
    """
    if not RICHER_CHANNEL_SCAN_ENABLED or RICHER_CHANNEL_MAX_EXTRA <= 0:
        return False, None, '更全补抓已关闭'
    if category not in RICHER_CHANNEL_SCAN_CATEGORIES:
        return False, None, f'分类 {category} 不在更全补抓范围'
    year = _parse_release_year(item_date)
    if year is None:
        return False, None, f'项目缺少有效年份信息（date: {item_date}）'
    if year <= RICHER_CHANNEL_MIN_YEAR:
        return False, year, f'年份 {year} <= {RICHER_CHANNEL_MIN_YEAR}'
    return True, year, ''


def pick_richer_channels(completed_recs, selected_recs, ordered_pending_recs,
                         category, item_label, item_date=None,
                         enabled=None, categories=None,
                         min_year=None,
                         min_advantage=None, max_extra=None,
                         verbose=True):
    enabled = RICHER_CHANNEL_SCAN_ENABLED if enabled is None else enabled
    categories = RICHER_CHANNEL_SCAN_CATEGORIES if categories is None else categories
    min_year = RICHER_CHANNEL_MIN_YEAR if min_year is None else min_year
    min_advantage = RICHER_CHANNEL_MIN_ADVANTAGE if min_advantage is None else min_advantage
    max_extra = RICHER_CHANNEL_MAX_EXTRA if max_extra is None else max_extra

    if not enabled or max_extra <= 0:
        return []
    if category not in categories:
        return []

    # 基础池（已映射渠道 + 本轮已选渠道）
    baseline_pool = list(completed_recs) + list(selected_recs)
    if not baseline_pool:
        return []

    base_rec = max(baseline_pool, key=lambda r: r['total'])
    reference = base_rec['total']
    base_desc = _describe_channel(base_rec)

    chosen_ids = {id(r['pl']) for r in baseline_pool}
    candidates = [r for r in ordered_pending_recs if id(r['pl']) not in chosen_ids]

    # 预检：是否有潜在集数更多的渠道
    has_richer_candidate = any((r['total'] - reference) >= max(1, min_advantage) for r in candidates)
    if not has_richer_candidate:
        return []

    # 年份过滤校验：年份必须严格大于 min_year
    year = _parse_release_year(item_date)
    if year is None:
        if verbose:
            print(f"  [更全跳过] {item_label} 发现集数更多的渠道，但项目缺少有效年份信息（date: {item_date}），跳过补抓")
        return []

    if year <= min_year:
        if verbose:
            print(f"  [更全跳过] {item_label} 发现集数更多的渠道，但年份 {year} <= {min_year}，跳过补抓")
        return []

    extras = []
    while len(extras) < max_extra:
        pool = [r for r in candidates if (r['total'] - reference) >= max(1, min_advantage)]
        if not pool:
            break
        best = max(pool, key=lambda r: r['total'])
        extras.append(best)
        candidates.remove(best)

        if verbose:
            print(f"  [更全补抓] {item_label} (年份 {year} > {min_year}) 数量已达标，但发现集数更多的渠道："
                  f"{_describe_channel(best)} > 基准 {base_desc}，"
                  f"为保证最新最全予以补抓")

        reference = best['total']
        base_desc = _describe_channel(best)

    return extras


# ===================== 渠道挑选：旧规则（非锚点分类使用） =====================
def _pick_legacy(completed_recs, ordered_pending_recs, required_count,
                 item_label, category, item_date):
    completed_count = len(completed_recs)
    selected_recs = []
    needed = max(0, required_count - completed_count)

    if needed > 0:
        if completed_count > 0:
            done_names = ', '.join(_describe_channel(r) for r in completed_recs)
            print(f"  [部分已满足] {item_label} 已有 {completed_count} 个完成渠道（{done_names}），"
                  f"还需补齐 {needed} 个完整渠道")

        for rec in ordered_pending_recs:
            if len(selected_recs) >= needed:
                break
            selected_recs.append(rec)
            _log_pick(rec, item_label, f"{completed_count + len(selected_recs)}/{required_count}")

        if (completed_count + len(selected_recs)) < required_count:
            print(f"  [提示] {item_label} 仅能凑齐 {completed_count + len(selected_recs)}/{required_count} 个渠道"
                  f"（已无更多可用渠道）")

    extra_recs = pick_richer_channels(
        completed_recs, selected_recs, ordered_pending_recs,
        category, item_label, item_date=item_date
    )
    for rec in extra_recs:
        _log_pick(rec, item_label, "额外")

    final_recs = selected_recs + extra_recs
    if not final_recs and completed_count >= required_count:
        done_names = ', '.join(_describe_channel(r) for r in completed_recs)
        print(f"  [已达标跳过] {item_label} 已有 {completed_count}/{required_count} 个完整已映射渠道："
              f"{done_names}，且无更全渠道可补（或不满足补抓条件），无需抓取")
    return final_recs


# ===================== 渠道挑选：满集锚点规则 =====================
def _pick_with_anchor(viable_recs, completed_recs, ordered_pending_recs,
                      required_count, item_label, category, item_date):
    richer_ok, year, reason = is_richer_eligible(category, item_date)
    max_completed = max((r['total'] for r in completed_recs), default=None)
    max_viable = max(r['total'] for r in viable_recs)

    # ---- 1. 确定锚点 ----
    anchor = None
    anchor_desc = ''
    if richer_ok and (max_completed is None or
                      (max_viable - max_completed) >= RICHER_CHANNEL_MIN_ADVANTAGE):
        anchor = max_viable
        anchor_desc = f"全部可用渠道最大集数 {anchor} 集（年份 {year} > {RICHER_CHANNEL_MIN_YEAR}，追最新最全）"
    elif max_completed is not None:
        anchor = max_completed
        anchor_desc = f"已完成渠道最大集数 {anchor} 集"
        if (not richer_ok) and category in RICHER_CHANNEL_SCAN_CATEGORIES:
            richer = [r for r in ordered_pending_recs
                      if (r['total'] - anchor) >= RICHER_CHANNEL_MIN_ADVANTAGE]
            if richer:
                print(f"  [更全跳过] {item_label} 发现集数更多的渠道"
                      f"（{', '.join(_describe_channel(r) for r in richer)}），但{reason}，不以其为锚点")

    # ---- 2. 尚无锚点（无完成渠道且不追更全）：按原优先级先抓，完成后自然形成锚点 ----
    if anchor is None:
        selected = ordered_pending_recs[:required_count]
        for i, rec in enumerate(selected, 1):
            _log_pick(rec, item_label, f"{i}/{required_count}")
        if len(selected) < required_count:
            print(f"  [提示] {item_label} 仅能凑齐 {len(selected)}/{required_count} 个渠道（已无更多可用渠道）")
        return selected

    # ---- 3. 按锚点分层 ----
    perfect = [r for r in completed_recs if r['total'] == anchor]
    lower_completed = [r for r in completed_recs if r['total'] != anchor]
    tier_pending = [r for r in ordered_pending_recs if r['total'] == anchor]

    needed = max(0, required_count - len(perfect))
    selected = tier_pending[:needed]

    if needed > 0:
        msg = (f"  [锚点补齐] {item_label} 锚点 = {anchor_desc}；"
               f"已有 {len(perfect)} 个满集完成渠道"
               f"{'（' + ', '.join(_describe_channel(r) for r in perfect) + '）' if perfect else ''}，"
               f"还需 {needed} 个 {anchor} 集完整渠道")
        if lower_completed:
            msg += f"（{', '.join(_describe_channel(r) for r in lower_completed)} 集数不足锚点，暂不计入）"
        print(msg)
        for i, rec in enumerate(selected, 1):
            _log_pick(rec, item_label, f"{len(perfect) + i}/{required_count} 满集")

    got = len(perfect) + len(selected)
    fallback_selected = []

    # ---- 4. 满集渠道已耗尽：降级兜底 ----
    if got < required_count:
        if ANCHOR_TIER_FALLBACK:
            got_with_lower = got + len(lower_completed)
            if lower_completed:
                print(f"  [锚点降级] {item_label} {anchor} 集渠道已无更多可用，"
                      f"计入 {len(lower_completed)} 个集数较少的已完成渠道："
                      f"{', '.join(_describe_channel(r) for r in lower_completed)}")
            still = required_count - got_with_lower
            if still > 0:
                chosen_ids = {id(r['pl']) for r in selected}
                others = [r for r in ordered_pending_recs
                          if r['total'] != anchor and id(r['pl']) not in chosen_ids]
                fallback_selected = others[:still]
                for i, rec in enumerate(fallback_selected, 1):
                    _log_pick(rec, item_label, f"{got_with_lower + i}/{required_count} 降级")
                if got_with_lower + len(fallback_selected) < required_count:
                    print(f"  [提示] {item_label} 仅能凑齐 "
                          f"{got_with_lower + len(fallback_selected)}/{required_count} 个渠道（已无更多可用渠道）")
        else:
            print(f"  [提示] {item_label} 仅能凑齐 {got}/{required_count} 个 {anchor} 集满集渠道"
                  f"（已无更多可用满集渠道，降级兜底已关闭）")

    final_recs = selected + fallback_selected
    if not final_recs:
        done = perfect + (lower_completed if (ANCHOR_TIER_FALLBACK and len(perfect) < required_count) else [])
        print(f"  [已达标跳过] {item_label} 锚点 {anchor} 集，满集完成 {len(perfect)}/{required_count}："
              f"{', '.join(_describe_channel(r) for r in done) or '无'}，无需抓取")
    return final_recs


def pick_playlists_to_scan(playlists, blacklist_url, url_mapping,
                           required_count, item_label, category, show_last_n,
                           full_scan=False,
                           episode_priority_names=None,
                           item_date=None):
    viable_recs = []
    for pl in playlists:
        name = _normalize_channel_name(pl.get('name')) or '未命名渠道'
        if is_channel_blocked(name):
            continue

        episodes_all = pl.get('episodes', {}) or {}

        # 智能提取有效集数（多季合集渠道自动仅提取最新季）
        effective_eps, is_multi_season, season_label = get_channel_effective_episodes(episodes_all, name)

        scan_episodes = get_scan_episodes(
            effective_eps, category, show_last_n, full_scan=full_scan
        )

        if not scan_episodes:
            continue

        if not is_channel_viable(scan_episodes, blacklist_url):
            continue

        viable_recs.append({
            'pl': pl,
            'name': name,
            'total': len(effective_eps),        # 仅以最新季有效集数参与比对
            'raw_total': len(episodes_all),     # 原始多季总集数
            'is_multi_season': is_multi_season,
            'season_label': season_label,
            'scan': scan_episodes,              # 仅扫描最新季
            'truncated': (not full_scan) and category == 'Show' and len(effective_eps) > 10,
        })

    if not viable_recs:
        return []

    completed_recs, pending_recs = [], []
    for rec in viable_recs:
        if is_channel_completed(rec['scan'], url_mapping):
            completed_recs.append(rec)
        else:
            pending_recs.append(rec)

    rec_by_id = {id(r['pl']): r for r in pending_recs}
    ordered_pending_pls = sort_playlists_by_priority(
        [r['pl'] for r in pending_recs],
        episode_priority_names=episode_priority_names
    )
    ordered_pending_recs = [rec_by_id[id(pl)] for pl in ordered_pending_pls]

    if ANCHOR_TIER_ENABLED and category in ANCHOR_TIER_CATEGORIES:
        final_recs = _pick_with_anchor(
            viable_recs, completed_recs, ordered_pending_recs,
            required_count, item_label, category, item_date
        )
    else:
        final_recs = _pick_legacy(
            completed_recs, ordered_pending_recs, required_count,
            item_label, category, item_date
        )

    return [(r['pl'], r['scan']) for r in final_recs]


def should_skip_by_region(item, category,
                          filter_categories=REGION_FILTER_CATEGORIES,
                          blocked_keywords=REGION_BLOCK_KEYWORDS):
    if category not in filter_categories:
        return False

    region = item.get('地区', '')
    if isinstance(region, list):
        region = ''.join(str(x) for x in region)
    region = str(region)

    return any(kw in region for kw in blocked_keywords)


def _parse_rating(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def should_skip_by_rating(item, threshold=RATING_THRESHOLD,
                          rating_fields=RATING_FIELDS):
    # 暂时屏蔽评分过滤
    return False


def atomic_write_json(path, data):
    """原子写入，并保留原文件权限（防止中途中断导致 mapping 损坏）"""
    dir_name = os.path.dirname(path) or '.'
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def emit_current_url(url):
    """复制到剪贴板（Downie 流程需要）+ 写状态文件 + 输出标记行（AppleScript 解析）"""
    pyperclip.copy(url)
    try:
        with open(CURRENT_URL_FILE, 'w', encoding='utf-8') as f:
            f.write(url)
    except OSError as e:
        print(f"[警告] 当前 URL 状态文件写入失败：{e}", file=sys.stderr)
    print(f"CURRENT_URL:{url}")


def main():
    global MOVIE_REQUIRED_CHANNELS, SERIES_REQUIRED_SHORT, SERIES_REQUIRED_LONG
    global BLOCKED_CHANNEL_NAMES, BLOCKED_CHANNEL_KEYWORDS
    global RICHER_CHANNEL_SCAN_ENABLED, RICHER_CHANNEL_MIN_YEAR, RICHER_CHANNEL_MIN_ADVANTAGE, RICHER_CHANNEL_MAX_EXTRA
    global ANCHOR_TIER_ENABLED, ANCHOR_TIER_FALLBACK

    parser = argparse.ArgumentParser(
        description='扫描 OVideos.json 中的视频链接，按渠道优先级与数量要求处理黑名单与 url_mapping。'
    )
    parser.add_argument('--show-last-n', type=int, default=0,
                        help='Show 分类每个渠道只扫末尾 N 条（默认 5；设为 0 则用默认 5）')
    parser.add_argument('--rating-threshold', type=float, default=RATING_THRESHOLD,
                        help=f'评分阈值，豆瓣或 IMDB 任一 >= 此值才处理（默认 {RATING_THRESHOLD}）')
    parser.add_argument('--movie-channels', type=int, default=MOVIE_REQUIRED_CHANNELS,
                        help=f'Movie 分类至少需要的完整渠道数（默认 {MOVIE_REQUIRED_CHANNELS}）')
    parser.add_argument('--series-short-channels', type=int, default=SERIES_REQUIRED_SHORT,
                        help=f'剧集类(<= {EPISODE_THRESHOLD} 集)至少需要的完整渠道数（默认 {SERIES_REQUIRED_SHORT}）')
    parser.add_argument('--series-long-channels', type=int, default=SERIES_REQUIRED_LONG,
                        help=f'剧集类(> {EPISODE_THRESHOLD} 集)至少需要的完整渠道数（默认 {SERIES_REQUIRED_LONG}）')
    parser.add_argument('--skip-channels', default='',
                        help='额外要跳过的渠道名（精确匹配），逗号分隔')
    parser.add_argument('--skip-channel-keywords', default='',
                        help='额外要跳过的渠道名关键字（模糊匹配），逗号分隔')
    parser.add_argument('--no-skip-channels', action='store_true',
                        help='临时清空渠道黑名单（调试用）')
    parser.add_argument('--no-richer-scan', action='store_true',
                        help='关闭"集数更多则补抓"规则（只按数量达标判断，回退到旧行为）')
    parser.add_argument('--richer-min-year', type=int, default=RICHER_CHANNEL_MIN_YEAR,
                        help=f'更全渠道补抓要求的最小年份（必须严格大于该年份，默认 {RICHER_CHANNEL_MIN_YEAR}）')
    parser.add_argument('--richer-min-advantage', type=int, default=RICHER_CHANNEL_MIN_ADVANTAGE,
                        help=f'候选渠道需比基准渠道多出多少集才补抓（默认 {RICHER_CHANNEL_MIN_ADVANTAGE}）')
    parser.add_argument('--richer-max-extra', type=int, default=RICHER_CHANNEL_MAX_EXTRA,
                        help=f'每个项目单轮最多额外补抓几个更全渠道（默认 {RICHER_CHANNEL_MAX_EXTRA}）')
    parser.add_argument('--no-anchor-tier', action='store_true',
                        help='关闭"满集锚点"规则（回退为只按完成渠道数量判断）')
    parser.add_argument('--no-anchor-fallback', action='store_true',
                        help='满集渠道耗尽时不降级计入集数较少的渠道')
    args = parser.parse_args()

    SHOW_LAST_N = args.show_last_n
    rating_threshold = args.rating_threshold

    MOVIE_REQUIRED_CHANNELS = args.movie_channels
    SERIES_REQUIRED_SHORT = args.series_short_channels
    SERIES_REQUIRED_LONG = args.series_long_channels

    RICHER_CHANNEL_SCAN_ENABLED = (not args.no_richer_scan) and RICHER_CHANNEL_SCAN_ENABLED
    RICHER_CHANNEL_MIN_YEAR = args.richer_min_year
    RICHER_CHANNEL_MIN_ADVANTAGE = max(1, args.richer_min_advantage)
    RICHER_CHANNEL_MAX_EXTRA = max(0, args.richer_max_extra)

    ANCHOR_TIER_ENABLED = (not args.no_anchor_tier) and ANCHOR_TIER_ENABLED
    ANCHOR_TIER_FALLBACK = (not args.no_anchor_fallback) and ANCHOR_TIER_FALLBACK

    if args.no_skip_channels:
        BLOCKED_CHANNEL_NAMES = set()
        BLOCKED_CHANNEL_KEYWORDS = tuple()
    else:
        extra_names = {s.strip() for s in args.skip_channels.split(',') if s.strip()}
        extra_kws = tuple(s.strip() for s in args.skip_channel_keywords.split(',') if s.strip())
        BLOCKED_CHANNEL_NAMES = set(BLOCKED_CHANNEL_NAMES) | extra_names
        BLOCKED_CHANNEL_KEYWORDS = tuple(BLOCKED_CHANNEL_KEYWORDS) + extra_kws

    rebuild_blocked_channel_cache()
    sanitize_priority_configs()

    ovideos_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
    mapping_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
    blacklist_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'

    def load_json(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"错误: 找不到文件 {path}", file=sys.stderr)
            sys.exit(2)
        except json.JSONDecodeError:
            print(f"错误: {path} 不是有效的JSON格式", file=sys.stderr)
            sys.exit(2)

    url_mapping = load_json(mapping_path)
    ovideos = load_json(ovideos_path)
    blacklist_url = build_lookup_set(load_json(blacklist_path))

    if BLOCKED_CHANNEL_NAMES or BLOCKED_CHANNEL_KEYWORDS:
        print(f"[渠道黑名单] 精确: {sorted(BLOCKED_CHANNEL_NAMES) or '无'} | "
              f"关键字: {list(BLOCKED_CHANNEL_KEYWORDS) or '无'}（直接跳过，不扫描/不抓取）")
    else:
        print("[渠道黑名单] 未启用")

    print(f"[渠道优先级] {' > '.join(TOP_PRIORITY_CHANNELS)} > 云播线路系列 > "
          f"{' > '.join(CHANNEL_PRIORITY)} > 其它(原顺序)")
    print(f"[集数优先组] {' , '.join(EPISODE_COUNT_PRIORITY_GROUP) or '无'}"
          f"（至少命中 {EPISODE_COUNT_PRIORITY_MIN_HIT} 个才触发）")
    print(f"[Movie 要求] 至少 {MOVIE_REQUIRED_CHANNELS} 个完整渠道")
    print(f"[剧集要求] 集数<= {EPISODE_THRESHOLD}: 至少 {SERIES_REQUIRED_SHORT} 个完整渠道 | "
          f"集数> {EPISODE_THRESHOLD}: 至少 {SERIES_REQUIRED_LONG} 个完整渠道")
    if RICHER_CHANNEL_SCAN_ENABLED and RICHER_CHANNEL_MAX_EXTRA > 0:
        print(f"[更全补抓] 已开启（生效分类：{', '.join(sorted(RICHER_CHANNEL_SCAN_CATEGORIES))}；"
              f"年份需 > {RICHER_CHANNEL_MIN_YEAR}；"
              f"集数需多出 >= {RICHER_CHANNEL_MIN_ADVANTAGE} 集；"
              f"非锚点分类单项目最多额外 {RICHER_CHANNEL_MAX_EXTRA} 个渠道）")
    else:
        print("[更全补抓] 已关闭（仅按渠道数量达标判断）")
    if ANCHOR_TIER_ENABLED:
        print(f"[满集锚点] 已开启（生效分类：{', '.join(sorted(ANCHOR_TIER_CATEGORIES))}；"
              f"仅集数 == 锚点的完整渠道计为完美；降级兜底：{'开' if ANCHOR_TIER_FALLBACK else '关'}）")
    else:
        print("[满集锚点] 已关闭")
    print(f"[Show 裁剪] 每个渠道只扫末尾 {SHOW_LAST_N} 条"
          if SHOW_LAST_N > 0 else "[Show 裁剪] 默认（>10 集时取末尾 5 条）")

    order_desc = "倒序读取" if REVERSE_SCAN else "正序（从上到下）读取"
    limit_desc = (f"每个分类最多读取前 {SCAN_LIMIT_PER_CATEGORY} 个项目"
                  if SCAN_LIMIT_PER_CATEGORY else "读取分类下的所有项目")
    print(f"[读取配置] 顺序：{order_desc} | 数量限制：{limit_desc}")

    for category, items in ovideos.items():
        if category in SKIP_CATEGORIES:
            print(f"[跳过] 根据配置，临时跳过 {category} 分组")
            continue

        items_to_process = list(reversed(items)) if REVERSE_SCAN else list(items)

        if SCAN_LIMIT_PER_CATEGORY and SCAN_LIMIT_PER_CATEGORY > 0:
            items_to_process = items_to_process[:SCAN_LIMIT_PER_CATEGORY]

        for item in items_to_process:
            item_label = f"[{category}] {item.get('name') or item.get('title') or '未命名'}"

            if should_skip_by_rating(item, threshold=rating_threshold):
                continue

            # 【修复】地区过滤原先未被调用，配置形同虚设
            if should_skip_by_region(item, category):
                continue

            playlists = item.get('playlist', []) or []
            if not playlists:
                continue

            total_channels = len(playlists)
            playlists = filter_blocked_playlists(playlists, item_label, verbose=False)
            if not playlists:
                print(f"  [放弃项目] {item_label} 全部 {total_channels} 个渠道均在黑名单中，跳过")
                continue

            episode_count = get_item_episode_count(playlists)
            required_count = get_required_channel_count(category, episode_count)

            item_name = item.get('name') or item.get('title') or ''
            is_full_scan = (category == 'Show' and item_name in SHOW_FULL_SCAN_WHITELIST)

            ep_priority_names = get_episode_count_priority_names(playlists, category)

            # 获取日期字段（优先 date，兼容 release_date 或 year）
            item_date = item.get('date') or item.get('release_date') or item.get('year')

            # ====== 智能挑选需要抓取的渠道 ======
            playlists_to_scan = pick_playlists_to_scan(
                playlists, blacklist_url, url_mapping,
                required_count, item_label, category, SHOW_LAST_N,
                full_scan=is_full_scan,
                episode_priority_names=ep_priority_names,
                item_date=item_date
            )

            if not playlists_to_scan:
                continue

            # ====== 逐个待抓渠道、逐条 url 扫描 ======
            for playlist, scan_episodes in playlists_to_scan:
                for episode_url in scan_episodes:
                    if episode_url in url_mapping:
                        if url_mapping[episode_url] == "":
                            print(f"找到已存在但未填写映射的链接，已复制到剪贴板:\n{episode_url}")
                            emit_current_url(episode_url)
                            return
                        else:
                            continue
                    else:
                        url_mapping[episode_url] = ""
                        atomic_write_json(mapping_path, url_mapping)
                        print(f"发现新链接，已添加到 mapping 文件并复制到剪贴板:\n{episode_url}")
                        emit_current_url(episode_url)
                        return

    print("所有视频链接都已处理完毕，没有发现新的或未填写的链接。")


rebuild_blocked_channel_cache()

if __name__ == "__main__":
    main()