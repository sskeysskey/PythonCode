import json
import argparse
import pyperclip

# SKIP_CATEGORIES = {'Movie', 'Drama'}
SKIP_CATEGORIES = set()

# ===== 新增：读取顺序与数量配置 =====
REVERSE_SCAN = False              # 开关：True 表示每个分类倒着读取，False 表示原样正序读取
SCAN_LIMIT_PER_CATEGORY = 17000       # 数量配置：每个分类最多读取的项目数（例如 5 表示只抓最后5个/最前5个；设为 0 或 None 表示不限制）

# 需要执行"地区过滤"的分类集合；以后想加就往里加，例如 {'Drama', 'Show'}
# 属于模糊匹配，命中任一关键字就跳过该项目
REGION_FILTER_CATEGORIES = {'Drama', "Anime"}
# REGION_BLOCK_KEYWORDS = ('大陆', '中国', '内地')
REGION_BLOCK_KEYWORDS = ('测试')

# 评分过滤阈值：豆瓣或 IMDB 任一 >= 此值即通过
RATING_THRESHOLD = 3.0
# 参与评分比较的字段（按顺序尝试）
RATING_FIELDS = ('豆瓣', 'IMDB')

# ===== 新增：特殊 channel 名称 =====
SPECIAL_CHANNEL_NAME = '6vdy'

def get_scan_episodes(episodes, category, show_last_n):
    """
    根据分类返回"本次实际要扫描的 episodes 列表"。
    - episodes 现在是字典 {"第01集": "url1", ...}，需要先提取出 values 列表。
    - Show: 
      - 如果总集数超过 20：强制只取末尾 5 条（如果 show_last_n 传入了大于0的值，也可以用 show_last_n，这里默认用 5）
      - 如果总集数不超过 20：全部扫描
    - 其他分类: 原样返回所有 values
    """
    if not episodes:
        return []
    
    # 将字典的 values 转换为 URL 列表
    urls_list = list(episodes.values())
    total_count = len(urls_list)

    if category == 'Show':
        if total_count > 20:
            # 如果命令行/配置传入了 show_last_n 且大于 0，则使用传入的值；否则默认截取最后 5 个
            limit = show_last_n if show_last_n > 0 else 5
            return urls_list[-limit:]
        else:
            # 不超过 20 个，全部扫描
            return urls_list
            
    return urls_list


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
        # 兼容新格式：默认获取字典 {}
        episodes_all = playlist.get('episodes', {}) or {}
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
    # --- 新增：暂时屏蔽评分过滤 ---
    return False 

    ratings = item.get('评分', {}) or {}
    for field in rating_fields:
        score = _parse_rating(ratings.get(field))
        if score is not None and score >= threshold:
            return False
    return True


# ============================================================
# 新增：从 playlist 中找出 6vdy 特殊 channel（可能没有）
# ============================================================
def find_special_channel(playlists, name=SPECIAL_CHANNEL_NAME):
    for pl in playlists:
        if pl.get('name') == name:
            return pl
    return None


