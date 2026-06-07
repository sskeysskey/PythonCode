import json

with open('/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for category, items in data.items():
    print(f"{category}: {len(items)} 个项目")