import re
import collections

file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"

def find_duplicate_keys_raw(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # 正则表达式：匹配 JSON 中的 Key (假设 Key 都是双引号包裹的)
    # 这个正则匹配 "key": 这种模式
    keys = re.findall(r'"(https://.*?)"\s*:', content)
    
    # 统计出现次数
    key_counts = collections.Counter(keys)
    
    duplicates = [key for key, count in key_counts.items() if count > 1]
    
    if duplicates:
        print(f"发现重复的 Key: {duplicates}")
    else:
        print("没有发现重复的 Key。")

find_duplicate_keys_raw(file_path)