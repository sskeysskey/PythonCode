#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
b.py
将 url_mapping.json 中值为空字符串 "" 的条目，
整体（key + value）移动到 blacklist_url.json 的末尾。

场景：Downie 遇到 404 页面时调用，把正在处理的未完成条目拉黑，避免下次再抓。
"""

import json
import os
import sys
from collections import OrderedDict

URL_MAPPING_PATH = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"
BLACKLIST_PATH   = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json"


def load_json_ordered(path: str) -> "OrderedDict":
    """读取 JSON，保持键的原始顺序；文件不存在或为空则返回空字典"""
    if not os.path.exists(path):
        return OrderedDict()
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return OrderedDict()
        return json.loads(content, object_pairs_hook=OrderedDict)


def save_json(path: str, data) -> None:
    """原子地写回 JSON，保持中文和缩进"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp_path, path)


def main() -> int:
    try:
        url_mapping = load_json_ordered(URL_MAPPING_PATH)
    except Exception as e:
        print(f"[b.py] 读取 url_mapping.json 失败: {e}", file=sys.stderr)
        return 1

    try:
        blacklist = load_json_ordered(BLACKLIST_PATH)
    except Exception as e:
        print(f"[b.py] 读取 blacklist_url.json 失败: {e}", file=sys.stderr)
        return 1

    # 找出所有值为空字符串 / None 的 key —— 这些就是"尚未处理"的条目
    keys_to_move = [k for k, v in url_mapping.items() if v == "" or v is None]

    if not keys_to_move:
        print("[b.py] url_mapping.json 中没有空值条目，无需移动。")
        return 0

    for key in keys_to_move:
        value = url_mapping.pop(key)
        # 如果黑名单里已经有同 key，先删除旧的，再放到末尾，保证"追加到尾部"的语义
        if key in blacklist:
            del blacklist[key]
        blacklist[key] = value
        print(f"[b.py] 已移入黑名单: {key}")

    try:
        save_json(URL_MAPPING_PATH, url_mapping)
        save_json(BLACKLIST_PATH, blacklist)
    except Exception as e:
        print(f"[b.py] 写回 JSON 失败: {e}", file=sys.stderr)
        return 1

    print(f"[b.py] 完成，共移动 {len(keys_to_move)} 条记录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())