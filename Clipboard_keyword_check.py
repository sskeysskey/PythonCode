#!/usr/bin/env python3
"""
Clipboard_keyword_check.py
检查剪贴板内容是否包含屏蔽关键词。
命中 → 记录URL到 copy_failure.html，exit(1)
未命中 → exit(0)

注意：行前缀过滤功能已迁移到 Clipboard_removal.py，
建议先运行 Clipboard_removal.py，再运行本脚本，这样检测的是清理后的最终内容。
"""

import sys
import os
import html
import pyperclip
from datetime import datetime

# ============ 屏蔽关键词列表（可自由增删）============
# 支持两种形式：
# 1. 字符串：出现该词即拦截，如 "天安门"
# 2. 元组/列表：必须同时出现这些词才拦截，如 ("异见人士", "中国")
BLOCKED_KEYWORDS = [
    ("天安门", "中国"),
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
    "新疆警察",
    "白纸运动",
    "中國領袖",
    "台灣民族",
    "黎智英",
    "苹果日报",
    "胡耀邦",
    ("文化大革命", "中国"),
    "赵紫阳",
    "台独",
    "台湾独立",
    ("异见人士", "中国"),
    "刘晓波",
    "中国间谍"
]

# ============ 路径配置 ============
USER_HOME = os.path.expanduser("~")
FAILURE_FILE = os.path.join(USER_HOME, "Coding", "News", "copy_failure.html")


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


def find_blocked_keyword(content):
    """返回命中的规则描述字符串；未命中返回 None"""
    for item in BLOCKED_KEYWORDS:
        # 情况 A: 组合词（元组/列表），所有词都必须出现
        if isinstance(item, (tuple, list)):
            if item and all(word in content for word in item):
                return " + ".join(item)
        # 情况 B: 单一词
        elif item and item in content:
            return item
    return None


def log_failure(url, matched_str):
    ensure_html_file()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_url = html.escape(url, quote=True)
    safe_kw = html.escape(matched_str, quote=True)

    html_entry = f"""    <div class='entry'>
        [{current_time}] - <span class='keyword'>[Blocked: {safe_kw}]</span> - 
        <a href='{safe_url}' target='_blank'>{safe_url}</a>
    </div>\n"""

    with open(FAILURE_FILE, 'a', encoding='utf-8') as f:
        f.write(html_entry)


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"
    content = pyperclip.paste() or ""
    if not content.strip():
        sys.exit(0)

    matched_str = find_blocked_keyword(content)
    if matched_str:
        log_failure(url, matched_str)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()