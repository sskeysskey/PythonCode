import html
import os
import re
import pyperclip
import shutil
import glob
import sys
import tempfile
from datetime import datetime
from time import sleep

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础 Coding 目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 具体业务路径
TXT_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
HTML_DIRECTORY = os.path.join(BASE_CODING_DIR, "Website", "news")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 4. 临时文件路径 (混合策略)
# Windows 下使用系统临时目录，Mac 下保持 /tmp 以兼容可能的外部 AppleScript
if os.name == 'nt':
    TEMP_DIR = tempfile.gettempdir()
else:
    TEMP_DIR = "/tmp"

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
    "nikkeiasia": "nikkei_asia.html"
}

def is_english_char(char: str) -> bool:
    """
    判断字符是否为英文字母（包含大小写）。
    """
    return bool(re.match(r'[a-zA-Z]', char))

def check_english_ratio() -> bool:
    """
    从剪贴板获取文本，计算其中英文字母占比并将结果写入临时文件。
    返回英文字母占比是否大于 0.5。
    """
    text = pyperclip.paste()
    if not text:
        return False
    english_chars = sum(1 for char in text if is_english_char(char))
    total_chars = sum(1 for char in text if not char.isspace())
    if total_chars == 0:
        return False
    english_ratio = english_chars / total_chars
    with open(RATIO_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write('true' if english_ratio > 0.5 else 'false')
    return english_ratio > 0.5

def get_clipboard_content() -> str:
    """
    获取剪贴板内容，去除空白行。
    """
    content = pyperclip.paste()
    if not content:
        return ""
    
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return "\n".join(lines)

def read_file(file_path: str) -> str:
    """
    读取指定文件并返回其内容（去除首尾空白）。
    """
    if not os.path.exists(file_path):
        return ""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        return f.read().strip()

def write_html_skeleton(file_path: str, title: str) -> None:
    """
    创建并写入 HTML 骨架。
    """
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
    """
    将新的条目（时间和内容）以行的形式插入到指定的 HTML 文件第一行记录之后。
    """
    if not os.path.exists(file_path):
        return
    with open(file_path, 'r+', encoding='utf-8-sig') as f:
        escaped_content = html.escape(content).replace('\n', '<br>\n')
        html_content = f.read()
        insert_position = html_content.find("</tr>") + 5
        new_row = f"""
            <tr>
                <td>{current_time}</td>
                <td>{escaped_content}</td>
            </tr>
        """
        updated_content = html_content[:insert_position] + new_row + html_content[insert_position:]
        f.seek(0)
        f.write(updated_content)

def close_html_skeleton(file_path: str) -> None:
    """
    在 HTML 文件末尾补充关闭标签。
    """
    with open(file_path, 'a', encoding='utf-8-sig') as f:
        f.write("""
            </table>
        </body>
        </html>
        """)

def remove_file(file_path: str) -> None:
    """
    安全地删除文件，如果文件不存在则忽略错误并打印提示。
    """
    try:
        os.remove(file_path)
    except OSError:
        pass

def move_and_record_images(url: str) -> None:
    """
    移动多种格式图片并记录到article_copier.txt
    (已提取为独立函数，并使用动态路径)
    """
    source_dir = DOWNLOADS_DIR
    today = datetime.now().strftime("%y%m%d")
    target_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    record_file = os.path.join(TXT_DIRECTORY, f"article_copier_{today}.txt")
    image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)
    image_files = []
    for fmt in image_formats:
        image_files.extend(glob.glob(os.path.join(source_dir, fmt)))
    moved_files = []
    for image_file in image_files:
        filename = os.path.basename(image_file)
        target_path = os.path.join(target_dir, filename)
        try:
            shutil.move(image_file, target_path)
            moved_files.append(filename)
        except Exception as e:
            print(f"Error moving file {image_file}: {e}")
    content = f"{url}\n\n"
    if moved_files:
        content += "\n".join(moved_files) + "\n\n"
    with open(record_file, 'a', encoding='utf-8') as f:
        f.write(content)

