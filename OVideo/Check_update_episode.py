import json
import re
import os

# 定义文件路径
file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"

# 1. 读取 JSON 文件
if not os.path.exists(file_path):
    print(f"错误：文件不存在 {file_path}")
    exit()

with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 正则表达式：匹配 "更新至XX集" 或 "更新至第XX集"
# (\d+) 用于捕获数字，(第)? 用于可选地捕获“第”字
pattern = re.compile(r"更新至(第)?(\d+)集")

# 解析实际集数的辅助函数
def get_actual_episode_count(episodes_dict):
    if not episodes_dict:
        return 0
        
    s_e_pattern = re.compile(r"S(\d+)E(\d+)", re.IGNORECASE)
    
    s_e_matches = []
    ep_numbers = []
    
    for key in episodes_dict.keys():
        # 1. 尝试匹配 S01E01 格式
        s_e_match = s_e_pattern.search(key)
        if s_e_match:
            season = int(s_e_match.group(1))
            episode = int(s_e_match.group(2))
            s_e_matches.append((season, episode))
            continue
            
        # 2. 尝试匹配 "第X集" 或纯数字
        num_match = re.search(r"第(\d+)集", key)
        if num_match:
            ep_numbers.append(int(num_match.group(1)))
        else:
            # 提取键中的所有数字，取最后一个作为集数（如 "HD中字" 会被忽略，"08完结" 提取出 8）
            nums = re.findall(r'\d+', key)
            if nums:
                ep_numbers.append(int(nums[-1]))

    # 如果存在 S..E.. 格式，取最新一季的最大集数
    if s_e_matches:
        max_season = max(s_e_matches, key=lambda x: x[0])[0]
        max_episode = max([ep for s, ep in s_e_matches if s == max_season])
        return max_episode
        
    # 如果存在普通数字格式，取最大值
    if ep_numbers:
        return max(ep_numbers)
        
    # 如果都匹配不到，退回到字典长度
    return len(episodes_dict)

# 存储所有待修改的项目
pending_modifications = []

# 2. 遍历所有分类 (Movie, Drama, Show, Anime)
for category, items in data.items():
    if not isinstance(items, list):
        continue
    
    for item in items:
        name = item.get("name", "未知名称")
        playlist = item.get("playlist", [])
        
        # 3. 检查第一个渠道的 episode 数量是否 >= 3
        if not playlist:
            continue
        
        # 3. 获取第一个渠道的实际集数
        first_channel = playlist[0]
        episodes = first_channel.get("episodes", {})
        
        # 使用新逻辑获取实际集数
        actual_count = get_actual_episode_count(episodes)
        
        if actual_count >= 3:
            info = item.get("info", "")
            match = pattern.search(info)
            
            # 4. 判断 info 是否符合指定的两种写法
            if match:
                has_di = match.group(1)  # 如果有“第”字，这里是“第”，否则是 None
                num_str = match.group(2)  # 匹配到的数字字符串（例如 "02" 或 "28"）
                info_num = int(num_str)   # 转为整数
                
                # 5. 如果实际数量大于 info 中的数量，加入待修改列表
                if actual_count > info_num:
                    # 保持原有的数字位数格式（例如：如果是 "02" 且实际是 5，则更新为 "05"；如果是 "28" 且实际是 30，则更新为 "30"）
                    format_width = len(num_str)
                    new_num_str = f"{actual_count:0{format_width}d}"
                    
                    # 拼接新的 info 字符串
                    di_str = "第" if has_di else ""
                    new_info = pattern.sub(f"更新至{di_str}{new_num_str}集", info)
                    
                    # 把需要修改的信息存起来
                    pending_modifications.append({
                        "item": item,
                        "category": category,
                        "name": name,
                        "old_info": info,
                        "new_info": new_info,
                        "actual_count": actual_count
                    })

# 如果没有需要修改的内容，直接退出
if not pending_modifications:
    print("\n没有需要更新的项目。")
    exit()

# 打印所有待修改项
print(f"\n========== 找到 {len(pending_modifications)} 个需要更新的项目 ==========\n")
for idx, mod in enumerate(pending_modifications, 1):
    print(f"[{idx}] 【{mod['category']}】《{mod['name']}》")
    print(f"   原 info: {mod['old_info']}")
    print(f"   新 info: {mod['new_info']}")
    print(f"   实际集数: {mod['actual_count']}\n")

# 询问是否确认修改
while True:
    choice = input("是否确认修改以上所有项目？(y/n): ").strip().lower()
    if choice in ['y', 'n']:
        break
    print("输入无效，请输入 y 或 n")

# 确认修改才执行
if choice == 'y':
    modified_count = 0
    for mod in pending_modifications:
        mod["item"]["info"] = mod["new_info"]
        modified_count += 1
    
    # 保存文件
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    print(f"\n✅ 修改完成！共更新了 {modified_count} 个项目。")
else:
    print("\n❌ 已取消，未修改任何内容。")
