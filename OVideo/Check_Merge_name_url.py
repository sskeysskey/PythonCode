import json
import os
import copy
from urllib.parse import urlparse

# 定义文件路径
file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
backup_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos_backup.json"

def get_domain(url_str):
    """提取URL的域名"""
    try:
        return urlparse(url_str).netloc
    except Exception:
        return ""

def get_first_playlist_episodes_count(item):
    """获取playlist里第一个渠道里的url数量"""
    try:
        playlist = item.get("playlist", [])
        if playlist and isinstance(playlist, list):
            first_channel = playlist[0]
            episodes = first_channel.get("episodes", {})
            return len(episodes)
    except Exception:
        pass
    return 0

def add_url_to_base(base_item, new_url):
    """
    将新的 url 动态添加到基准项目中。
    寻找当前最大的 urlX，然后递增写入。例如已有 url, url1，则写入 url2。
    """
    url_keys = [k for k in base_item.keys() if k == 'url' or (k.startswith('url') and k[3:].isdigit())]
    
    if not url_keys:
        base_item['url'] = new_url
        return

    max_num = 0
    for key in url_keys:
        if key == 'url':
            continue
        num = int(key[3:])
        if num > max_num:
            max_num = num
    
    next_key = f"url{max_num + 1}"
    
    new_item = {}
    inserted = False
    for k, v in base_item.items():
        new_item[k] = v
        if k == 'url' and max_num == 0:
            new_item[next_key] = new_url
            inserted = True
        elif k == f"url{max_num}":
            new_item[next_key] = new_url
            inserted = True
            
    if not inserted:
        new_item[next_key] = new_url
        
    base_item.clear()
    base_item.update(new_item)

def process_all_items(all_flat_items, is_dry_run=False):
    """
    对所有扁平化后的项目进行扫描与合并。
    is_dry_run=True 时，仅打印日志，用于预览。
    """
    merge_count_type1 = 0
    merge_count_type2 = 0

    i = 0
    while i < len(all_flat_items):
        j = i + 1
        while j < len(all_flat_items):
            item_i = all_flat_items[i]['data']
            item_j = all_flat_items[j]['data']
            
            # --- 步骤 1：处理“同名且 URL 完全相同”的项目 ---
            if item_i['name'] == item_j['name'] and item_i['url'] == item_j['url']:
                count_i = get_first_playlist_episodes_count(item_i)
                count_j = get_first_playlist_episodes_count(item_j)
                
                if is_dry_run:
                    print(f"\n[合并类型1: 同名且 URL 完全相同] 发现重复项目: '{item_i['name']}'")
                    print(f"  -> 项目A [分类:{all_flat_items[i]['category']}] URL: {item_i['url']} | 剧集数: {count_i}")
                    print(f"  -> 项目B [分类:{all_flat_items[j]['category']}] URL: {item_j['url']} | 剧集数: {count_j}")

                if count_i >= count_j:
                    base_flat = all_flat_items[i]
                    merged_flat = all_flat_items[j]
                    if is_dry_run:
                        print(f"  => 动作: 剧集数 A({count_i}) >= B({count_j})。保留项目A，合并并删除项目B。")
                    
                    add_url_to_base(base_flat['data'], merged_flat['data']['url'])
                    all_flat_items.pop(j)
                else:
                    base_flat = all_flat_items[j]
                    merged_flat = all_flat_items[i]
                    if is_dry_run:
                        print(f"  => 动作: 剧集数 B({count_j}) > A({count_i})。保留项目B，合并并删除项目A。")
                    
                    add_url_to_base(base_flat['data'], merged_flat['data']['url'])
                    all_flat_items.pop(i)
                    i -= 1
                    break
                
                merge_count_type1 += 1
                continue

            # --- 步骤 2：处理“同名但 域名不同”的项目 ---
            elif item_i['name'] == item_j['name'] and get_domain(item_i['url']) != get_domain(item_j['url']):
                count_i = get_first_playlist_episodes_count(item_i)
                count_j = get_first_playlist_episodes_count(item_j)
                
                if is_dry_run:
                    print(f"\n[合并类型2: 同名但域名不同的跨域合并] 发现同名项目: '{item_i['name']}'")
                    print(f"  -> 项目A [分类:{all_flat_items[i]['category']}] URL: {item_i['url']} | 剧集数: {count_i}")
                    print(f"  -> 项目B [分类:{all_flat_items[j]['category']}] URL: {item_j['url']} | 剧集数: {count_j}")

                # 默认以剧集数多的作为基准
                if count_i >= count_j:
                    base_flat = all_flat_items[i]
                    merged_flat = all_flat_items[j]
                    remove_idx = j
                    reset_i = False
                    if is_dry_run:
                        print(f"  => 判定: 保留项目A作为基准，合并并删除项目B。")
                else:
                    base_flat = all_flat_items[j]
                    merged_flat = all_flat_items[i]
                    remove_idx = i
                    reset_i = True
                    if is_dry_run:
                        print(f"  => 判定: 保留项目B作为基准，合并并删除项目A。")
                
                # 1. 附加 URL
                add_url_to_base(base_flat['data'], merged_flat['data']['url'])
                
                # 2. 如果被合并的项目是 6vdy，保留其播放列表前置的特殊逻辑
                if "6vdy.org" in merged_flat['data']['url']:
                    v6_playlist = merged_flat['data'].get('playlist', [])
                    base_playlist = base_flat['data'].get('playlist', [])
                    if v6_playlist:
                        if is_dry_run:
                            print(f"  => 动作: 将 6vdy 项目的 {len(v6_playlist)} 个播放列表频道前置到基准项目中。")
                        for channel in reversed(v6_playlist):
                            base_playlist.insert(0, channel)
                
                # 3. 删除被合并项目
                all_flat_items.pop(remove_idx)
                merge_count_type2 += 1

                if reset_i:
                    i -= 1
                    break
            else:
                j += 1
        i += 1
        
    if is_dry_run:
        print(f"\n--- 预览统计 ---")
        print(f"同名且 URL 相同 拟合并次数: {merge_count_type1}")
        print(f"同名但 域名不同 拟合并次数: {merge_count_type2}")
        print(f"----------------\n")

    return all_flat_items, merge_count_type1, merge_count_type2

