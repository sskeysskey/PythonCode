import sys
import json
import os
import subprocess

# 你的 JSON 文件路径
JSON_PATH = "/Users/yanzhang/Coding/LocalServer/Resources/Prediction/pending_translations.json"
# 临时目录用于存放分割好的内容和对应关系
TMP_DIR = "/tmp/doubao_chunks"

def get_clipboard():
    """获取 macOS 剪贴板内容"""
    p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
    data, _ = p.communicate()
    return data.decode('utf-8')

def split_json():
    """读取 JSON，提取第一组引号的内容并按要求平均分割"""
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    items = []
    # 提取所有需要翻译的 key（第一组引号）
    for category in ["names", "options", "types", "subtypes"]:
        if category in data:
            for key in data[category].keys():
                items.append((category, key))

    n = len(items)
    if n == 0:
        print("0")
        return

    # 平分算法，单份不超过 200 行
    max_size = 200
    num_chunks = (n + max_size - 1) // max_size
    base_size = n // num_chunks
    remainder = n % num_chunks

    os.makedirs(TMP_DIR, exist_ok=True)
    
    # 清理历史缓存
    for f in os.listdir(TMP_DIR):
        os.remove(os.path.join(TMP_DIR, f))

    start = 0
    chunk_files = 0
    for i in range(num_chunks):
        # 将余数均匀分配到前面的块中 (比如 500/3 -> 167, 167, 166)
        size = base_size + (1 if i < remainder else 0)
        chunk_items = items[start:start+size]
        start += size

        # 写入需要发送给豆包的纯文本
        keys_text = "\n".join([item[1] for item in chunk_items])
        with open(f"{TMP_DIR}/chunk_{i}.txt", 'w', encoding='utf-8') as f:
            f.write(keys_text)

        # 保存元数据以便回写时一对一匹配
        with open(f"{TMP_DIR}/meta_{i}.json", 'w', encoding='utf-8') as f:
            json.dump(chunk_items, f, ensure_ascii=False)

        chunk_files += 1

    # 返回 chunk 总数给 AppleScript
    print(chunk_files)

def validate_and_merge(chunk_index):
    """验证剪贴板并在通过后回写进第二组引号"""
    with open(f"{TMP_DIR}/meta_{chunk_index}.json", 'r', encoding='utf-8') as f:
        chunk_items = json.load(f)

    translated_text = get_clipboard().strip()
    # 过滤掉豆包可能产生的多余空行
    translated_lines = [line.strip() for line in translated_text.split('\n') if line.strip()]

    # 1. 验证行数是否一对一
    if len(translated_lines) != len(chunk_items):
        print(f"FAIL: 行数不匹配。发出 {len(chunk_items)} 行，收到 {len(translated_lines)} 行。")
        return

    # 2. 验证是否包含合理的中文内容 (防止复制到了错误文本或豆包罢工)
    chinese_chars = sum(1 for c in translated_text if '\u4e00' <= c <= '\u9fff')
    if chinese_chars < (len(chunk_items) * 0.5): 
        print("FAIL: 内容似乎没有翻译成中文。")
        return

    # 3. 验证通过，写入原始 JSON 对应的第二组引号中
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for i, (category, key) in enumerate(chunk_items):
        # 将翻译后的内容写入对应的 key 中
        data[category][key] = translated_lines[i]

    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 返回 OK 告知 AppleScript 继续下一组
    print("OK")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
        
    action = sys.argv[1]
    if action == "split":
        split_json()
    elif action == "validate":
        validate_and_merge(sys.argv[2])
