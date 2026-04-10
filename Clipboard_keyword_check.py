#!/usr/bin/env python3
"""
Clipboard_keyword_check.py
检查剪贴板内容是否包含屏蔽关键词。
命中 → 记录URL到 copy_failure.txt，exit(1)
未命中 → exit(0)
"""
import sys
import os
import pyperclip
from datetime import datetime

# ============ 屏蔽关键词列表（可自由增删）============
BLOCKED_KEYWORDS = [
    "习近平",
    "天安门",
    "六四",
    "中国共产党",
    "北京",
    "民运",
    "反共",
    "中國大陸",
    "中華民族",
    "中共",
    "中國領袖",
    "台灣民族",
    "中國政府",
    "胡耀邦",
    "赵紫阳"
]

# ============ 路径配置 ============
USER_HOME = os.path.expanduser("~")
FAILURE_FILE = os.path.join(USER_HOME, "Coding", "News", "copy_failure.txt")


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"

    content = pyperclip.paste()
    if not content:
        sys.exit(0)

    for keyword in BLOCKED_KEYWORDS:
        if keyword in content:
            os.makedirs(os.path.dirname(FAILURE_FILE), exist_ok=True)
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(FAILURE_FILE, 'a', encoding='utf-8') as f:
                # 在信息和 URL 之间添加一个换行符，形成空行
                f.write(f"[{current_time}] [BLOCKED: {keyword}]\n\n{url}\n\n")
            sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()