import json
import argparse
import pyperclip

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
# 1) 精确匹配：忽略首尾空格与大小写。例如 'shangxidq' 也能拦住 ' ShangxiDQ '
BLOCKED_CHANNEL_NAMES = set()
# 2) 模糊匹配：渠道名中包含任一关键字即跳过（风格参考 REGION_BLOCK_KEYWORDS）
#    例：想干掉整个「云播线路」系列 -> BLOCKED_CHANNEL_KEYWORDS = ('云播线路',)
BLOCKED_CHANNEL_KEYWORDS = ()

# ===== 渠道优先级配置 =====
# ===== 比「云播线路」系列更高优先级的渠道 =====
TOP_PRIORITY_CHANNELS = ['shangxidq', 'gdefud', 'huxitech', 'meiju8', 'cifppc', 'xb6v', '暴风']

# 「云播线路」系列(云播线路 / 云播线路1 / 云播线路2 ...)整体为第一优先级,
# 组内不排序,按它们在 JSON playlist 里的原始顺序取。
CLOUD_SERIES_PREFIX = '云播线路'

# 云播线路系列之后的优先级(越靠前越高);未列出的渠道再排在这些后面,保持原序。
CHANNEL_PRIORITY = ['chnland']

# ===== Drama / Anime 特殊规则:按集数抢占最高优先级 =====
# 当项目(仅限下列分类)的 playlist 中,同时出现 GROUP 里的渠道 >= MIN_HIT 个时,
# 这些命中的渠道整体升到"第 0 档"(在 mcm 等 TOP_PRIORITY 之上),
# 组内按【集数从多到少】排序;集数相同时,再按 TOP_PRIORITY_CHANNELS 的顺序决定先后。
EPISODE_COUNT_PRIORITY_CATEGORIES = {'Drama', 'Anime', 'Show'}
EPISODE_COUNT_PRIORITY_GROUP = ('shangxidq', 'gdefud', 'huxitech', 'xb6v', '暴风', '天堂', '光速', '红牛', '量子')
EPISODE_COUNT_PRIORITY_MIN_HIT = 2      # 至少命中几个渠道才触发该规则

# ===== 各分类需要"完整处理"（无黑名单）的渠道数量配置 =====
# Movie：至少需要这么多个完整渠道（可改 / 可被命令行覆盖）
MOVIE_REQUIRED_CHANNELS = 2

# 剧集类分类
SERIES_CATEGORIES = {'Drama', 'Show', 'Anime'}
EPISODE_THRESHOLD = 20          # 集数阈值
SERIES_REQUIRED_SHORT = 2       # 集数 <= 阈值时，需要的完整渠道数（可改 / 可被命令行覆盖）
SERIES_REQUIRED_LONG = 1        # 集数 > 阈值时，需要的完整渠道数（可改 / 可被命令行覆盖）

# ===== 【新增】"更全渠道补抓"规则 =====
# 场景：数量上已凑够 required_count 个完整渠道，但还存在集数更多的渠道。
# 为保证资源"最新最全"，即便已达标也要把集数更多的渠道补抓进来。
RICHER_CHANNEL_SCAN_ENABLED = True
# 仅对剧集类生效（Movie 每个渠道恒为 1 集，比较无意义）
RICHER_CHANNEL_SCAN_CATEGORIES = {'Drama', 'Show', 'Anime'}
# 候选渠道集数需要比"基准线"至少多出多少集才触发（>=1；调大可降低噪音）
RICHER_CHANNEL_MIN_ADVANTAGE = 1
# 单个项目单轮最多额外补抓几个"更全渠道"（1 即只追最全的那个，已足够保证最全）
RICHER_CHANNEL_MAX_EXTRA = 1

# ===== Show 全量抓取白名单 =====
SHOW_FULL_SCAN_WHITELIST = {
    '爱情岛(美国版) 第八季', '罗德岛娇妻', '荒野独居 第一季', '荒野独居 第二季', '荒野独居 第三季', '荒野独居 第四季',
    '荒野独居 第五季', '荒野独居 第六季', '荒野独居 第七季', '荒野独居 第八季', '荒野独居 第九季',
    '荒野独居 第十季', '荒野独居 第十一季', '荒野独居 第十二季', '荒野独居 第十三季'
}

