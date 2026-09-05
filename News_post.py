#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的「AI 中文结果落盘」脚本
替代 Qianwen_News.py / Deepseek_News.py / Doubao_News.py

用法:
    News_post.py <provider> <url>
        provider : qianwen | deepseek | doubao （决定使用哪套清洗规则）
        url      : 当前文章 URL

清洗档案（CLEAN_PROFILES）：
    qianwen  -> clean_qianwen  （原 Qianwen_News.py 的 A/B/C 逻辑块）
    doubao   -> clean_doubao   （原 Doubao_News.py 的 A/B/C 逻辑块）
    deepseek -> raw            （原 Deepseek_News.py：清洗逻辑整体注释掉 = 不清洗）
"""

import glob
import html
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from time import sleep

import pyperclip

# ================= 路径配置 =================
USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

TXT_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
HTML_DIRECTORY = os.path.join(BASE_CODING_DIR, "Website", "news")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

TEMP_DIR = tempfile.gettempdir() if os.name == 'nt' else "/tmp"
SEGMENT_FILE_PATH = os.path.join(TEMP_DIR, 'segment.txt')
SITE_FILE_PATH = os.path.join(TEMP_DIR, 'site.txt')
RATIO_FILE_PATH = os.path.join(TEMP_DIR, 'english_ratio_result.txt')

SEGMENT_TO_HTML_FILE = {
    "technologyreview": "technologyreview.html",
    "economist": "economist.html",
    "nytimes": "nytimes.html",
    "nikkei": "nikkei.html",
    "bloomberg": "bloomberg.html",
    "hbr": "hbr.html",
    "ft": "ft.html",
    "wsj": "wsj.html",
    "reuters": "reuters.html",
    "washingtonpost": "washingtonpost.html",
    "nikkeiasia": "nikkei_asia.html",
}

# provider -> 清洗档案
CLEAN_PROFILES = {
    "qianwen": "qianwen",
    "doubao": "doubao",
    "deepseek": "deepseek",
}
# 是否把被删除的文本记录到 News/delete_content.txt
LOG_DELETED = True


# ================= 通用工具 =================
def is_english_char(char: str) -> bool:
    return bool(re.match(r'[a-zA-Z]', char))


def check_english_ratio() -> bool:
    """把剪贴板英文占比结果写入 /tmp/english_ratio_result.txt"""
    text = pyperclip.paste()
    if not text:
        return False
    english_chars = sum(1 for c in text if is_english_char(c))
    total_chars = sum(1 for c in text if not c.isspace())
    if total_chars == 0:
        return False
    ratio = english_chars / total_chars
    with open(RATIO_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write('true' if ratio > 0.5 else 'false')
    return ratio > 0.5


def get_clipboard_content() -> str:
    content = pyperclip.paste()
    if not content:
        return ""
    return "\n".join(line.strip() for line in content.splitlines() if line.strip())


def read_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return ""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        return f.read().strip()


def write_html_skeleton(file_path: str, title: str) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8-sig') as f:
        f.write(f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
                body {{ font-size: 28px; }}
                table {{ width: 100%; border-collapse: collapse; border: 2px solid #000; box-shadow: 3px 3px 10px rgba(0, 0, 0, 0.2); }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 2px solid #000; border-right: 2px solid #000; }}
                th {{ background-color: #f2f2f2; font-weight: bold; }}
                tr:hover {{ background-color: #f5f5f5; }}
                tr:last-child td {{ border-bottom: 2px solid #000; }}
                td:last-child, th:last-child {{ border-right: none; }}
            </style>
        </head>
        <body>
            <table>
                <tr>
                    <th>时间</th>
                    <th>摘要</th>
                </tr>
        """)


def append_to_html(file_path: str, current_time: str, content: str) -> None:
    if not os.path.exists(file_path):
        return
    with open(file_path, 'r+', encoding='utf-8-sig') as f:
        escaped = html.escape(content).replace('\n', '<br>\n')
        html_content = f.read()
        insert_position = html_content.find("</tr>") + 5
        new_row = f"""
            <tr>
                <td>{current_time}</td>
                <td>{escaped}</td>
            </tr>
        """
        updated = html_content[:insert_position] + new_row + html_content[insert_position:]
        f.seek(0)
        f.write(updated)


def close_html_skeleton(file_path: str) -> None:
    with open(file_path, 'a', encoding='utf-8-sig') as f:
        f.write("""
            </table>
        </body>
        </html>
        """)


