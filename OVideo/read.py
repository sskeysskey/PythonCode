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

# ===== 【新增】渠道黑名单（全分类生效：不扫描、不抓取、不计入集数与优先级） =====
# 1) 精确匹配：忽略首尾空格与大小写。例如 'shangxidq' 也能拦住 ' ShangxiDQ '
BLOCKED_CHANNEL_NAMES = set()
# 2) 模糊匹配：渠道名中包含任一关键字即跳过（风格参考 REGION_BLOCK_KEYWORDS）
#    例：想干掉整个「云播线路」系列 -> BLOCKED_CHANNEL_KEYWORDS = ('云播线路',)
BLOCKED_CHANNEL_KEYWORDS = ()

# ===== 渠道优先级配置 =====
# ===== 比「云播线路」系列更高优先级的渠道 =====
# 组内越靠前优先级越高。将来若有：
#   - 比 gdefud 更高的渠道 → 加在 gdefud 前面
#   - 介于 gdefud 与云播线路之间的渠道 → 加在 gdefud 后面
# 整个这一档都排在「云播线路」系列之上。
TOP_PRIORITY_CHANNELS = ['shangxidq', 'gdefud', 'huxitech', 'meiju8', 'cifppc', 'xb6v']

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
EPISODE_COUNT_PRIORITY_GROUP = ('shangxidq', 'gdefud', 'huxitech', 'xb6v', '天堂', '光速', '红牛', '量子')
EPISODE_COUNT_PRIORITY_MIN_HIT = 2      # 至少命中几个渠道才触发该规则

# ===== 各分类需要"完整处理"（无黑名单）的渠道数量配置 =====
# Movie：至少需要这么多个完整渠道（可改 / 可被命令行覆盖）
MOVIE_REQUIRED_CHANNELS = 2

# 剧集类分类
SERIES_CATEGORIES = {'Drama', 'Show', 'Anime'}
EPISODE_THRESHOLD = 20          # 集数阈值
SERIES_REQUIRED_SHORT = 2       # 集数 <= 阈值时，需要的完整渠道数（可改 / 可被命令行覆盖）
SERIES_REQUIRED_LONG = 1        # 集数 > 阈值时，需要的完整渠道数（可改 / 可被命令行覆盖）

# ===== Show 全量抓取白名单 =====
# 只要项目的 name 在这个集合里，Show 分类就【全量抓取】，忽略"末尾5条"的裁剪。
SHOW_FULL_SCAN_WHITELIST = {
    '爱情岛(美国版) 第八季', '罗德岛娇妻', '荒野独居 第一季', '荒野独居 第二季', '荒野独居 第三季', '荒野独居 第四季',
    '荒野独居 第五季', '荒野独居 第六季', '荒野独居 第七季', '荒野独居 第八季', '荒野独居 第九季',
    '荒野独居 第十季', '荒野独居 第十一季', '荒野独居 第十二季', '荒野独居 第十三季'
}

# 其它未明确归类的分类，默认需要的完整渠道数
DEFAULT_REQUIRED_CHANNELS = 1


# ===================== 【新增】渠道黑名单相关工具 =====================
# 预计算的小写集合缓存（避免每个渠道都重复做 lower/strip）
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
    自动净化优先级配置：把已被拉黑的渠道从 TOP_PRIORITY_CHANNELS /
    CHANNEL_PRIORITY / EPISODE_COUNT_PRIORITY_GROUP 中移除，避免配置自相矛盾
    （例如 shangxidq 既在黑名单里、又在最高优先级列表里）。
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
    - full_scan=True 时，无论如何都返回全部（用于 Show 白名单）。
    - Show 且集数 > 10：默认只取末尾 5 条（或 show_last_n 指定的条数）。
    - 其他情况：返回全部 url。
    """
    if not episodes:
        return []

    urls_list = list(episodes.values())
    total_count = len(urls_list)

    # 命中白名单 -> 直接全量，跳过裁剪逻辑
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
    判断"要扫描的那段 episodes"是否完整可用：
    - 至少要有一个 episode
    - 所有待扫 episode 都不在黑名单里（整条渠道都得干净）
    """
    if not scan_episodes:
        return False
    return all(url not in blacklist_url for url in scan_episodes)


