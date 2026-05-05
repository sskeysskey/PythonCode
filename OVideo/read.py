import json
import pyperclip

def main():
    # 定义文件路径
    ovideos_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
    mapping_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'

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

    # 3. 遍历 OVideos.json 提取 episodes 里的 url
    # OVideos.json 的顶层是分类（如 "Movie", "Drama"）
    for category, items in ovideos.items():
        for item in items:
            # 获取 playlist 列表，如果没有则默认为空列表
            playlists = item.get('playlist', [])
            for playlist in playlists:
                # 获取 episodes 列表
                episodes = playlist.get('episodes', [])
                for episode_url in episodes:
                    
                    # 核心逻辑判断
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