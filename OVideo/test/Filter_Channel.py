import json

# 假设 json_data 是你的 JSON 字符串或已解析的字典
def find_only_shangxidq_items(data):
    # 如果传入的是字符串，先解析成字典
    if isinstance(data, str):
        data = json.loads(data)
    
    target_channel = "shangxidq"
    matched_items = []

    # 遍历外层的各个分类 (Movie, Drama, Show, Anime 等)
    for category, items in data.items():
        if not isinstance(items, list):
            continue
            
        for item in items:
            playlist = item.get("playlist", [])
            if not playlist:
                continue
            
            # 获取当前条目所有的渠道名称（使用 set 去重）
            channels = {p.get("name") for p in playlist if "name" in p}
            
            # 核心条件：渠道集合完全等于 {"shangxidq"}
            if channels == {target_channel}:
                matched_items.append({
                    "category": category,
                    "name": item.get("name"),
                    "item": item
                })
                
    return matched_items

# 示例调用
if __name__ == "__main__":
    # 读取 json 文件或直接传入数据
    with open("/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        
    results = find_only_shangxidq_items(data)
    
    print(f"共找到 {len(results)} 个符合条件的项目：")
    for r in results:
        print(f"[{r['category']}] {r['name']}")