def get_item_episode_count(playlists):
    """
    取该项目代表性的集数：所有渠道里最大的集数。
    （同一部剧不同渠道集数通常一致，用 max 兜底更稳妥。）
    注意：传入的 playlists 应已剔除黑名单渠道。
    """
    counts = []
    for pl in playlists:
        eps = pl.get('episodes', {}) or {}
        counts.append(len(eps))
    return max(counts) if counts else 0


def get_required_channel_count(category, episode_count):
    """
    根据分类 + 集数，决定至少需要几个"完整无黑名单"渠道。
    """
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
    """
    判断该项目是否触发"按集数排序"的特殊规则。
    返回:命中的渠道名集合(set);未触发则返回空 set。
    注意:episodes 为空的渠道不算命中；黑名单渠道也不算（调用前已被过滤）。
    """
    if category not in categories:
        return set()

    # 延迟取值：sanitize_priority_configs 可能已修改该全局元组
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
    """
    按优先级排序渠道:
    - 第 0 档: 触发"按集数排序"规则的渠道, 集数多的在前;集数相同则按 top_priority 顺序
    - 第 1 档: TOP_PRIORITY_CHANNELS,组内按列表顺序
    - 第 2 档: 「云播线路」系列,组内按原始 JSON 顺序
    - 第 3 档: priority 列表里的渠道
    - 第 4 档: 未列出的渠道,保持原始顺序
    （黑名单渠道不应出现在这里；若出现则被排到最末尾作为兜底）
    """
    # 延迟取值，确保用到的是 sanitize 之后的配置
    priority = CHANNEL_PRIORITY if priority is None else priority
    top_priority = TOP_PRIORITY_CHANNELS if top_priority is None else top_priority

    episode_priority_names = episode_priority_names or set()
    indexed = list(enumerate(playlists))

    def top_idx(name):
        # 不在 top_priority 里的,排到该档最后
        return top_priority.index(name) if name in top_priority else len(top_priority)

    def sort_key(pair):
        original_idx, pl = pair
        name = _normalize_channel_name(pl.get('name'))

        # 兜底：万一黑名单渠道漏进来，一律沉到最底
        if is_channel_blocked(name):
            return (9, 0, 0, original_idx)

        # 第 0 档:按集数从多到少(负号实现降序),集数相同回落到固定优先级顺序
        if name in episode_priority_names:
            ep_count = len(pl.get('episodes', {}) or {})
            return (0, -ep_count, top_idx(name), original_idx)

        # 第 1 档:比云播线路更高优先级的固定渠道
        if name in top_priority:
            return (1, top_priority.index(name), 0, original_idx)

        # 第 2 档:云播线路系列,组内按原始顺序
        if name.startswith(cloud_prefix):
            return (2, original_idx, 0, 0)

        # 第 3 档:显式列在 priority 里的渠道
        if name in priority:
            return (3, priority.index(name), 0, original_idx)

        # 第 4 档:其它,保持原顺序
        return (4, 0, 0, original_idx)

    indexed.sort(key=sort_key)
    return [pl for _, pl in indexed]


