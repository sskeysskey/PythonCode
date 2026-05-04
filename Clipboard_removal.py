import pyperclip
import re

def is_short_line_to_remove(line):
    """
    判断一行是否应该被删除：
    1. 以"以下是"开头
    2. 且该行中文字符数少于 10 个
    """
    # 检查是否以“以下是”开头
    if line.strip().startswith("以下是"):
        # 统计中文字符数 (使用正则表达式匹配中文字符)
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', line)
        if len(chinese_chars) < 10:
            return True
    return False


def get_current_url():
    """从 /tmp/site.txt 读取当前页面 URL（由 AppleScript 的 handlename 写入）"""
    try:
        with open("/tmp/site.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def is_bloomberg_footer_paragraph(paragraph):
    """
    判断段落是否为 Bloomberg 文章末尾的 newsletter/podcast 推广段落：
      条件 A：段落中同时包含 "Listen now" 和 "subscribe on"（忽略大小写）
      条件 B：段落以 "Explore all Bloomberg newsletters" 开头（忽略大小写）
    """
    stripped = paragraph.strip()
    if not stripped:
        return False

    lower = stripped.lower()

    # 条件 B：以 "Explore all Bloomberg newsletters" 开头
    if lower.startswith("explore all bloomberg newsletters"):
        return True

    # 条件 A：同时包含 "Listen now" 和 "subscribe on"
    if "listen now" in lower and "subscribe on" in lower:
        return True

    return False


def remove_bloomberg_tail(content):
    """
    针对 Bloomberg 文章：从后往前扫描段落，
    一旦发现命中的段落，则将该段及其之后的所有段落整体删除。
    若存在多个命中段落，则从最靠前的那一个开始截断（更稳妥）。
    """
    # 以空行分段（兼容空白行）
    paragraphs = re.split(r'\n\s*\n', content)

    cut_index = None
    # 从后往前扫描，每命中一次就更新 cut_index，最终保留最靠前命中的位置
    for i in range(len(paragraphs) - 1, -1, -1):
        if is_bloomberg_footer_paragraph(paragraphs[i]):
            cut_index = i

    if cut_index is not None:
        paragraphs = paragraphs[:cut_index]

    # 重新拼回原本的段落分隔（空行）
    return "\n\n".join(paragraphs).rstrip() + "\n"


def clean_clipboard():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()

    # 1. 移除"更多阅读 / 延伸阅读 / 相关阅读 / 拓展阅读"等开头行
    pattern = r'^(?:更多阅读|延伸阅读|相关阅读|拓展阅读).*(?:\r?\n|$)'
    cleaned_content = re.sub(pattern, '', clipboard_content, flags=re.MULTILINE)

    # 2. 按行过滤："以下是..."且中文字符少于 10 个的行
    lines = cleaned_content.splitlines()
    final_lines = [line for line in lines if not is_short_line_to_remove(line)]
    final_content = "\n".join(final_lines)

    # 3. 【新增】如果当前页面是 Bloomberg，进一步剔除末尾的 newsletter / podcast 推广段
    current_url = get_current_url().lower()
    if "bloomberg.com" in current_url:
        before_len = len(final_content)
        final_content = remove_bloomberg_tail(final_content)
        if len(final_content) != before_len:
            print("[Bloomberg] 已剔除末尾的 newsletter/podcast 推广段落。")

    # 写回剪贴板
    pyperclip.copy(final_content)
    return final_content


if __name__ == "__main__":
    try:
        clean_clipboard()
        print("剪贴板内容已清理完成！")
        print("已移除\"更多阅读\"等相关行，以及\"以下是...\"且中文少于10字的行。")
    except Exception as e:
        print(f"发生错误: {str(e)}")