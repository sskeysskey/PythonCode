import sys
import json
import os
import re
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
    """读取 JSON，提取需要翻译的内容，以 JSON 格式分块输出"""
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

    # 平分算法，单份不超过 200 条
    max_size = 200
    num_chunks = (n + max_size - 1) // max_size
    base_size = n // num_chunks
    remainder = n % num_chunks

    os.makedirs(TMP_DIR, exist_ok=True)

    # 清理历史缓存
    for f_name in os.listdir(TMP_DIR):
        os.remove(os.path.join(TMP_DIR, f_name))

    start = 0
    chunk_files = 0
    for i in range(num_chunks):
        # 将余数均匀分配到前面的块中 (比如 500/3 -> 167, 167, 166)
        size = base_size + (1 if i < remainder else 0)
        chunk_items = items[start:start + size]
        start += size

        # 构建带分类结构的 JSON（与 pending_translations.json 结构一致）
        chunk_dict = {}
        for category, key in chunk_items:
            if category not in chunk_dict:
                chunk_dict[category] = {}
            chunk_dict[category][key] = ""

        with open(f"{TMP_DIR}/chunk_{i}.txt", 'w', encoding='utf-8') as f:
            json.dump(chunk_dict, f, ensure_ascii=False, indent=2)

        # 保存元数据以便回写时一对一匹配
        with open(f"{TMP_DIR}/meta_{i}.json", 'w', encoding='utf-8') as f:
            json.dump(chunk_items, f, ensure_ascii=False)

        chunk_files += 1

    # 返回 chunk 总数给 AppleScript
    print(chunk_files)


def strip_markdown_fences(text):
    """去除 Doubao 可能包裹的 markdown 代码块标记"""
    text = text.strip()
    # 去掉开头的 ```json 或 ```
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    # 去掉结尾的 ```
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def validate_and_merge(chunk_index):
    """验证剪贴板中的 JSON 翻译结果并回写到 pending_translations.json"""
    with open(f"{TMP_DIR}/meta_{chunk_index}.json", 'r', encoding='utf-8') as f:
        chunk_items = json.load(f)

    clipboard_text = get_clipboard().strip()
    clipboard_text = strip_markdown_fences(clipboard_text)

    # 1. 尝试解析 JSON
    try:
        translated_dict = json.loads(clipboard_text)
    except json.JSONDecodeError as e:
        print(f"FAIL: 返回内容不是合法的JSON格式。错误: {e}")
        return

    if not isinstance(translated_dict, dict):
        print("FAIL: 返回的JSON不是字典格式。")
        return

    # 2. 逐条验证每个 (category, key) 都有对应的非空翻译
    missing_keys = []
    empty_values = []
    all_translations = []

    for category, key in chunk_items:
        if category not in translated_dict:
            missing_keys.append(f"{category}/{key}")
            continue
        if key not in translated_dict[category]:
            missing_keys.append(f"{category}/{key}")
            continue
        val = translated_dict[category].get(key, "")
        if not val or not str(val).strip():
            empty_values.append(f"{category}/{key}")
            continue
        all_translations.append(str(val).strip())

    if missing_keys:
        print(f"FAIL: 缺少 {len(missing_keys)} 个key。首个缺失: {missing_keys[0]}")
        return

    if empty_values:
        print(f"FAIL: {len(empty_values)} 个翻译值为空。首个为空: {empty_values[0]}")
        return

    # 3. 验证是否包含合理的中文内容（防止复制到了错误文本）
    all_text = "".join(all_translations)
    chinese_chars = sum(1 for c in all_text if '\u4e00' <= c <= '\u9fff')
    if chinese_chars < len(chunk_items) * 0.5:
        print("FAIL: 内容似乎没有翻译成中文。")
        return

    # 4. 验证通过，写入原始 JSON 对应的 value 中
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for category, key in chunk_items:
        data[category][key] = translated_dict[category][key].strip()

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