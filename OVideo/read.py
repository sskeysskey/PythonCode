import json
import argparse
import pyperclip


# 需要执行"地区过滤"的分类集合；以后想加就往里加，例如 {'Drama', 'Show'}
REGION_FILTER_CATEGORIES = {'Drama'}

# 命中任一关键字就跳过该项目
# 只写 '大陆' 可避免误伤 "中国香港" / "中国台湾"；
# 如果想把 "中国"、"中国大陆" 都算上，就加 '中国'
REGION_BLOCK_KEYWORDS = ('大陆', '中国')

# 评分过滤阈值：豆瓣或 IMDB 任一 >= 此值即通过
RATING_THRESHOLD = 6.5
# 参与评分比较的字段（按顺序尝试）
RATING_FIELDS = ('豆瓣', 'IMDB')


def get_scan_episodes(episodes, category, show_last_n):
    """
    根据分类返回"本次实际要扫描的 episodes 列表"。
    - Show: 只取末尾 show_last_n 条（不足则全拿）
    - 其他分类: 原样返回
    """
    if category == 'Show' and show_last_n > 0:
        return episodes[-show_last_n:]
    return episodes


def is_channel_viable(episodes, blacklist_url):
    """
    判断"要扫描的那段 episodes"是否可用:
    - 至少要有一个 episode
    - 所有待扫 episode 都不在黑名单里
    """
    if not episodes:
        return False
    return all(url not in blacklist_url for url in episodes)


def pick_playlists_to_scan(playlists, blacklist_url, only_first_channel,
                           item_label, category, show_last_n):
    """
    按顺序筛选 channel：
    - only_first_channel=True: 返回第一个可用 channel
    - only_first_channel=False: 返回所有可用 channel
    返回列表的每一项是 (playlist, scan_episodes) 元组，
    其中 scan_episodes 是"实际要扫描的 url 列表"。
    """
    viable = []
    for idx, playlist in enumerate(playlists, start=1):
        episodes_all = playlist.get('episodes', [])
        scan_episodes = get_scan_episodes(episodes_all, category, show_last_n)

        if not scan_episodes:
            print(f"  [跳过] {item_label} 第 {idx} 个 channel 为空")
            continue
        if not is_channel_viable(scan_episodes, blacklist_url):
            print(f"  [跳过] {item_label} 第 {idx} 个 channel 的待扫片段含黑名单链接，顺延到下一个")
            continue

        viable.append((playlist, scan_episodes))
        if only_first_channel:
            if category == 'Show':
                print(f"  [采用] {item_label} 第 {idx} 个 channel "
                      f"(Show 末尾 {len(scan_episodes)} 条，原共 {len(episodes_all)} 集)")
            else:
                print(f"  [采用] {item_label} 第 {idx} 个 channel (共 {len(scan_episodes)} 集)")
            break
    return viable


def should_skip_by_region(item, category,
                         filter_categories=REGION_FILTER_CATEGORIES,
                         blocked_keywords=REGION_BLOCK_KEYWORDS):
    """
    只有当 category 在 filter_categories 中时才进行地区过滤。
    命中任一关键字则返回 True（=需要跳过）。
    """
    if category not in filter_categories:
        return False

    region = item.get('地区', '')
    if isinstance(region, list):
        region = ''.join(region)
    region = str(region)

    return any(kw in region for kw in blocked_keywords)


def _parse_rating(value):
    """把评分值解析成 float；空串/None/非法值 -> None"""
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
    """
    豆瓣或 IMDB 任一 >= threshold 即通过（返回 False）；
    全部为空或低于阈值 -> 跳过（返回 True）。
    """
    ratings = item.get('评分', {}) or {}
    for field in rating_fields:
        score = _parse_rating(ratings.get(field))
        if score is not None and score >= threshold:
            return False
    return True


