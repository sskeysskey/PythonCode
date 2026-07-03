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

# ============================================================
# ===== 渠道优先级配置 =====
# 列表里出现的渠道优先级最高（越靠前越高）；
# 未列出的渠道一律排在它们后面，并保持原 JSON 中的顺序。
# 你新增的 chnland 排第一，6vdy 第二，其它按原序。
# ============================================================
CHANNEL_PRIORITY = ['huxitech', 'chnland', '6vdy']

# ============================================================
# ===== 各分类需要"完整处理"（无黑名单）的渠道数量配置 =====
# ============================================================
# Movie：至少需要这么多个完整渠道（可改）
MOVIE_REQUIRED_CHANNELS = 2

# 剧集类分类
SERIES_CATEGORIES = {'Drama', 'Show', 'Anime'}
EPISODE_THRESHOLD = 20          # 集数阈值
SERIES_REQUIRED_SHORT = 2       # 集数 <= 阈值时，需要的完整渠道数（可改）
SERIES_REQUIRED_LONG = 1        # 集数 > 阈值时，需要的完整渠道数（可改）

# 其它未明确归类的分类，默认需要的完整渠道数
DEFAULT_REQUIRED_CHANNELS = 1


def get_scan_episodes(episodes, category, show_last_n):
    """
    根据分类返回"本次实际要扫描的 url 列表"。
    - episodes 是字典 {"第01集": "url1", ...}，需要先取 values。
    - Show 且集数 > 10：默认只取末尾 5 条（或 show_last_n 指定的条数）。
    - 其他情况：返回全部 url。
    """
    if not episodes:
        return []

    urls_list = list(episodes.values())
    total_count = len(urls_list)

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


def sort_playlists_by_priority(playlists, priority=CHANNEL_PRIORITY):
    """
    按优先级排序渠道：
    - priority 列表里的渠道排前面（越靠前优先级越高）
    - 未列出的渠道排后面，并保持原始顺序
    """
    indexed = list(enumerate(playlists))

    def sort_key(pair):
        original_idx, pl = pair
        name = pl.get('name')
        if name in priority:
            # (0, 优先级序号, 原序号)
            return (0, priority.index(name), original_idx)
        # (1, 0, 原序号) —— 未列出的排后面，保持原顺序
        return (1, 0, original_idx)

    indexed.sort(key=sort_key)
    return [pl for _, pl in indexed]


def pick_playlists_to_scan(playlists, blacklist_url, required_count,
                           item_label, category, show_last_n):
    """
    按优先级顺序收集"完整无黑名单"的渠道，直到凑够 required_count 个，
    或所有渠道都试完为止。
    返回列表，每项为 (playlist, scan_episodes)。
    """
    ordered = sort_playlists_by_priority(playlists)

    viable = []
    for pl in ordered:
        if len(viable) >= required_count:
            break

        name = pl.get('name') or '未命名渠道'
        episodes_all = pl.get('episodes', {}) or {}
        scan_episodes = get_scan_episodes(episodes_all, category, show_last_n)

        if not scan_episodes:
            print(f"  [跳过] {item_label} 渠道「{name}」为空")
            continue

        if not is_channel_viable(scan_episodes, blacklist_url):
            print(f"  [跳过] {item_label} 渠道「{name}」含黑名单链接，顺延到下一个")
            continue

        viable.append((pl, scan_episodes))
        if category == 'Show' and len(episodes_all) > 10:
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
    global MOVIE_REQUIRED_CHANNELS, SERIES_REQUIRED_SHORT
    
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
    args = parser.parse_args()

    SHOW_LAST_N = args.show_last_n
    rating_threshold = args.rating_threshold

    # 命令行可覆盖配置常量
    MOVIE_REQUIRED_CHANNELS = args.movie_channels
    SERIES_REQUIRED_SHORT = args.series_short_channels

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

    print(f"[渠道优先级] {' > '.join(CHANNEL_PRIORITY)} > 其它(原顺序)")
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

            # ====== 计算集数 & 需要的完整渠道数 ======
            episode_count = get_item_episode_count(playlists)
            required_count = get_required_channel_count(category, episode_count)
            print(f"  [项目] {item_label} 集数≈{episode_count}，需要 {required_count} 个完整渠道")

            # ====== 按优先级收集完整渠道 ======
            playlists_to_scan = pick_playlists_to_scan(
                playlists, blacklist_url, required_count,
                item_label, category, SHOW_LAST_N
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


if __name__ == "__main__":
    main()