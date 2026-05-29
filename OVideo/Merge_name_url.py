import json
import os
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
    # 找出当前已有的所有以 url 开头的键
    url_keys = [k for k in base_item.keys() if k == 'url' or (k.startswith('url') and k[3:].isdigit())]
    
    if not url_keys:
        base_item['url'] = new_url
        return

    # 确定下一个序号
    max_num = 0
    for key in url_keys:
        if key == 'url':
            continue
        num = int(key[3:])
        if num > max_num:
            max_num = num
    
    next_key = f"url{max_num + 1}"
    
    # 为了保证顺序（让 url1, url2 挨着 url 存放），我们重建字典
    new_item = {}
    inserted = False
    for k, v in base_item.items():
        new_item[k] = v
        # 在原有的最后一个 url 键后面插入新的 urlX
        if k == 'url' and max_num == 0:
            new_item[next_key] = new_url
            inserted = True
        elif k == f"url{max_num}":
            new_item[next_key] = new_url
            inserted = True
            
    if not inserted:
        new_item[next_key] = new_url
        
    # 更新原字典
    base_item.clear()
    base_item.update(new_item)

def process_all_items(all_flat_items):
    """对所有扁平化后的项目（包含跨分组项目）进行统一合并"""
    
    # --- 步骤 1：处理“同名且同域名”的项目 ---
    i = 0
    while i < len(all_flat_items):
        j = i + 1
        while j < len(all_flat_items):
            item_i = all_flat_items[i]['data']
            item_j = all_flat_items[j]['data']
            
            # 判断同名且同域名
            if item_i['name'] == item_j['name'] and get_domain(item_i['url']) == get_domain(item_j['url']):
                count_i = get_first_playlist_episodes_count(item_i)
                count_j = get_first_playlist_episodes_count(item_j)
                
                # 确定基准项目和被合并项目
                if count_i >= count_j:
                    base_flat = all_flat_items[i]
                    merged_flat = all_flat_items[j]
                    # 保持 i 不变，删除 j
                    add_url_to_base(base_flat['data'], merged_flat['data']['url'])
                    all_flat_items.pop(j)
                else:
                    base_flat = all_flat_items[j]
                    merged_flat = all_flat_items[i]
                    add_url_to_base(base_flat['data'], merged_flat['data']['url'])
                    # 因为 i 被删除了，i 处的元素变成了原来的 i+1，所以 i 不需要自增，直接跳出内循环重新匹配
                    all_flat_items.pop(i)
                    i -= 1
                    break
            else:
                j += 1
        i += 1

    # --- 步骤 2：处理“同名但不同域名”的项目（包含 6vdy.org） ---
    i = 0
    while i < len(all_flat_items):
        j = i + 1
        while j < len(all_flat_items):
            item_i = all_flat_items[i]['data']
            item_j = all_flat_items[j]['data']
            
            if item_i['name'] == item_j['name'] and get_domain(item_i['url']) != get_domain(item_j['url']):
                url_i = item_i['url']
                url_j = item_j['url']
                
                is_i_6v = "6vdy.org" in url_i
                is_j_6v = "6vdy.org" in url_j
                
                # 只有当其中一个是 6vdy，另一个不是时才合并
                if (is_i_6v or is_j_6v) and not (is_i_6v and is_j_6v):
                    if is_j_6v:
                        base_flat = all_flat_items[i]
                        v6_flat = all_flat_items[j]
                        remove_idx = j
                        reset_i = False
                    else:
                        base_flat = all_flat_items[j]
                        v6_flat = all_flat_items[i]
                        remove_idx = i
                        reset_i = True
                    
                    # 1. 将 6vdy 的 url 移过去
                    add_url_to_base(base_flat['data'], v6_flat['data']['url'])
                    
                    # 2. 将 6vdy 的 playlist 挪到 base_item playlist 的第一位
                    v6_playlist = v6_flat['data'].get('playlist', [])
                    base_playlist = base_flat['data'].get('playlist', [])
                    if v6_playlist:
                        for channel in reversed(v6_playlist):
                            base_playlist.insert(0, channel)
                    
                    # 3. 删除 6vdy 项目
                    all_flat_items.pop(remove_idx)
                    
                    if reset_i:
                        i -= 1
                        break
                else:
                    j += 1
            else:
                j += 1
        i += 1
        
    return all_flat_items

def main():
    if not os.path.exists(file_path):
        print(f"错误：找不到文件 {file_path}")
        return

    # 读取 JSON
    print("正在读取 JSON 文件...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 备份原文件以防万一
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"原文件已备份至: {backup_path}")

    # 1. 扁平化所有分类的数据，并记录它们原本属于哪个分类
    categories = ["Movie", "Drama", "Show", "Anime"]
    all_flat_items = []
    
    for cat in categories:
        if cat in data and isinstance(data[cat], list):
            for item in data[cat]:
                all_flat_items.append({
                    "category": cat,  # 记录原始分类
                    "data": item
                })

    print(f"扁平化完成，共收集到 {len(all_flat_items)} 个项目。开始跨分组扫描与合并...")

    # 2. 统一进行合并处理
    merged_flat_items = process_all_items(all_flat_items)

    # 3. 重新分发回对应的分类
    # 初始化一个空的分类字典
    new_data = {cat: [] for cat in categories}
    
    for flat_item in merged_flat_items:
        cat = flat_item["category"]
        item_data = flat_item["data"]
        new_data[cat].append(item_data)

    print("合并与分发完成，正在写入文件...")

    # 4. 写入新数据
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=4)
    
    print("处理完成！跨分组重复项已成功合并，新数据已写入原文件。")

if __name__ == "__main__":
    main()