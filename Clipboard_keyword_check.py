#!/usr/bin/env python3
"""
Clipboard_keyword_check.py
检查剪贴板内容是否包含屏蔽关键词。
命中 → 记录URL到 copy_failure.html，exit(1)
未命中 → exit(0)
"""

import sys
import os
import pyperclip
from datetime import datetime

# ============ 屏蔽关键词列表（可自由增删）============
# 支持两种形式：
# 1. 字符串：出现该词即拦截，如 "天安门"
# 2. 元组/列表：必须同时出现这些词才拦截，如 ("异见人士", "中国")
BLOCKED_KEYWORDS = [
    "天安门",
    "六四",
    ("民运", "中国"),
    "反共",
    "反送中",
    "反修例",
    "挺台",
    "入侵台湾",
    "中華民族",
    ("国安法", "中国"),
    ("坦克人", "中国"),
    ("反修例", "中国"),
    "香港国家安全法",
    ("报复社会", "中国"),
    "赖清德总统",
    "中华民国总统",
    "流亡藏人",
    "抗议中国",
    "达赖喇嘛",
    "伏特台风",
    "亚麻台风",
    ("再教育营", "中国"),
    "逃离中国",
    "新疆警察",
    "白纸运动",
    "中國領袖",
    "台灣民族",
    "黎智英",
    "苹果日报",
    "胡耀邦",
    "文化大革命",
    "赵紫阳",
    "台独",
    "台湾独立",
    ("异见人士", "中国"),
    "刘晓波",
    "中国间谍"
]

# ============ 过滤前缀列表 ============
IGNORE_PREFIXES = (
    "此文包含Instagram提供的内容",
    "此文包含Google YouTue提供的内容",
    "結尾 Instagram 帖子",
    "結尾 YouTube 帖子",
    "我們使用了人工智慧",
    "按此了解我們如何",
    "本文部分原以英文撰寫",
    "此文包含Google YouTue提供的内容",
    "結尾 YouTube 帖子",
    "補充報導：",
    "圖表製作："
)

# ============ 路径配置 ============
USER_HOME = os.path.expanduser("~")
FAILURE_FILE = os.path.join(USER_HOME, "Coding", "News", "copy_failure.html")

def filter_paragraphs(text):
    """过滤掉以指定前缀开头的段落/行"""
    lines = text.splitlines()
    filtered_lines = [
        line for line in lines 
        if not line.strip().startswith(IGNORE_PREFIXES)
    ]
    return "\n".join(filtered_lines)

def ensure_html_file():
    """确保 HTML 文件存在且包含基础结构"""
    if not os.path.exists(FAILURE_FILE):
        os.makedirs(os.path.dirname(FAILURE_FILE), exist_ok=True)
        header = """<html>
<head>
    <meta charset="UTF-8">
    <title>Copy Failures Log</title>
    <style>
        body { font-family: sans-serif; padding: 20px; line-height: 1.6; }
        a { color: blue; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .entry { margin-bottom: 10px; border-bottom: 1px solid #ccc; padding-bottom: 5px; }
        .keyword { color: red; font-weight: bold; margin-right: 10px; }
    </style>
</head>
<body>
    <h1>Copy Failures Log (Blocked Keywords)</h1>
"""
        with open(FAILURE_FILE, 'w', encoding='utf-8') as f:
            f.write(header)

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"
    content = pyperclip.paste()
    if not content:
        sys.exit(0)

    # 1. 过滤指定开头的段落
    content = filter_paragraphs(content)

    # 2. 对过滤后的内容进行敏感词检测
    for item in BLOCKED_KEYWORDS:
        is_hit = False
        matched_str = ""

        # 情况 A: 组合词（用元组/列表表示）
        if isinstance(item, (tuple, list)):
            # 组合内所有词都必须在 content 中
            if all(word in content for word in item):
                is_hit = True
                matched_str = " + ".join(item)
        # 情况 B: 单一词（字符串）
        else:
            if item in content:
                is_hit = True
                matched_str = item

        # 命中规则，写入日志并退出
        if is_hit:
            ensure_html_file()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            html_entry = f"""    <div class='entry'>
        [{current_time}] - <span class='keyword'>[Blocked: {matched_str}]</span> - 
        <a href='{url}' target='_blank'>{url}</a>
    </div>\n"""

            with open(FAILURE_FILE, 'a', encoding='utf-8') as f:
                f.write(html_entry)

            sys.exit(1)

    sys.exit(0)

if __name__ == '__main__':
    main()