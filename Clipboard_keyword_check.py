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
BLOCKED_KEYWORDS = [
    "习近平",
    "天安门",
    "六四",
    "中国共产党",
    "民运",
    "反共",
    "入侵台湾",
    "中華民族",
    "国安法",
    "反修例",
    "香港国家安全法",
    "总统赖清德",
    "报复社会"
    "赖清德总统",
    "中华民国总统",
    "流亡藏人",
    "达赖喇嘛",
    "伏特台风",
    "亚麻台风",
    "再教育营",
    "逃离中国",
    "新疆警察",
    "白纸运动",
    "中國領袖",
    "台灣民族",
    "黎智英",
    "苹果日报",
    "胡耀邦",
    "赵紫阳",
    "异见人士",
    "刘晓波",
    "台湾总统",
    "中国间谍"
]

# ============ 路径配置 ============
USER_HOME = os.path.expanduser("~")
# 修改为 .html 后缀
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

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"

    content = pyperclip.paste()
    if not content:
        sys.exit(0)

    for keyword in BLOCKED_KEYWORDS:
        if keyword in content:
            ensure_html_file()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 构造 HTML 条目
            html_entry = f"""    <div class='entry'>
        [{current_time}] - <span class='keyword'>[Blocked: {keyword}]</span> - 
        <a href='{url}' target='_blank'>{url}</a>
    </div>\n"""
            
            # 将新条目插入到 </body> 标签之前（或者简单地追加，只要浏览器能解析即可）
            # 这里采用简单追加方式，浏览器通常能容错处理
            with open(FAILURE_FILE, 'a', encoding='utf-8') as f:
                f.write(html_entry)
            
            sys.exit(1)

    sys.exit(0)

if __name__ == '__main__':
    main()