import json
import os

# 定义文件路径
input_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
mapping_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"
output_path = "/Users/yanzhang/Downloads/a.json"


def get_float_score(score_str):
    """安全地将评分字符串转换为浮点数，若为空或无法转换则返回 0.0"""
    if not score_str:
        return 0.0
    try:
        return float(score_str)
    except ValueError:
        return 0.0


def filter_and_remove_videos():
    # 1. 读取原始视频数据 OVideos.json
    if not os.path.exists(input_path):
        print(f"错误：找不到输入文件 {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. 读取 url_mapping.json 并提取所有的 Key
    mapping_keys = set()
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping_data = json.load(f)
            # 将所有 key 存入 set 中，提高后续查询效率
            mapping_keys = set(mapping_data.keys())
    else:
        print(f"警告：未找到映射文件 {mapping_path}，将不执行 URL 匹配豁免。")

    # 初始化用于保存“被筛选（删除）出来”的数据结构
    filtered_out_data = {"Movie": [], "Drama": [], "Show": [], "Anime": []}

    # 需要处理的分类
    target_categories = ["Drama", "Show", "Anime"]

    # 3. 遍历并分流数据
    for category in target_categories:
        if category in data:
            keep_list = []  # 用于存放保留在原文件中的项目
            
            for item in data[category]:
                # 获取评分字典
                ratings = item.get("评分", {})

                # 提取评分并转换为浮点数
                douban_score = get_float_score(ratings.get("豆瓣", ""))
                imdb_score = get_float_score(ratings.get("IMDB", ""))

                # 取两者中分数高的
                max_score = max(douban_score, imdb_score)

                # 判断是否低于 6.5 分
                if max_score < 6.5:
                    # 【新增保护逻辑】：检查 playlist 里的任何 episode url 是否在 mapping_keys 中
                    has_mapped_url = False
                    playlists = item.get("playlist", [])
                    
                    for playlist in playlists:
                        episodes = playlist.get("episodes", {})
                        for ep_name, ep_url in episodes.items():
                            if ep_url in mapping_keys:
                                has_mapped_url = True
                                break  # 只要找到一个匹配，就可以跳出当前项目的 episode 循环
                        if has_mapped_url:
                            break  # 跳出 playlist 循环

                    if has_mapped_url:
                        # 触发豁免：即使低于 6.5 分，但有播放链接在 mapping 中，予以保留
                        keep_list.append(item)
                    else:
                        # 未触发豁免：低于 6.5 分且无匹配，移出并放入 a.json
                        filtered_out_data[category].append(item)
                else:
                    # 大于等于 6.5 分，直接保留在原数据中
                    keep_list.append(item)
            
            # 更新原数据字典中该分类的列表
            data[category] = keep_list

    # 4. 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 5. 将低分筛选数据保存至 a.json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(filtered_out_data, f, ensure_ascii=False, indent=4)
    print(f"已成功将低于 6.5 分且未被豁免的项目筛选并保存至：{output_path}")

    # 6. 将更新后的数据（已移除低分且未豁免的项目）写回原 OVideos.json 文件
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"已成功更新原文件（已保留豁免项目）：{input_path}")


if __name__ == "__main__":
    filter_and_remove_videos()