# 其它未明确归类的分类，默认需要的完整渠道数
DEFAULT_REQUIRED_CHANNELS = 1


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
    """
    剔除黑名单渠道。必须在"计算集数 / 判定优先级 / 排序 / 扫描"之前调用，
    保证被拉黑的渠道完全不参与后续任何决策。
    """
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
    """
    自动净化优先级配置：把已被拉黑的渠道从优先级列表中移除。
    """
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
# ====================================================================


def get_scan_episodes(episodes, category, show_last_n, full_scan=False):
    """
    根据分类返回"本次实际要扫描的 url 列表"。
    """
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
    """
    判断待扫 episodes 是否可用：非空且整条渠道都无黑名单链接。
    """
    if not scan_episodes:
        return False
    return all(url not in blacklist_url for url in scan_episodes)


def is_channel_completed(scan_episodes, url_mapping):
    """
    判断该渠道的待扫集数是否已经在 url_mapping 中全部完成映射：
    - 至少有 1 集
    - 每一集都在 url_mapping 中
    - 每一集对应的值都不是空字符串（已完成人工/解析映射）
    """
    if not scan_episodes:
        return False
    return all(
        (url in url_mapping and str(url_mapping[url]).strip() != "")
        for url in scan_episodes
    )


def get_item_episode_count(playlists):
    """取该项目代表性的集数（所有未拉黑渠道里的最大集数）。"""
    counts = []
    for pl in playlists:
        eps = pl.get('episodes', {}) or {}
        counts.append(len(eps))
    return max(counts) if counts else 0


def get_required_channel_count(category, episode_count):
    """根据分类 + 集数，决定至少需要几个完整无黑名单渠道。"""
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
    """判断是否触发集数优先规则。"""
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
    """按优先级排序渠道。"""
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
            ep_count = len(pl.get('episodes', {}) or {})
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


# ===================== 【新增】更全渠道补抓工具 =====================
def _describe_channel(rec):
    """统一的渠道描述文本，便于日志输出。"""
    return f"「{rec['name']}」({rec['total']}集)"


def pick_richer_channels(completed_recs, selected_recs, ordered_pending_recs,
                         category, item_label,
                         enabled=None, categories=None,
                         min_advantage=None, max_extra=None,
                         verbose=True):
    """
    【新增】质量兜底：即便渠道"数量"已达标，只要还存在集数更多的可用渠道，
    也把它补抓进来，保证资源最新最全。

    判定基准（reference）：
        已完成渠道 ∪ 本轮已选中渠道 中的【最大完整集数】
    候选条件：
        未被选中的可用渠道，其完整集数 - reference >= min_advantage

    自收敛特性：
        每追加一个候选，reference 就抬升到该候选的集数，
        因此天然只会追到"最全的那一个"；max_extra 作为硬上限兜底。
    并列打平：
        集数相同时，沿用 ordered_pending_recs 已有的优先级顺序（TOP > 云播 > ...）。
    """
    enabled = RICHER_CHANNEL_SCAN_ENABLED if enabled is None else enabled
    categories = RICHER_CHANNEL_SCAN_CATEGORIES if categories is None else categories
    min_advantage = RICHER_CHANNEL_MIN_ADVANTAGE if min_advantage is None else min_advantage
    max_extra = RICHER_CHANNEL_MAX_EXTRA if max_extra is None else max_extra

    if not enabled or max_extra <= 0:
        return []
    if category not in categories:
        return []

    baseline_pool = list(completed_recs) + list(selected_recs)
    if not baseline_pool:
        return []

    # 基准渠道 = 已完成/已选中里集数最多的那个
    base_rec = max(baseline_pool, key=lambda r: r['total'])
    reference = base_rec['total']
    base_desc = _describe_channel(base_rec)

    chosen_ids = {id(r['pl']) for r in baseline_pool}
    candidates = [r for r in ordered_pending_recs if id(r['pl']) not in chosen_ids]

    extras = []
    while len(extras) < max_extra:
        pool = [r for r in candidates if (r['total'] - reference) >= max(1, min_advantage)]
        if not pool:
            break
        # candidates 已按优先级排序，max 返回首个最大值 -> 集数相同按优先级打平
        best = max(pool, key=lambda r: r['total'])
        extras.append(best)
        candidates.remove(best)

        if verbose:
            print(f"  [更全补抓] {item_label} 数量已达标，但发现集数更多的渠道："
                  f"{_describe_channel(best)} > 基准 {base_desc}，"
                  f"为保证最新最全予以补抓")

        # 抬升基准线，保证不会连锁追抓一堆渠道
        reference = best['total']
        base_desc = _describe_channel(best)

    return extras
