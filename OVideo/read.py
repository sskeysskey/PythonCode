import json
import argparse
import pyperclip


def is_channel_viable(episodes, blacklist_url):
    """
    判断一个 channel 是否"可用":
    - 至少要有一个 episode
    - 所有 episode 都不在黑名单里（保证 mapping 能成一套完整的）
    """
    if not episodes:
        return False
    return all(url not in blacklist_url for url in episodes)


def pick_playlists_to_scan(playlists, blacklist_url, only_first_channel, item_label):
    """
    按顺序筛选 channel：
    - only_first_channel=True：返回第一个可用 channel（列表形式，可能为空）
    - only_first_channel=False：返回所有可用 channel
    过程中把被跳过的 channel 打印出来，便于排查。
    """
    viable = []
    for idx, playlist in enumerate(playlists, start=1):
        episodes = playlist.get('episodes', [])
        if not episodes:
            print(f"  [跳过] {item_label} 第 {idx} 个 channel 为空")
            continue
        if not is_channel_viable(episodes, blacklist_url):
            print(f"  [跳过] {item_label} 第 {idx} 个 channel 含黑名单链接，顺延到下一个")
            continue

        viable.append(playlist)
        if only_first_channel:
            # 只需要第一个可用的，拿到就停
            print(f"  [采用] {item_label} 第 {idx} 个 channel")
            break
    return viable


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
    args = parser.parse_args()
    ONLY_FIRST_CHANNEL = not args.all_channels

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

    # 4. 遍历 OVideos.json 提取 episodes 里的 url
    # OVideos.json 的顶层是分类（如 "Movie", "Drama"）
    for category, items in ovideos.items():
        for item in items:
            # 获取 playlist 列表，如果没有则默认为空列表
            playlists = item.get('playlist', [])

            # 用于日志的项目标识
            item_label = f"[{category}] {item.get('name') or item.get('title') or '未命名'}"

            # 先按规则筛出要扫描的 channel
            playlists_to_scan = pick_playlists_to_scan(
                playlists, blacklist_url, ONLY_FIRST_CHANNEL, item_label
            )

            if not playlists_to_scan:
                print(f"  [放弃项目] {item_label} 所有 channel 均不可用，跳过该项目")
                continue

            for playlist in playlists_to_scan:
                # 获取 episodes 列表
                episodes = playlist.get('episodes', [])
                for episode_url in episodes:
                    # 注意：到这里的 channel 已经保证没有黑名单链接，
                    # 所以这里不再需要 blacklist 检查。

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