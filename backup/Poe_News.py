# o1优化后代码
import html
import os
import re
import pyperclip
import shutil
import glob
import subprocess
import sys
import tempfile # <--- 新增
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

# ========================================================

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
    "nytimes": "nytimes.html",
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
    从剪贴板获取文本，计算其中英文字母占比并将结果写入 /tmp/english_ratio_result.txt。
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
    
    # 使用动态路径写入结果
    with open(RATIO_FILE_PATH, 'w') as f:
        f.write('true' if english_ratio > 0.5 else 'false')
    
    return english_ratio > 0.5

def get_clipboard_content() -> str:
    """
    获取剪贴板内容，去除空白行。
    如果行数小于 3，直接返回原内容，否则去掉第一行和最后一行后再返回(注释掉的部分)。
    """
    content = pyperclip.paste()
    if not content:
        return ""
    
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    # 移除第一行和最后一行
    # filtered_lines = lines[1:-1]
    
    return "\n".join(lines)

def read_file(file_path: str) -> str:
    """
    读取指定文件并返回其内容（去除首尾空白）。
    增加文件存在性检查，防止报错。
    """
    if not os.path.exists(file_path):
        # 如果文件不存在，返回空字符串，避免 crash
        return ""
        
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        return f.read().strip()

def write_html_skeleton(file_path: str, title: str) -> None:
    """
    创建并写入 HTML 骨架。
    """
    # 确保父目录存在
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
    except OSError as e:
        # 在调试时可以打印，生产环境可以选择忽略
        # print(f"Error removing {file_path}: {e}")
        pass

def move_and_record_images(url: str) -> None:
    """
    移动多种格式图片并记录到article_copier.txt
    (从 main 函数中提取出来，并使用动态路径)
    """
    source_dir = DOWNLOADS_DIR
    today = datetime.now().strftime("%y%m%d")
    target_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    record_file = os.path.join(TXT_DIRECTORY, f"article_copier_{today}.txt")
    
    # 支持的图片格式
    image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]
    
    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)
    
    # 获取所有图片文件
    image_files = []
    for format in image_formats:
        image_files.extend(glob.glob(os.path.join(source_dir, format)))
    
    moved_files = []
    # 移动文件
    for image_file in image_files:
        filename = os.path.basename(image_file)
        target_path = os.path.join(target_dir, filename)
        try:
            shutil.move(image_file, target_path)
            moved_files.append(filename)
        except Exception as e:
            print(f"Error moving file {image_file}: {e}")

    # 写入记录文件，无论是否有移动文件都写入URL
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

    # 1. 检查英文比例
    check_english_ratio()
    sleep(0.2)
    
    try:
        # 读取刚刚写入的临时文件
        if os.path.exists(RATIO_FILE_PATH):
            with open(RATIO_FILE_PATH, 'r') as f:
                is_english = (f.read().strip().lower() == 'true')
            remove_file(RATIO_FILE_PATH)
            
            if is_english:
                try:
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    poe_auto_path = os.path.join(current_dir, 'Poe_auto.py')
                    # 执行 Poe_auto.py，带参数"short"
                    subprocess.run([sys.executable, poe_auto_path, 'short'], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error executing Poe_auto.py: {e}")
                except Exception as e:
                    print(f"Unexpected error running Poe_auto.py: {e}")
    except Exception as e:
        print(f"Error checking english ratio: {e}")
    
    # 2. 处理剪贴板内容
    clipboard_content = get_clipboard_content()
    if clipboard_content:
        # =========== 修改 1：全局去除 # 和 * ===========
        # 放在最前面，确保后续的逻辑（如 splitlines）处理的是干净的文本
        clipboard_content = clipboard_content.replace('#', '').replace('*', '')

        # 将内容按行分割，方便处理第一行
        lines = clipboard_content.splitlines()
        
        if lines:  # 确保内容不为空
            first_line = lines[0].strip() # 加上 strip() 更加保险，防止开头有不可见空格影响判断

            # =========== 修改 2：简化第一段删除逻辑 ===========
            # 只要第一段以 "以下" 开头，直接删除整个第一段
            if first_line.startswith(("以下", "这是", "这篇")):
                # 将第一行之后的内容重新组合成新的剪贴板内容
                clipboard_content = "\n".join(lines[1:]).lstrip()

            # --- 下面保留你原有的其他补充逻辑 (作为 elif) ---
            
            # 原规则：如果第一段包含"以下"且包含"翻译/全译"（处理"以下"不在开头但在句中的情况）
            elif "以下" in first_line and ("翻译" in first_line or "全译" in first_line):
                clipboard_content = "\n".join(lines[1:]).lstrip()

            # 原规则：正则清理引导句（处理 "我将从以下几个方面..." 这种开头不为"以下"的情况）
            elif any(keyword in first_line for keyword in ["总结", "以下", "方面", "几点"]):
                # 正则表达式解释:
                # [，。]       - 匹配一个中文逗号或句号
                # \s*         - 匹配0个或多个空白符
                # .*?         - 非贪婪匹配任意字符
                # (?:总结|以下|方面|几点) - 匹配核心关键词之一
                # .*?         - 非贪婪匹配任意字符
                # [:：]        - 匹配中英文冒号
                modified_first_line = re.sub(r'[，。]\s*.*?(?:总结|以下|方面|几点).*?[:：]', '：', first_line, count=1)
                
                # 仅在正则表达式成功匹配并作出改变时才更新内容
                if modified_first_line != first_line:
                    lines[0] = modified_first_line
                    clipboard_content = "\n".join(lines)

    # 3. 读取站点和 segment 信息
    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)
    
    site_content_with_tags = f'{site_content}'
    final_content = f"{site_content_with_tags}\n\n{clipboard_content}"
    
    # 4. 写入 TXT 文件
    now = datetime.now()
    txt_file_name = f"News_{now.strftime('%y_%m_%d')}.txt"
    txt_file_path = os.path.join(TXT_DIRECTORY, txt_file_name)
    
    # 确保目录存在
    os.makedirs(TXT_DIRECTORY, exist_ok=True)
    
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content + '\n\n')
    
    # 5. 写入 HTML 文件
    html_file_name = SEGMENT_TO_HTML_FILE.get(segment_content.lower(), "other.html")
    html_file_path = os.path.join(HTML_DIRECTORY, html_file_name)
    
    if not os.path.isfile(html_file_path):
        write_html_skeleton(html_file_path, segment_content)
    
    append_to_html(html_file_path, now.strftime('%Y-%m-%d %H:%M:%S'), clipboard_content)
    
    if os.path.isfile(html_file_path):
        close_html_skeleton(html_file_path)
    
    # 6. 处理图片
    # 调用提取出来的函数
    move_and_record_images(url)
    sleep(0.3)
    
    # 7. 删除临时文件
    remove_file(SEGMENT_FILE_PATH)
    remove_file(SITE_FILE_PATH)

if __name__ == '__main__':
    main()