def remove_file(file_path: str) -> None:
    try:
        os.remove(file_path)
    except OSError:
        pass


def move_and_record_images(url: str) -> None:
    today = datetime.now().strftime("%y%m%d")
    target_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    record_file = os.path.join(TXT_DIRECTORY, f"article_copier_{today}.txt")
    image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)

    image_files = []
    for fmt in image_formats:
        image_files.extend(glob.glob(os.path.join(DOWNLOADS_DIR, fmt)))

    moved = []
    for image_file in image_files:
        filename = os.path.basename(image_file)
        try:
            shutil.move(image_file, os.path.join(target_dir, filename))
            moved.append(filename)
        except Exception as e:
            print(f"Error moving file {image_file}: {e}")

    content = f"{url}\n\n"
    if moved:
        content += "\n".join(moved) + "\n\n"
    with open(record_file, 'a', encoding='utf-8') as f:
        f.write(content)


# =========================================================
#   清洗档案 1：千问（原 Qianwen_News.py 逻辑块 A/B/C）
# =========================================================
def clean_qianwen(lines):
    deleted = []

    # ---------- 逻辑块 A：头部 ----------
    if lines:
        if "总结" in lines[0] or ("核心" in lines[0] and "概述" in lines[0]):
            deleted.append(lines.pop(0))

        indices_to_remove = [
            i for i in range(min(2, len(lines)))
            if len(lines[i]) <= 15 and ("总结" in lines[i] or "分模块" in lines[i])
        ]
        for i in reversed(indices_to_remove):
            deleted.append(lines.pop(i))

        # Newsletter / 通讯推广清理（前 3 段）
        newsletter_blacklist = ["Odd Lots"]
        nl_remove = []
        for i in range(min(3, len(lines))):
            cur = lines[i]
            cond_newsletter = len(cur) <= 20 and "Newsletter" in cur
            cond_blacklist = any(w in cur for w in newsletter_blacklist)
            if cond_newsletter or cond_blacklist:
                nl_remove.append(i)
        for i in reversed(nl_remove):
            deleted.append(lines.pop(i))

        if lines and len(lines[0]) <= 10:
            deleted.append(lines.pop(0))

    # ---------- 逻辑块 B：尾部 ----------
    if lines:
        # 尾部推广批量截断（最后 15 段内）
        N = 15
        promo_scan_start = max(0, len(lines) - N)
        promo_truncate_index = len(lines)
        for i in range(promo_scan_start, len(lines)):
            cur = lines[i]
            if "Odd Lots" in cur or ("Bloomberg 订阅" in cur and "简报" in cur):
                promo_truncate_index = i
                break
        if promo_truncate_index < len(lines):
            deleted.extend(lines[promo_truncate_index:])
            lines = lines[:promo_truncate_index]

        ai_ask_keywords = [
            "需要我", "是否需要", "你是否", "我可以", "要不要我", "如果你需要",
            "你觉得", "您觉得", "或者需要", "希望我", "如果需要", "以上就是",
            "需要吗", "以上总结", "这份总结", "符合你的预期", "符合您的预期"
        ]
        ai_statement_keywords = [
            "以上内容基于", "未添加任何主观", "基于所提供新闻", "本总结仅供参考"
        ]

        truncate_index = len(lines)
        scan_limit = max(-1, len(lines) - 7)
        for i in range(len(lines) - 1, scan_limit, -1):
            cur = lines[i]
            if len(cur) <= 150 and any(k in cur for k in ai_ask_keywords) and ("？" in cur or "?" in cur):
                truncate_index = i
            elif cur.startswith(tuple(ai_ask_keywords)):
                truncate_index = i
            elif "你觉得" in cur and any(w in cur for w in
                                      ["这份总结", "以后总结", "以上就是", "总结", "符合你的预期", "摘要", "梳理"]):
                truncate_index = i
            elif any(k in cur for k in ai_statement_keywords):
                truncate_index = i

        if truncate_index < len(lines):
            deleted.extend(lines[truncate_index:])
            lines = lines[:truncate_index]

        # 尾部横线
        changed = True
        while changed and lines:
            changed = False
            last = lines[-1]
            if len(last) > 0 and last.replace('-', '').strip() == '':
                deleted.append(lines.pop(-1))
                changed = True

    # ---------- 逻辑块 C：全局过滤 ----------
    filtered = []
    transition_keywords = ["以下", "新闻", "事件", "模块", "总结", "详细", "核心", "内容", "要点"]
    for line in lines:
        s = line.strip()
        if s.startswith("拓展阅读"):
            deleted.append(line); continue
        if s == "广告":
            deleted.append(line); continue
        if s.startswith("AdChoices"):
            deleted.append(line); continue
        if len(s) > 0 and s.replace('-', '') == '':
            deleted.append(line); continue
        if len(s) <= 40:
            hit = sum(1 for k in transition_keywords if k in s)
            if "以下" in s and hit >= 2 and s.endswith(("：", ":")):
                deleted.append(line); continue
            if hit >= 3:
                deleted.append(line); continue
        filtered.append(line)

    return filtered, deleted