def main():
    # ============ 解析命令行参数 ============
    parser = argparse.ArgumentParser(
        description='扫描 OVideos.json 中的视频链接，处理黑名单与 url_mapping。'
    )
    parser.add_argument(
        '--all-channels',
        action='store_true',
        help='扫描每个项目下所有可用 channel（默认只扫每个项目的第一个可用 channel）'
    )
    parser.add_argument(
        '--show-last-n',
        type=int,
        default=5,
        help='Show 分类每个 channel 只扫末尾 N 条（默认 5；设为 0 则不裁剪）'
    )
    parser.add_argument(
        '--rating-threshold',
        type=float,
        default=RATING_THRESHOLD,
        help=f'评分阈值，豆瓣或 IMDB 任一 >= 此值才处理（默认 {RATING_THRESHOLD}）'
    )
    args = parser.parse_args()
    ONLY_FIRST_CHANNEL = not args.all_channels
    SHOW_LAST_N = args.show_last_n
    rating_threshold = args.rating_threshold

    # 定义文件路径
    ovideos_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
    mapping_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
    blacklist_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'

    # 1. 读取 url_mapping.json 文件
    try:
        with open(mapping_path, 'r', encoding='utf-8') as f:
            url_mapping = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {mapping_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {mapping_path} 不是有效的JSON格式")
        return

    # 2. 读取 OVideos.json 文件
    try:
        with open(ovideos_path, 'r', encoding='utf-8') as f:
            ovideos = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {ovideos_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {ovideos_path} 不是有效的JSON格式")
        return

    # 3. 读取 blacklist_url.json 文件
    try:
        with open(blacklist_path, 'r', encoding='utf-8') as f:
            blacklist_url = json.load(f)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {blacklist_path}")
        return
    except json.JSONDecodeError:
        print(f"错误: {blacklist_path} 不是有效的JSON格式")
        return

    mode_desc = "仅扫描每个项目的第一个可用 channel" if ONLY_FIRST_CHANNEL else "扫描每个项目的所有可用 channel"
    print(f"[模式] {mode_desc}")
    print(f"[Show 裁剪] 每个 channel 只扫末尾 {SHOW_LAST_N} 条"
          if SHOW_LAST_N > 0 else "[Show 裁剪] 关闭（扫全部）")
    print(f"[评分过滤] 豆瓣或 IMDB 任一 >= {rating_threshold} 才处理")

    # 4. 遍历 OVideos.json 提取 episodes 里的 url
    # OVideos.json 的顶层是分类（如 "Movie", "Show"）
    for category, items in ovideos.items():
        for item in items:
            # 用于日志的项目标识
            item_label = f"[{category}] {item.get('name') or item.get('title') or '未命名'}"

            # ====== 地区过滤（仅对配置中的分类生效）======
            if should_skip_by_region(item, category):
                print(f"  [跳过项目] {item_label} 地区为「{item.get('地区')}」，按 {category} 过滤规则跳过")
                continue

            # ====== 评分过滤：豆瓣或 IMDB 任一 >= 阈值才处理 ======
            if should_skip_by_rating(item, threshold=rating_threshold):
                ratings = item.get('评分', {}) or {}
                print(f"  [跳过项目] {item_label} 评分不达标"
                      f"（豆瓣={ratings.get('豆瓣', '')!r}, IMDB={ratings.get('IMDB', '')!r}，阈值={rating_threshold}）")
                continue
            
            # 获取 playlist 列表，如果没有则默认为空列表
            playlists = item.get('playlist', [])

            # 先按规则筛出要扫描的 channel
            playlists_to_scan = pick_playlists_to_scan(
                playlists, blacklist_url, ONLY_FIRST_CHANNEL,
                item_label, category, SHOW_LAST_N
            )

            if not playlists_to_scan:
                print(f"  [放弃项目] {item_label} 所有 channel 均不可用，跳过该项目")
                continue

            for playlist, scan_episodes in playlists_to_scan:
                for episode_url in scan_episodes:
                    # 此时 scan_episodes 已保证无黑名单链接
                    if episode_url in url_mapping:
                        # 如果找到了匹配的（冒号左边存在）
                        if url_mapping[episode_url] == "":
                            # 冒号右边为空，直接停止，将 url 写入剪贴板
                            pyperclip.copy(episode_url)
                            print(f"找到已存在但未填写映射的链接，已复制到剪贴板:\n{episode_url}")
                            return # 结束程序
                        else:
                            # 冒号右边不为空，跳过此链接，继续找下一个
                            continue
                    else:
                        # 如果找不到能匹配的（冒号左边不存在）
                        # 新建一行，冒号右边保持为空
                        url_mapping[episode_url] = ""

                        # 将该 url 写入剪贴板
                        pyperclip.copy(episode_url)

                        # 将更新后的字典写回 url_mapping.json 文件
                        with open(mapping_path, 'w', encoding='utf-8') as f:
                            # indent=4 保证格式化输出，ensure_ascii=False 保证中文字符正常显示（虽然这里全是url）
                            json.dump(url_mapping, f, indent=4, ensure_ascii=False)
                        print(f"发现新链接，已添加到 mapping 文件并复制到剪贴板:\n{episode_url}")
                        return # 结束程序

    # 如果所有循环都执行完毕还没有 return，说明所有链接都已经处理且右边都不为空
    print("所有视频链接都已处理完毕，没有发现新的或未填写的链接。")


if __name__ == "__main__":
    main()