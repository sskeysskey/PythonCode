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
    "天安门",
    "六四",
    "民运",
    "反共",
    "反送中",
    "反修例",
    "挺台",
    "入侵台湾",
    "中華民族",
    "国安法",
    "反修例",
    "觅熵",
    "沐美",
    "长光卫星",
    "香港国家安全法",
    "报复社会",         # 修复：补充了之前遗漏的逗号
    "赖清德总统",
    "中华民国总统",
    "流亡藏人",
    "抗议中国",
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
    "文化大革命",
    "赵紫阳",
    "台独",
    "台湾独立",
    "异见人士",
    "刘晓波",
    "中国间谍"
]

# ============ 过滤前缀列表 ============
IGNORE_PREFIXES = (
    "此文包含Instagram提供的内容",
    "結尾 Instagram 帖子",
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
# 修改为 .html 后缀
FAILURE_FILE = os.path.join(USER_HOME, "Coding", "News", "copy_failure.html")

def filter_paragraphs(text):
    """
    过滤掉以指定前缀开头的段落/行
    """
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

    # 可选：如果希望剪贴板里的实际内容也同步删掉这些段落，取消下面这行的注释即可：
    # pyperclip.copy(content)

    # 2. 对过滤后的内容进行敏感词检测
    for keyword in BLOCKED_KEYWORDS:
        if keyword in content:
            ensure_html_file()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 构造 HTML 条目
            html_entry = f"""    <div class='entry'>
        [{current_time}] - <span class='keyword'>[Blocked: {keyword}]</span> - 
        <a href='{url}' target='_blank'>{url}</a>
    </div>\n"""
            
            with open(FAILURE_FILE, 'a', encoding='utf-8') as f:
                f.write(html_entry)
            
            sys.exit(1)

    sys.exit(0)

if __name__ == '__main__':
    main()