# =========================================================
#   清洗档案 2：豆包（原 Doubao_News.py 逻辑块 A/B/C）
# =========================================================
def clean_doubao(lines):
    deleted = []

    # ---------- 逻辑块 A：头部递归清理 ----------
    changed = True
    while changed and lines:
        changed = False
        first_line = lines[0]

        chinese_count = len(re.findall(r'[\u4e00-\u9fff]', first_line))

        base_keywords = [
            "中文精简分模块总结", "中文分模块总结", "分模块总结", "核心内容总结",
            "中文模块总结", "中文要点总结", "核心信息总结", "事件中文总结", "中文结构化总结",
            "--全文", "核心总结", "核心内容", "核心事件", "核心信息", "事件总结",
            "核心定位", "要点总结", "--英文报道",
            "分模块", "中文", "—— ", "（）", "总结"
        ]
        target_keywords = []
        for kw in base_keywords:
            target_keywords.extend([f"（{kw}）", f"({kw})", kw])

        if chinese_count > 14 and any(kw in first_line for kw in base_keywords):
            sorted_kws = sorted(target_keywords, key=len, reverse=True)
            pattern_body = '|'.join(re.escape(kw) for kw in sorted_kws)
            punc = r'[，。：；！？、,.?:;]*'
            full_pattern = f'{punc}(?:{pattern_body}){punc}'
            lines[0] = re.sub(full_pattern, '', first_line).strip()
            first_line = lines[0]
            changed = True

        check_keywords = ["中文", "英文", "分模块", "总结", "文章", "新闻",
                          "核心内容", "核心", "事件", "信息精简版", "现象"]
        hit_count = sum(1 for k in check_keywords if k in first_line)
        if hit_count >= 2 and len(first_line) <= 14:
            deleted.append(lines.pop(0)); changed = True; continue

        if first_line.startswith(("下面是对你", "请使用文章顶部")):
            deleted.append(lines.pop(0)); changed = True; continue

        should_remove = False
        if first_line.startswith(("中文译文", "译文")) and len(re.findall(r'[\u4e00-\u9fff]', first_line)) < 10:
            should_remove = True
        elif first_line.startswith(("以下", "这是", "这篇")):
            should_remove = True
        elif "以下" in first_line and ("翻译" in first_line or "全译" in first_line):
            should_remove = True
        if should_remove:
            deleted.append(lines.pop(0)); changed = True; continue

        if any(kw in first_line for kw in ["总结", "以下", "方面", "几点"]):
            modified = re.sub(r'[，。]\s*.*?(?:总结|以下|方面|几点).*?[:：]', '：', first_line, count=1)
            if modified != first_line:
                lines[0] = modified.strip()

        if lines:
            cur = lines[0]
            if len(cur) > 0 and cur.replace('-', '').strip() == '':
                deleted.append(lines.pop(0)); changed = True; continue

    # 第一段字符数 <= 22 则移除
    if lines and len(lines[0].strip()) <= 22:
        deleted.append(lines.pop(0))

    # ---------- 逻辑块 B：尾部清理 ----------
    changed = True
    while changed and lines:
        changed = False
        last_line = lines[-1]

        ai_disclaimer_keywords = ["本回答由AI生成", "内容由AI生成", "由AI生成"]
        if any(kw in last_line for kw in ai_disclaimer_keywords):
            deleted.append(lines.pop(-1)); changed = True; continue

        ai_ask_keywords = ["需要我", "是否需要", "你是否", "我可以", "要不要我",
                           "如果你需要", "你觉得", "或者需要", "希望我"]
        if last_line.startswith(tuple(ai_ask_keywords)):
            deleted.append(lines.pop(-1)); changed = True; continue
        if any(kw in last_line for kw in ai_ask_keywords) and ("？" in last_line or "?" in last_line):
            deleted.append(lines.pop(-1)); changed = True; continue

        if lines:
            cur = lines[-1]
            if len(cur) > 0 and cur.replace('-', '').strip() == '':
                deleted.append(lines.pop(-1)); changed = True; continue

    # ---------- 逻辑块 C：全局过滤 ----------
    filtered = []
    transition_keywords = ["以下", "新闻", "事件", "模块", "总结", "详细", "核心", "内容", "要点"]
    for line in lines:
        s = line.strip()
        if s == "广告":
            deleted.append(line); continue
        if s.startswith("AdChoices"):
            deleted.append(line); continue
        if len(s) > 0 and s.replace('-', '') == '':
            deleted.append(line); continue
        if len(s) <= 40:
            hit = sum(1 for kw in transition_keywords if kw in s)
            if "以下" in s and hit >= 2 and s.endswith(("：", ":")):
                deleted.append(line); continue
            if hit >= 3:
                deleted.append(line); continue
        filtered.append(line)

    return filtered, deleted