# ====================================================================


def pick_playlists_to_scan(playlists, blacklist_url, url_mapping,
                           required_count, item_label, category, show_last_n,
                           full_scan=False,
                           episode_priority_names=None):
    """
    渠道挑选器（数量 + 质量双重把关）：
    1. 过滤黑名单渠道 / 含 blacklist_url 的渠道 / 空渠道；
    2. 统计已在 url_mapping 中完整映射好的渠道数；
    3. 数量不足 -> 按优先级补齐差额；
    4. 【新增】无论数量是否达标，只要还存在"集数更多"的可用渠道，
       就额外补抓（pick_richer_channels），保证资源最新最全；
    5. 都不需要则返回空列表。
    """
    # ---------- 1. 收集健康可用渠道 ----------
    viable_recs = []
    for pl in playlists:
        name = _normalize_channel_name(pl.get('name')) or '未命名渠道'
        if is_channel_blocked(name):
            continue

        episodes_all = pl.get('episodes', {}) or {}
        scan_episodes = get_scan_episodes(
            episodes_all, category, show_last_n, full_scan=full_scan
        )

        if not scan_episodes:
            continue

        if not is_channel_viable(scan_episodes, blacklist_url):
            continue

        viable_recs.append({
            'pl': pl,
            'name': name,
            'total': len(episodes_all),      # 完整集数：用于"谁更全"的比较
            'scan': scan_episodes,           # 本轮实际要扫的 url（Show 可能被裁剪）
            'truncated': (not full_scan) and category == 'Show' and len(episodes_all) > 10,
        })

    if not viable_recs:
        return []

    # ---------- 2. 区分"已完整映射"与"待处理" ----------
    completed_recs, pending_recs = [], []
    for rec in viable_recs:
        if is_channel_completed(rec['scan'], url_mapping):
            completed_recs.append(rec)
        else:
            pending_recs.append(rec)

    completed_count = len(completed_recs)

    # 待处理渠道按既有优先级排序（保持与原逻辑一致）
    rec_by_id = {id(r['pl']): r for r in pending_recs}
    ordered_pending_pls = sort_playlists_by_priority(
        [r['pl'] for r in pending_recs],
        episode_priority_names=episode_priority_names
    )
    ordered_pending_recs = [rec_by_id[id(pl)] for pl in ordered_pending_pls]

    # ---------- 3. 数量补齐 ----------
    selected_recs = []
    needed = max(0, required_count - completed_count)

    if needed > 0:
        if completed_count > 0:
            done_names = ', '.join(f"「{r['name']}」" for r in completed_recs)
            print(f"  [部分已满足] {item_label} 已有 {completed_count} 个完成渠道（{done_names}），"
                  f"还需补齐 {needed} 个完整渠道")

        for rec in ordered_pending_recs:
            if len(selected_recs) >= needed:
                break
            selected_recs.append(rec)
            slot_idx = completed_count + len(selected_recs)

            if rec['truncated']:
                print(f"  [采用 {slot_idx}/{required_count}] {item_label} 待抓渠道「{rec['name']}」"
                      f"(Show 末尾 {len(rec['scan'])} 条，原共 {rec['total']} 集)")
            else:
                print(f"  [采用 {slot_idx}/{required_count}] {item_label} 待抓渠道「{rec['name']}」"
                      f"(共 {len(rec['scan'])} 集)")

        if (completed_count + len(selected_recs)) < required_count:
            print(f"  [提示] {item_label} 仅能凑齐 {completed_count + len(selected_recs)}/{required_count} 个渠道"
                  f"（已无更多可用渠道）")

    # ---------- 4. 质量兜底：补抓集数更多的渠道 ----------
    extra_recs = pick_richer_channels(
        completed_recs, selected_recs, ordered_pending_recs,
        category, item_label
    )

    for rec in extra_recs:
        if rec['truncated']:
            print(f"  [采用 额外] {item_label} 待抓渠道「{rec['name']}」"
                  f"(Show 末尾 {len(rec['scan'])} 条，原共 {rec['total']} 集)")
        else:
            print(f"  [采用 额外] {item_label} 待抓渠道「{rec['name']}」"
                  f"(共 {len(rec['scan'])} 集)")

    final_recs = selected_recs + extra_recs

    # ---------- 5. 真正无事可做 ----------
    if not final_recs:
        if completed_count >= required_count:
            done_names = ', '.join(_describe_channel(r) for r in completed_recs)
            print(f"  [已达标跳过] {item_label} 已有 {completed_count}/{required_count} 个完整已映射渠道："
                  f"{done_names}，且无更全渠道可补，无需抓取")
        return []

    return [(r['pl'], r['scan']) for r in final_recs]


