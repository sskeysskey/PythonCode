import json
import shutil

BLACKLIST_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'

# 先备份
shutil.copy(BLACKLIST_FILE, BLACKLIST_FILE + '.bak')

with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

fixed = 0
for key, value in data.items():
    # 旧格式：[ "ignore/404 自动拉黑", url ]
    if isinstance(value, list) and len(value) == 2 and value[0] == "ignore/404 自动拉黑":
        data[key] = [key, "404 自动拉黑"]
        fixed += 1

with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print(f"已修正 {fixed} 条记录")