def main():
    if not os.path.exists(file_path):
        print(f"错误：找不到文件 {file_path}")
        return

    # 读取 JSON
    print("正在读取 JSON 文件...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 1. 扁平化所有分类的数据
    categories = ["Movie", "Drama", "Show", "Anime"]
    all_flat_items = []
    
    for cat in categories:
        if cat in data and isinstance(data[cat], list):
            for item in data[cat]:
                all_flat_items.append({
                    "category": cat,
                    "data": item
                })

    print(f"扁平化完成，共收集到 {len(all_flat_items)} 个项目。")
    print("==================================================")
    print("开始扫描可合并的项目（预览模式）...")
    
    # 2. 使用深拷贝进行预览（Dry Run），不影响原数据
    dry_run_items = copy.deepcopy(all_flat_items)
    _, count1, count2 = process_all_items(dry_run_items, is_dry_run=True)

    if count1 == 0 and count2 == 0:
        print("没有发现需要合并的项目，程序退出。")
        return

    # 3. 等待用户确认
    print("==================================================")
    user_input = input("请仔细核对上方的预览日志。是否确认执行这些合并？(输入 y 确认，其他键取消并退出): ")
    
    if user_input.strip().lower() != 'y':
        print("已取消合并操作，文件未被修改。")
        return

    # 4. 用户确认后，开始真正的合并操作
    print("\n开始正式合并...")
    
    # 备份原文件
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"原文件已备份至: {backup_path}")

    # 正式处理原列表 (is_dry_run=False，不再打印冗长的日志)
    merged_flat_items, _, _ = process_all_items(all_flat_items, is_dry_run=False)

    # 5. 重新分发回对应的分类
    new_data = {cat: [] for cat in categories}
    for flat_item in merged_flat_items:
        cat = flat_item["category"]
        item_data = flat_item["data"]
        new_data[cat].append(item_data)

    print("合并与分发完成，正在写入文件...")

    # 6. 写入新数据
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=4)
    
    print("处理完成！新数据已成功写入原文件。")

if __name__ == "__main__":
    main()