def pick_playlists_to_scan(playlists, blacklist_url, required_count,
                           item_label, category, show_last_n,
                           full_scan=False,
                           episode_priority_names=None):
    """
    按优先级顺序收集"完整无黑名单"的渠道……
    """
    ordered = sort_playlists_by_priority(
        playlists, episode_priority_names=episode_priority_names
    )

    viable = []
    for pl in ordered:
        if len(viable) >= required_count:
            break

        name = _normalize_channel_name(pl.get('name')) or '未命名渠道'

        # 【新增】防御性兜底：渠道黑名单
        if is_channel_blocked(name):
            print(f"  [跳过] {item_label} 渠道「{name}」在渠道黑名单中，不扫描")
            continue

        episodes_all = pl.get('episodes', {}) or {}
        scan_episodes = get_scan_episodes(
            episodes_all, category, show_last_n, full_scan=full_scan
        )

        if not scan_episodes:
            print(f"  [跳过] {item_label} 渠道「{name}」为空")
            continue

        if not is_channel_viable(scan_episodes, blacklist_url):
            print(f"  [跳过] {item_label} 渠道「{name}」含黑名单链接，顺延到下一个")
            continue

        viable.append((pl, scan_episodes))
        # 这里的日志判断也要考虑 full_scan：全量时不该显示"末尾N条"
        if category == 'Show' and len(episodes_all) > 10 and not full_scan:
            print(f"  [采用 {len(viable)}/{required_count}] {item_label} 渠道「{name}」"
                  f"(Show 末尾 {len(scan_episodes)} 条，原共 {len(episodes_all)} 集)")
        else:
            print(f"  [采用 {len(viable)}/{required_count}] {item_label} 渠道「{name}」"
                  f"(共 {len(scan_episodes)} 集)")

    if len(viable) < required_count:
        print(f"  [提示] {item_label} 仅找到 {len(viable)}/{required_count} 个完整渠道"
              f"（已无更多可用渠道）")

    return viable


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
    # 把 SERIES_REQUIRED_LONG 也纳入可被命令行覆盖的全局变量
    global MOVIE_REQUIRED_CHANNELS, SERIES_REQUIRED_SHORT, SERIES_REQUIRED_LONG
    # 【新增】渠道黑名单也支持命令行覆盖
    global BLOCKED_CHANNEL_NAMES, BLOCKED_CHANNEL_KEYWORDS

    # ============ 解析命令行参数 ============
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
    # 【新增】渠道黑名单相关参数
    parser.add_argument(
        '--skip-channels',
        default='',
        help='额外要跳过的渠道名（精确匹配），逗号分隔，例：--skip-channels "暴风,光速"'
    )
    parser.add_argument(
        '--skip-channel-keywords',
        default='',
        help='额外要跳过的渠道名关键字（模糊匹配），逗号分隔，例：--skip-channel-keywords "云播线路"'
    )
    parser.add_argument(
        '--no-skip-channels',
        action='store_true',
        help='临时清空渠道黑名单（调试用）'
    )
    args = parser.parse_args()

    SHOW_LAST_N = args.show_last_n
    rating_threshold = args.rating_threshold

    # 命令行可覆盖配置常量
    MOVIE_REQUIRED_CHANNELS = args.movie_channels
    SERIES_REQUIRED_SHORT = args.series_short_channels
    SERIES_REQUIRED_LONG = args.series_long_channels

    # ====== 【新增】组装渠道黑名单并初始化缓存 ======
    if args.no_skip_channels:
        BLOCKED_CHANNEL_NAMES = set()
        BLOCKED_CHANNEL_KEYWORDS = tuple()
    else:
        extra_names = {s.strip() for s in args.skip_channels.split(',') if s.strip()}
        extra_kws = tuple(s.strip() for s in args.skip_channel_keywords.split(',') if s.strip())
        BLOCKED_CHANNEL_NAMES = set(BLOCKED_CHANNEL_NAMES) | extra_names
        BLOCKED_CHANNEL_KEYWORDS = tuple(BLOCKED_CHANNEL_KEYWORDS) + extra_kws

    rebuild_blocked_channel_cache()
    sanitize_priority_configs()   # 自动剔除优先级配置里与黑名单冲突的渠道

    # 定义文件路径
    ovideos_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
    mapping_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
    blacklist_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'

    # 1. 读取 url_mapping.json
    try:
        with open(mapping_path, 'r', encoding='utf-8') as f:
            url_mapping = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {mapping_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {mapping_path} 不是有效的JSON格式")
        return

    # 2. 读取 OVideos.json
    try:
        with open(ovideos_path, 'r', encoding='utf-8') as f:
            ovideos = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {ovideos_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {ovideos_path} 不是有效的JSON格式")
        return

    # 3. 读取 blacklist_url.json
    try:
        with open(blacklist_path, 'r', encoding='utf-8') as f:
            blacklist_url = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {blacklist_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {blacklist_path} 不是有效的JSON格式")
        return

    # 【新增】黑名单横幅
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
    print(f"[Show 裁剪] 每个渠道只扫末尾 {SHOW_LAST_N} 条"
          if SHOW_LAST_N > 0 else "[Show 裁剪] 默认（>10 集时取末尾 5 条）")
    print(f"[评分过滤] 豆瓣或 IMDB 任一 >= {rating_threshold} 才处理（当前已屏蔽）")

    order_desc = "倒序读取" if REVERSE_SCAN else "正序（从上到下）读取"
    limit_desc = (f"每个分类最多读取前 {SCAN_LIMIT_PER_CATEGORY} 个项目"
                  if SCAN_LIMIT_PER_CATEGORY else "读取分类下的所有项目")
    print(f"[读取配置] 顺序：{order_desc} | 数量限制：{limit_desc}")

    # 4. 遍历 OVideos.json
    for category, items in ovideos.items():
        if category in SKIP_CATEGORIES:
            print(f"[跳过] 根据配置，临时跳过 {category} 分组")
            continue

        # 处理读取顺序
        if REVERSE_SCAN:
            items_to_process = list(reversed(items))
        else:
            items_to_process = list(items)

        # 处理数量限制
        if SCAN_LIMIT_PER_CATEGORY and SCAN_LIMIT_PER_CATEGORY > 0:
            items_to_process = items_to_process[:SCAN_LIMIT_PER_CATEGORY]

        for item in items_to_process:
            item_label = f"[{category}] {item.get('name') or item.get('title') or '未命名'}"

            # ====== 地区过滤（按需开启）======
            # if should_skip_by_region(item, category):
            #     print(f"  [跳过项目] {item_label} 地区为「{item.get('地区')}」，按 {category} 过滤规则跳过")
            #     continue

            # ====== 评分过滤 ======
            if should_skip_by_rating(item, threshold=rating_threshold):
                ratings = item.get('评分', {}) or {}
                print(f"  [跳过项目] {item_label} 评分不达标"
                      f"（豆瓣={ratings.get('豆瓣', '')!r}, IMDB={ratings.get('IMDB', '')!r}，阈值={rating_threshold}）")
                continue

            playlists = item.get('playlist', []) or []
            if not playlists:
                print(f"  [放弃项目] {item_label} 没有任何渠道")
                continue

            # ====== 【新增】渠道黑名单过滤（必须在集数/优先级计算之前） ======
            total_channels = len(playlists)
            playlists = filter_blocked_playlists(playlists, item_label)
            if not playlists:
                print(f"  [放弃项目] {item_label} 全部 {total_channels} 个渠道均在渠道黑名单中，跳过该项目")
                continue

            # ====== 计算集数 & 需要的完整渠道数 ======
            episode_count = get_item_episode_count(playlists)
            required_count = get_required_channel_count(category, episode_count)

            # ====== 判断是否命中 Show 全量白名单 ======
            item_name = item.get('name') or item.get('title') or ''
            is_full_scan = (category == 'Show'
                            and item_name in SHOW_FULL_SCAN_WHITELIST)

            # ====== Drama/Anime/Show:按集数抢占最高优先级 ======
            ep_priority_names = get_episode_count_priority_names(playlists, category)
            if ep_priority_names:
                detail = ', '.join(
                    f"{pl.get('name')}({len(pl.get('episodes', {}) or {})}集)"
                    for pl in sort_playlists_by_priority(
                        playlists, episode_priority_names=ep_priority_names)
                    if _normalize_channel_name(pl.get('name')) in ep_priority_names
                )
                print(f"  [集数优先] {item_label} 命中 {len(ep_priority_names)} 个渠道,"
                      f"改按集数排序:{detail}")

            if is_full_scan:
                print(f"  [项目] {item_label} 集数≈{episode_count}，"
                      f"需要 {required_count} 个完整渠道 [命中白名单→全量抓取]")
            else:
                print(f"  [项目] {item_label} 集数≈{episode_count}，"
                      f"需要 {required_count} 个完整渠道")

            # ====== 按优先级收集完整渠道 ======
            playlists_to_scan = pick_playlists_to_scan(
                playlists, blacklist_url, required_count,
                item_label, category, SHOW_LAST_N,
                full_scan=is_full_scan,
                episode_priority_names=ep_priority_names
            )

            if not playlists_to_scan:
                print(f"  [放弃项目] {item_label} 没有任何完整可用渠道，跳过该项目")
                continue

            # ====== 逐个渠道、逐条 url 扫描 ======
            for playlist, scan_episodes in playlists_to_scan:
                for episode_url in scan_episodes:
                    # scan_episodes 已保证整条渠道无黑名单链接
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


# 模块导入时也先初始化一次缓存，保证单独调用某个函数时行为一致
rebuild_blocked_channel_cache()

if __name__ == "__main__":
    main()