# =========================================================
#   清洗档案 3：DeepSeek 
# =========================================================
def clean_deepseek(lines):
    deleted = []

    # ---------- 逻辑块 A：第一段规则过滤 ----------
    if lines:
        first_line = lines[0].strip()
        # 字符数小于 22 且包含“总结”字样，则移出正文并记录到已删除列表
        if len(first_line) < 22 and "总结" in first_line:
            deleted.append(lines.pop(0))

    # ---------- 逻辑块 B：剥离模块前缀 ----------
    cleaned_lines = []
    # 匹配行首的 "模块一："、"模块1:"、"模块十二：" 等格式（兼容中英文冒号与多余空格）
    module_pattern = re.compile(r'^模块\s*[一二三四五六七八九十\d]+\s*[：:]\s*')

    for line in lines:
        # 剥离 "模块X：" 前缀
        new_line = module_pattern.sub('', line).strip()
        cleaned_lines.append(new_line)

    return cleaned_lines, deleted


def clean_content(profile: str, content: str):
    """返回 (清洗后的正文, 被删除的行列表)"""
    if not content or profile == "raw":
        return content, []
    content = content.replace('#', '').replace('*', '')
    lines = [line.strip() for line in content.splitlines()]
    
    if profile == "doubao":
        lines, deleted = clean_doubao(lines)
    elif profile == "deepseek":
        lines, deleted = clean_deepseek(lines)
    elif profile == "qianwen":
        lines, deleted = clean_qianwen(lines)
    else:
        deleted = []
        
    return "\n".join(lines), deleted


def log_deleted(provider, url, deleted):
    if not (LOG_DELETED and deleted):
        return
    os.makedirs(TXT_DIRECTORY, exist_ok=True)
    path = os.path.join(TXT_DIRECTORY, "delete_content.txt")
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"[{now_str}] ({provider}) URL: {url}\n")
        f.write("\n".join(deleted) + "\n")
        f.write("-" * 50 + "\n\n")


# ================= 主流程 =================
def main() -> None:
    provider = (sys.argv[1] if len(sys.argv) > 1 else "qianwen").strip().lower()
    url = sys.argv[2] if len(sys.argv) > 2 else "No URL provided"
    profile = CLEAN_PROFILES.get(provider, "raw")

    check_english_ratio()
    sleep(0.2)

    clipboard_content = get_clipboard_content()
    clipboard_content, deleted = clean_content(profile, clipboard_content)
    log_deleted(provider, url, deleted)

    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)
    final_content = f"{site_content}\n\n{clipboard_content}"

    now = datetime.now()
    txt_file_path = os.path.join(TXT_DIRECTORY, f"News_{now.strftime('%y_%m_%d')}.txt")
    os.makedirs(TXT_DIRECTORY, exist_ok=True)
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content + '\n\n')

    html_file_name = SEGMENT_TO_HTML_FILE.get(segment_content.lower(), "other.html")
    html_file_path = os.path.join(HTML_DIRECTORY, html_file_name)
    if not os.path.isfile(html_file_path):
        write_html_skeleton(html_file_path, segment_content)
    append_to_html(html_file_path, now.strftime('%Y-%m-%d %H:%M:%S'), clipboard_content)
    if os.path.isfile(html_file_path):
        close_html_skeleton(html_file_path)

    move_and_record_images(url)
    sleep(0.3)

    remove_file(SEGMENT_FILE_PATH)
    remove_file(SITE_FILE_PATH)


if __name__ == '__main__':
    main()