# ============================================================
# 新增：处理 6vdy 特殊 channel
# 返回值：
#   'exited'   -> 已找到待处理链接，已复制到剪贴板并写文件，调用方必须直接结束程序
#   'done'     -> 6vdy 的所有链接都已在 mapping 中且值非空，可继续处理普通 channel
#   'skip_all' -> 6vdy 自身有问题（比如所有链接都被黑名单挡住、或者 episodes 为空但又必须处理）
# ============================================================
def process_special_6vdy(special_pl, url_mapping, blacklist_url,
                         mapping_path, item_label):
    # 兼容新格式：默认获取字典 {}
    episodes = special_pl.get('episodes', {}) or {}
    if not episodes:
        print(f"  [6vdy] {item_label} 的 6vdy channel episodes 为空，按已完成处理")
        return 'done'

    # 使用 episodes.values() 遍历字典中的 URL
    for episode_url in episodes.values():
        if episode_url in blacklist_url:
            # 6vdy 单条命中黑名单：跳过该条，但继续看下一条
            print(f"  [6vdy 跳过黑名单] {episode_url}")
            continue

        if episode_url in url_mapping:
            if url_mapping[episode_url] == "":
                # 已存在但未填写映射 -> 复制并退出
                pyperclip.copy(episode_url)
                print(f"[6vdy] {item_label} 找到已存在但未填写映射的链接，已复制到剪贴板:\n{episode_url}")
                return 'exited'
            else:
                # 已存在且已填写 -> 继续看下一条
                continue
        else:
            # 新链接 -> 写入 mapping、复制、退出
            url_mapping[episode_url] = ""
            pyperclip.copy(episode_url)
            with open(mapping_path, 'w', encoding='utf-8') as f:
                json.dump(url_mapping, f, indent=4, ensure_ascii=False)
            print(f"[6vdy] {item_label} 发现新链接，已添加到 mapping 文件并复制到剪贴板:\n{episode_url}")
            return 'exited'

    # 全部 episodes 都已在 mapping 中且值非空（或者都被黑名单跳过）
    print(f"  [6vdy 完成] {item_label} 的 6vdy channel 全部链接已就绪，转入普通 channel 流程")
    return 'done'


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
        default=0,
        help='Show 分类每个 channel只扫末尾 N 条（默认 5；设为 0 则不裁剪）'
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
    print(f"[特殊 channel] 名为 '{SPECIAL_CHANNEL_NAME}' 的 channel 将优先全部处理")
    
    # 输出读取顺序和数量配置的提示
    order_desc = "倒序读取" if REVERSE_SCAN else "正序（从上到下）读取"
    limit_desc = f"每个分类最多读取前 {SCAN_LIMIT_PER_CATEGORY} 个项目" if SCAN_LIMIT_PER_CATEGORY else "读取分类下的所有项目"
    print(f"[读取配置] 顺序：{order_desc} | 数量限制：{limit_desc}")

    # 4. 遍历 OVideos.json 提取 episodes 里的 url
    # OVideos.json 的顶层是分类（如 "Movie", "Show"）
    for category, items in ovideos.items():
        # ===== 新增：配置开关逻辑 =====
        if category in SKIP_CATEGORIES:
            print(f"[跳过] 根据配置，临时跳过 {category} 分组")
            continue

        # ============================================================
        # ===== 新增：根据配置处理读取顺序与数量限制 =====
        # ============================================================
        # 1. 处理顺序：如果开启了倒序
        if REVERSE_SCAN:
            items_to_process = list(reversed(items))
        else:
            items_to_process = list(items)

        # 2. 处理数量限制
        if SCAN_LIMIT_PER_CATEGORY and SCAN_LIMIT_PER_CATEGORY > 0:
            items_to_process = items_to_process[:SCAN_LIMIT_PER_CATEGORY]

        for item in items_to_process:
            # 用于日志的项目标识
            item_label = f"[{category}] {item.get('name') or item.get('title') or '未命名'}"

            # ====== 地区过滤（仅对配置中的分类生效）======
            # if should_skip_by_region(item, category):
            #     print(f"  [跳过项目] {item_label} 地区为「{item.get('地区')}」，按 {category} 过滤规则跳过")
            #     continue

            # ====== 评分过滤：豆瓣或 IMDB 任一 >= 阈值才处理 ======
            if should_skip_by_rating(item, threshold=rating_threshold):
                ratings = item.get('评分', {}) or {}
                print(f"  [跳过项目] {item_label} 评分不达标"
                      f"（豆瓣={ratings.get('豆瓣', '')!r}, IMDB={ratings.get('IMDB', '')!r}，阈值={rating_threshold}）")
                continue

            playlists = item.get('playlist', []) or []

            # ============================================================
            # 1) 先优先处理 6vdy 特殊 channel
            # ============================================================
            special_pl = find_special_channel(playlists)
            if special_pl is not None:
                status = process_special_6vdy(
                    special_pl, url_mapping, blacklist_url,
                    mapping_path, item_label
                )
                if status == 'exited':
                    return  # 已处理掉一个链接，结束整个程序

            # ============================================================
            # 2) 6vdy 已就绪（或本来就没有），继续走普通 channel 旧逻辑
            #    注意：要把 6vdy 从普通 channel 列表里剔除
            # ============================================================
            normal_playlists = [pl for pl in playlists
                                if pl.get('name') != SPECIAL_CHANNEL_NAME]

            playlists_to_scan = pick_playlists_to_scan(
                normal_playlists, blacklist_url, ONLY_FIRST_CHANNEL,
                item_label, category, SHOW_LAST_N
            )

            if not playlists_to_scan:
                print(f"  [放弃项目] {item_label} 所有普通 channel 均不可用，跳过该项目")
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