def main() -> None:
    """
    主流程
    """
    # 获取传入的URL参数
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"
    check_english_ratio()
    sleep(0.2)

    # 用于收集被过滤/删除的文本内容
    deleted_lines = []

    # 拼接最终内容
    clipboard_content = get_clipboard_content()
    if clipboard_content:
        # 全局去除 # 和 *
        clipboard_content = clipboard_content.replace('#', '').replace('*', '')
        lines = [line.strip() for line in clipboard_content.splitlines()]

        # =========================================================
        #   逻辑块 A：条件删除头部内容 (包含 Newsletter 和特定通讯清理)
        # =========================================================
        if lines:
            # 1. 修改后：第一段包含"总结"，或者同时包含"核心"和"概述"则删除
            if "总结" in lines[0] or ("核心" in lines[0] and "概述" in lines[0]):
                deleted_lines.append(lines.pop(0))

            # 2. 原有：前两段中字符数 ≤ 15 且含"总结"或"分模块"则整段删除
            indices_to_remove = [
                i for i in range(min(2, len(lines)))
                if len(lines[i]) <= 15 and ("总结" in lines[i] or "分模块" in lines[i])
            ]
            for i in reversed(indices_to_remove):
                deleted_lines.append(lines.pop(i))
            
            # ---------------- 新增 Newsletter 清理逻辑 ----------------
            # 扫描前 3 段（放宽范围以防前面有空行或短标题干扰）
            newsletter_indices_to_remove = []
            newsletter_blacklist = ["Odd Lots"] # 以后如果有其他通讯推广词，可以直接加在这里
            
            for i in range(min(3, len(lines))):
                current_line = lines[i]
                
                # 规则 A：字符数 <= 20 且包含 "Newsletter"
                cond_newsletter = len(current_line) <= 20 and "Newsletter" in current_line
                
                # 规则 B：包含黑名单中的专有名词（如 Odd Lots 推广语）
                cond_blacklist = any(black_word in current_line for black_word in newsletter_blacklist)
                
                if cond_newsletter or cond_blacklist:
                    newsletter_indices_to_remove.append(i)
            
            # 倒序删除，防止索引错位
            for i in reversed(newsletter_indices_to_remove):
                deleted_lines.append(lines.pop(i))
            # ----------------------------------------------------------

            # 3. 原有：如果剩余的第一段内容长度 ≤ 10 个中文字符，则删除
            if lines and len(lines[0]) <= 10:
                deleted_lines.append(lines.pop(0))

        # =========================================================
        #   逻辑块 B：处理尾部 (Footer Processing) - 批量截断推广与 AI 废话
        # =========================================================
        if lines:
            # ---------------- 新增：尾部 Newsletter/推广 批量截断 ----------------
            # 设定检查范围 N，例如最后 15 段（足以覆盖 Bloomberg 尾部的一长串简报列表）
            N = 15
            promo_scan_start = max(0, len(lines) - N)
            promo_truncate_index = len(lines)
            
            # 在最后 N 段中正向寻找，找到第一个触发词就截断它及后面的所有内容
            for i in range(promo_scan_start, len(lines)):
                current_line = lines[i]
                # 触发条件：包含 "Odd Lots" 或其他明显推广词。
                # 加上 "订阅" 或 "简报" 是为了防止正文中恰好提到 Odd Lots 被误删。
                if "Odd Lots" in current_line or ("Bloomberg 订阅" in current_line and "简报" in current_line):
                    promo_truncate_index = i
                    break # 找到第一个触发点就停止，从这里开始后面全删
            
            # 执行截断
            if promo_truncate_index < len(lines):
                deleted_lines.extend(lines[promo_truncate_index:])
                lines = lines[:promo_truncate_index]

            # ---------------- 原有：批量截断 AI 废话 ----------------
            ai_ask_keywords = ["需要我", "是否需要", "你是否", "我可以", "要不要我", "如果你需要", "你觉得", "或者需要", "希望我", "如果需要"]
            
            truncate_index = len(lines)
            # 从后往前扫描，最多扫描最后 5 行（防止误删正文）
            scan_limit = max(-1, len(lines) - 6)
            for i in range(len(lines) - 1, scan_limit, -1):
                current_line = lines[i]
                
                # 规则1：包含提问特征词，且带有问号或冒号（准备列举选项）
                if any(kw in current_line for kw in ai_ask_keywords) and ("？" in current_line or "?" in current_line or "：" in current_line or ":" in current_line):
                    truncate_index = i
                # 规则2：直接以强烈的 AI 引导词开头
                elif current_line.startswith(tuple(ai_ask_keywords)):
                    truncate_index = i
                # 规则3：针对“这份总结涵盖了...你觉得...”这类特定句式
                elif "这份总结" in current_line and ("你觉得" in current_line or "如何" in current_line):
                    truncate_index = i

            # 如果找到了截断点，记录被截断的部分，然后丢弃
            if truncate_index < len(lines):
                deleted_lines.extend(lines[truncate_index:])
                lines = lines[:truncate_index]

            # 尾部横线清理
            changed = True
            while changed and lines:
                changed = False
                last_line = lines[-1]
                if len(last_line) > 0 and last_line.replace('-', '').strip() == '':
                    deleted_lines.append(lines.pop(-1))
                    changed = True

        # =========================================================
        #   逻辑块 C (广告过滤、全局横线及中间AI引导句过滤)
        # =========================================================
        filtered_lines = []
        # 定义中间过渡句的高频关键词
        transition_keywords = ["以下", "新闻", "事件", "模块", "总结", "详细", "核心", "内容", "要点"]
        
        for line in lines:
            stripped_line = line.strip()
            
            # --- 新增规则：删除以“拓展阅读”开头的段落 ---
            if stripped_line.startswith("拓展阅读"):
                deleted_lines.append(line)
                continue
            # -------------------------------------------

            # 1. 过滤只有“广告”两个字的行
            if stripped_line == "广告":
                deleted_lines.append(line)
                continue
            # 2. 过滤以 AdChoices 开头的行
            if stripped_line.startswith("AdChoices"):
                deleted_lines.append(line)
                continue
            # 3. 全局过滤只包含“-”的行
            if len(stripped_line) > 0 and stripped_line.replace('-', '') == '':
                deleted_lines.append(line)
                continue
            
            # 4. 智能过滤中间的 AI 引导句/过渡句
            # 规则：句子长度较短（小于等于40字），防止误删真正的新闻长段落
            if len(stripped_line) <= 40:
                # 计算命中了几个关键词
                hit_count = sum(1 for kw in transition_keywords if kw in stripped_line)
                
                # 特征 A：包含“以下”，命中至少2个关键词，且以冒号结尾（典型特征）
                if "以下" in stripped_line and hit_count >= 2 and stripped_line.endswith(("：", ":")):
                    deleted_lines.append(line)
                    continue
                
                # 特征 B：关键词密度极高（命中3个及以上）
                if hit_count >= 3:
                    deleted_lines.append(line)
                    continue
            
            # 如果没有被上面的规则拦截，则保留该行
            filtered_lines.append(line)

        clipboard_content = "\n".join(filtered_lines)

    # =========================================================
    #   将所有被过滤的文本写入 delete_content.txt
    # =========================================================
    if deleted_lines:
        os.makedirs(TXT_DIRECTORY, exist_ok=True)
        delete_log_path = os.path.join(TXT_DIRECTORY, "delete_content.txt")
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(delete_log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{now_str}] URL: {url}\n")
            f.write("\n".join(deleted_lines) + "\n")
            f.write("-" * 50 + "\n\n")

    # 拼接最终内容
    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)

    site_content_with_tags = f'{site_content}'
    final_content = f"{site_content_with_tags}\n\n{clipboard_content}"

    # 写入 TXT 文件
    now = datetime.now()
    txt_file_name = f"News_{now.strftime('%y_%m_%d')}.txt"
    txt_file_path = os.path.join(TXT_DIRECTORY, txt_file_name)

    # 确保目录存在
    os.makedirs(TXT_DIRECTORY, exist_ok=True)

    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content + '\n\n')

    # 写入 HTML 文件
    html_file_name = SEGMENT_TO_HTML_FILE.get(segment_content.lower(), "other.html")
    html_file_path = os.path.join(HTML_DIRECTORY, html_file_name)
    if not os.path.isfile(html_file_path):
        write_html_skeleton(html_file_path, segment_content)
    append_to_html(html_file_path, now.strftime('%Y-%m-%d %H:%M:%S'), clipboard_content)

    if os.path.isfile(html_file_path):
        close_html_skeleton(html_file_path)

    move_and_record_images(url)
    sleep(0.3)

    # 删除临时文件
    remove_file(SEGMENT_FILE_PATH)
    remove_file(SITE_FILE_PATH)

if __name__ == '__main__':
    main()