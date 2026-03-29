#!/usr/bin/env python3
"""
translation_helper.py — 双语字典每日维护工具

用法:
  python translation_helper.py extract   # 提取待翻译新词
  python translation_helper.py merge     # 合并翻译结果到主字典
  python translation_helper.py md5       # 输出字典文件的 MD5（用于更新 version.json）
"""

import json
import os
import re
import sys
import hashlib

# --- 修改后的路径配置 ---
# 资源文件所在目录的绝对路径
RESOURCE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/Prediction"

# 字典文件和待翻译文件的完整路径
DICT_PATH = os.path.join(RESOURCE_DIR, "translation_dict.json")
PENDING_PATH = os.path.join(RESOURCE_DIR, "pending_translations.json")

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存: {path}")


def clean_option_label(raw_label):
    """
    复刻 Swift 端 PredictionOption.displayLabel 的逻辑:
    去掉排名前缀如 "1Gary Woodland" → "Gary Woodland"
    """
    match = re.match(r"^T?\d+", raw_label)
    if match:
        cleaned = raw_label[match.end():].strip()
        return cleaned if cleaned else raw_label
    return raw_label


def is_rank_only(label):
    """复刻 Swift 端的 isRankOnly 过滤逻辑"""
    return bool(re.match(r"^T?\d+$", label))


def extract_texts_from_files():
    """从所有预测 JSON 文件中提取需要翻译的文本"""
    names = set()
    options = set()
    types = set()
    subtypes = set()

    for fname in os.listdir(RESOURCE_DIR):
        if not fname.endswith(".json"):
            continue
        if fname in ("version.json", "translation_dict.json", "pending_translations.json"):
            continue

        fpath = os.path.join(RESOURCE_DIR, fname)
        data = load_json(fpath)
        if not isinstance(data, list):
            continue

        for item in data:
            if "name" in item and item["name"]:
                names.add(item["name"])
            if "type" in item and item["type"] and item["type"].strip():
                types.add(item["type"].strip())
            if "subtype" in item and item["subtype"] and item["subtype"].strip():
                subtypes.add(item["subtype"].strip())

            i = 1
            while f"option{i}" in item:
                raw = item[f"option{i}"]
                if raw and not is_rank_only(raw):
                    cleaned = clean_option_label(raw)
                    if cleaned:
                        options.add(cleaned)
                i += 1

    return names, options, types, subtypes


def cmd_extract():
    """提取待翻译新词"""
    dictionary = load_json(DICT_PATH) or {"names": {}, "options": {}, "types": {}, "subtypes": {}}
    names, options, types, subtypes = extract_texts_from_files()

    pending = {"names": {}, "options": {}, "types": {}, "subtypes": {}}
    for n in sorted(names):
        if n not in dictionary.get("names", {}):
            pending["names"][n] = ""
    for o in sorted(options):
        if o not in dictionary.get("options", {}):
            pending["options"][o] = ""
    for t in sorted(types):
        if t not in dictionary.get("types", {}):
            pending["types"][t] = ""
    for s in sorted(subtypes):
        if s not in dictionary.get("subtypes", {}):
            pending["subtypes"][s] = ""

    total = sum(len(v) for v in pending.values())
    if total == 0:
        print("✅ 所有文本已翻译，无新增内容。")
        return

    save_json(PENDING_PATH, pending)
    print(f"\n📝 发现 {total} 条待翻译文本:")
    for cat, items in pending.items():
        if items:
            print(f"   {cat}: {len(items)} 条")
    print(f"\n请编辑 {PENDING_PATH}")
    print('将空字符串 "" 替换为中文翻译，然后运行: python translation_helper.py merge')


def cmd_merge():
    """合并已翻译的 pending 文件到主字典"""
    pending = load_json(PENDING_PATH)
    if not pending:
        print("❌ 未找到 pending_translations.json，请先运行 extract。")
        return

    dictionary = load_json(DICT_PATH) or {"names": {}, "options": {}, "types": {}, "subtypes": {}}

    merged_count = 0
    skipped_count = 0
    for category in ("names", "options", "types", "subtypes"):
        items = pending.get(category, {})
        for key, value in items.items():
            if value and value.strip():
                dictionary.setdefault(category, {})[key] = value.strip()
                merged_count += 1
            else:
                skipped_count += 1

    save_json(DICT_PATH, dictionary)
    print(f"\n📊 合并结果: {merged_count} 条已合并, {skipped_count} 条跳过(未填写)")

    # 统计总量
    total = sum(len(v) for v in dictionary.values())
    print(f"📚 字典总量: {total} 条")

    # 输出 MD5
    print(f"\n🔑 字典 MD5: {calc_md5(DICT_PATH)}")
    print("请将此 MD5 更新到 version.json 中。")

    # 清理 pending 文件
    if merged_count > 0:
        os.remove(PENDING_PATH)
        print(f"🗑️ 已删除 pending_translations.json")


def calc_md5(filepath):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_md5():
    """输出字典文件 MD5"""
    if not os.path.exists(DICT_PATH):
        print("❌ 字典文件不存在")
        return
    md5 = calc_md5(DICT_PATH)
    print(f"MD5: {md5}")
    print(f'\n在 version.json 的 files 数组中添加或更新:')
    print(json.dumps({"name": "translation_dict.json", "type": "json", "md5": md5}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python translation_helper.py [extract|merge|md5]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "extract":
        cmd_extract()
    elif cmd == "merge":
        cmd_merge()
    elif cmd == "md5":
        cmd_md5()
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: extract, merge, md5")