def should_skip_by_region(item, category,
                          filter_categories=REGION_FILTER_CATEGORIES,
                          blocked_keywords=REGION_BLOCK_KEYWORDS):
    if category not in filter_categories:
        return False

    region = item.get('地区', '')
    if isinstance(region, list):
        region = ''.join(region)
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
    # --- 暂时屏蔽评分过滤 ---
    return False

    ratings = item.get('评分', {}) or {}
    for field in rating_fields:
        score = _parse_rating(ratings.get(field))
        if score is not None and score >= threshold:
            return False
    return True


def main():
    global MOVIE_REQUIRED_CHANNELS, SERIES_REQUIRED_SHORT, SERIES_REQUIRED_LONG
    global BLOCKED_CHANNEL_NAMES, BLOCKED_CHANNEL_KEYWORDS
    global RICHER_CHANNEL_SCAN_ENABLED, RICHER_CHANNEL_MIN_ADVANTAGE, RICHER_CHANNEL_MAX_EXTRA

    parser = argparse.ArgumentParser(
        description='扫描 OVideos.json 中的视频链接，按渠道优先级与数量要求处理黑名单与 url_mapping。'
    )
    parser.add_argument(
        '--show-last-n',
        type=int,
        default=0,
        help='Show 分类每个渠道只扫末尾 N 条（默认 5；设为 0 则用默认 5）'
    )
    parser.add_argument(
        '--rating-threshold',
        type=float,
        default=RATING_THRESHOLD,
        help=f'评分阈值，豆瓣或 IMDB 任一 >= 此值才处理（默认 {RATING_THRESHOLD}）'
    )
    parser.add_argument(
        '--movie-channels',
        type=int,
        default=MOVIE_REQUIRED_CHANNELS,
        help=f'Movie 分类至少需要的完整渠道数（默认 {MOVIE_REQUIRED_CHANNELS}）'
    )
    parser.add_argument(
        '--series-short-channels',
        type=int,
        default=SERIES_REQUIRED_SHORT,
        help=f'剧集类(<= {EPISODE_THRESHOLD} 集)至少需要的完整渠道数（默认 {SERIES_REQUIRED_SHORT}）'
    )
    parser.add_argument(
        '--series-long-channels',
        type=int,
        default=SERIES_REQUIRED_LONG,
        help=f'剧集类(> {EPISODE_THRESHOLD} 集)至少需要的完整渠道数（默认 {SERIES_REQUIRED_LONG}）'
    )
    parser.add_argument(
        '--skip-channels',
        default='',
        help='额外要跳过的渠道名（精确匹配），逗号分隔'
    )
    parser.add_argument(
        '--skip-channel-keywords',
        default='',
        help='额外要跳过的渠道名关键字（模糊匹配），逗号分隔'
    )
    parser.add_argument(
        '--no-skip-channels',
        action='store_true',
        help='临时清空渠道黑名单（调试用）'
    )
    # ===== 【新增】更全渠道补抓相关开关 =====
    parser.add_argument(
        '--no-richer-scan',
        action='store_true',
        help='关闭"集数更多则补抓"规则（只按数量达标判断，回退到旧行为）'
    )
    parser.add_argument(
        '--richer-min-advantage',
        type=int,
        default=RICHER_CHANNEL_MIN_ADVANTAGE,
        help=f'候选渠道需比基准渠道多出多少集才补抓（默认 {RICHER_CHANNEL_MIN_ADVANTAGE}）'
    )
    parser.add_argument(
        '--richer-max-extra',
        type=int,
        default=RICHER_CHANNEL_MAX_EXTRA,
        help=f'每个项目单轮最多额外补抓几个更全渠道（默认 {RICHER_CHANNEL_MAX_EXTRA}）'
    )
    args = parser.parse_args()

    SHOW_LAST_N = args.show_last_n
    rating_threshold = args.rating_threshold

    MOVIE_REQUIRED_CHANNELS = args.movie_channels
    SERIES_REQUIRED_SHORT = args.series_short_channels
    SERIES_REQUIRED_LONG = args.series_long_channels

    RICHER_CHANNEL_SCAN_ENABLED = (not args.no_richer_scan) and RICHER_CHANNEL_SCAN_ENABLED
    RICHER_CHANNEL_MIN_ADVANTAGE = max(1, args.richer_min_advantage)
    RICHER_CHANNEL_MAX_EXTRA = max(0, args.richer_max_extra)

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

    try:
        with open(mapping_path, 'r', encoding='utf-8') as f:
            url_mapping = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {mapping_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {mapping_path} 不是有效的JSON格式")
        return

    try:
        with open(ovideos_path, 'r', encoding='utf-8') as f:
            ovideos = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {ovideos_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {ovideos_path} 不是有效的JSON格式")
        return

    try:
        with open(blacklist_path, 'r', encoding='utf-8') as f:
            blacklist_url = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {blacklist_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {blacklist_path} 不是有效的JSON格式")
        return

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
              f"集数需多出 >= {RICHER_CHANNEL_MIN_ADVANTAGE} 集；"
              f"单项目最多额外 {RICHER_CHANNEL_MAX_EXTRA} 个渠道）")
    else:
        print("[更全补抓] 已关闭（仅按渠道数量达标判断）")
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

        if REVERSE_SCAN:
            items_to_process = list(reversed(items))
        else:
            items_to_process = list(items)

        if SCAN_LIMIT_PER_CATEGORY and SCAN_LIMIT_PER_CATEGORY > 0:
            items_to_process = items_to_process[:SCAN_LIMIT_PER_CATEGORY]

        for item in items_to_process:
            item_label = f"[{category}] {item.get('name') or item.get('title') or '未命名'}"

            if should_skip_by_rating(item, threshold=rating_threshold):
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

            # ====== 智能挑选需要抓取的渠道（数量达标 + 更全补抓 双重判断） ======
            playlists_to_scan = pick_playlists_to_scan(
                playlists, blacklist_url, url_mapping,
                required_count, item_label, category, SHOW_LAST_N,
                full_scan=is_full_scan,
                episode_priority_names=ep_priority_names
            )

            if not playlists_to_scan:
                # 包含：已达标且无更全渠道 / 无任何可用健康渠道，直接处理下一个条目
                continue

            # ====== 逐个待抓渠道、逐条 url 扫描 ======
            for playlist, scan_episodes in playlists_to_scan:
                for episode_url in scan_episodes:
                    if episode_url in url_mapping:
                        if url_mapping[episode_url] == "":
                            pyperclip.copy(episode_url)
                            print(f"找到已存在但未填写映射的链接，已复制到剪贴板:\n{episode_url}")
                            return
                        else:
                            continue
                    else:
                        url_mapping[episode_url] = ""
                        pyperclip.copy(episode_url)
                        with open(mapping_path, 'w', encoding='utf-8') as f:
                            json.dump(url_mapping, f, indent=4, ensure_ascii=False)
                        print(f"发现新链接，已添加到 mapping 文件并复制到剪贴板:\n{episode_url}")
                        return

    print("所有视频链接都已处理完毕，没有发现新的或未填写的链接。")


rebuild_blocked_channel_cache()

if __name__ == "__main__":
    main()