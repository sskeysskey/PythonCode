#!/usr/bin/env python3
"""
Clipboard_removal.py
清理剪贴板内容并写回剪贴板：
  1. 移除「更多阅读 / 延伸阅读 / 相关阅读 / 拓展阅读」（含繁体）开头的行
  2. 移除以 IGNORE_PREFIXES 中任一前缀开头的整行（原 keyword_check 中的功能，已迁移至此）
  3. 移除「以下是...」且中文字符少于 10 个的行
  4. Bloomberg：剔除末尾 newsletter / podcast 推广段落
  5. RFI.fr：移除 YouTube Cookie 提示及其后内容
  6. 移除末尾「本文原以英文撰寫」段落/行
"""

import re
import sys
import unicodedata
import pyperclip

# ============ 需整行删除的前缀列表（可自由增删）============
# 匹配前会对「行」和「前缀」做同样的规范化（去零宽字符、全半角统一、空白合并），
# 所以这里按网页上看到的样子写即可，不用操心全角冒号、多余空格等问题。
IGNORE_PREFIXES = (
    "此文包含Instagram提供的内容",
    "此文包含Google YouTube提供的内容",
    "此文包含Google YouTue提供的内容",   # 保留原列表中的写法，两种都能匹配
    "結尾 Instagram 帖子",
    "結尾 YouTube 帖子",
    "我們使用了人工智慧協助翻譯",
    "按此了解我們如何使用人工智慧",
    "本文部分原以英文撰寫",
    "補充報導：",
    "圖表製作：",
    "本文原以英文撰寫",
    "了解更多關於",
)

# 网页复制时常见的「隐形字符」：零宽空格/连接符、方向标记、BOM、软连字符等
_INVISIBLE_CHARS_RE = re.compile(r'[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad]')


def normalize_for_match(text):
    """
    仅用于「比较」的规范化（不会改动写回剪贴板的原文）：
      - 去除零宽字符 / BOM 等 str.strip() 去不掉的隐形字符
      - NFKC：全角标点→半角、不间断空格/全角空格→普通空格
      - 连续空白合并为一个空格，并去掉首尾空白
    """
    text = _INVISIBLE_CHARS_RE.sub('', text)
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# 预先规范化前缀并去重（保持顺序）
_NORMALIZED_IGNORE_PREFIXES = tuple(
    dict.fromkeys(normalize_for_match(p) for p in IGNORE_PREFIXES if p.strip())
)

_ORIGINAL_ENGLISH_NOTE = normalize_for_match("本文原以英文撰寫")
_FOLLOWING_PREFIX = normalize_for_match("以下是")


def collapse_blank_lines(text):
    """把连续多个空行（含仅有空白的行）压缩为一个空行"""
    return re.sub(r'\n(?:[ \t\u3000\u00a0]*\n){2,}', '\n\n', text)


def is_short_line_to_remove(line):
    """
    判断一行是否应该被删除：
    1. 以"以下是"开头
    2. 且该行中文字符数少于 10 个
    """
    if normalize_for_match(line).startswith(_FOLLOWING_PREFIX):
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', line)
        if len(chinese_chars) < 10:
            return True
    return False


def remove_ignored_prefix_lines(content):
    """删除以 IGNORE_PREFIXES 中任一前缀开头的整行"""
    kept_lines = []
    removed = 0
    for line in content.splitlines():
        if _NORMALIZED_IGNORE_PREFIXES and normalize_for_match(line).startswith(_NORMALIZED_IGNORE_PREFIXES):
            removed += 1
            continue
        kept_lines.append(line)

    if removed == 0:
        return content

    result = collapse_blank_lines("\n".join(kept_lines)).strip("\n")
    print(f"[Prefix] 已移除 {removed} 行指定前缀开头的内容。")
    return result


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
    stripped = normalize_for_match(paragraph)
    if not stripped:
        return False

    lower = stripped.lower()

    if lower.startswith("explore all bloomberg newsletters"):
        return True

    if "listen now" in lower and "subscribe on" in lower:
        return True

    return False


def remove_bloomberg_tail(content):
    """
    针对 Bloomberg 文章：找到第一个命中的推广段落，
    将该段及其之后的所有段落整体删除。
    返回 (新内容, 是否有删除)
    """
    paragraphs = re.split(r'\n\s*\n', content)

    cut_index = next(
        (i for i, p in enumerate(paragraphs) if is_bloomberg_footer_paragraph(p)),
        None
    )
    if cut_index is None:
        return content, False

    return "\n\n".join(paragraphs[:cut_index]).rstrip(), True


def remove_rfi_youtube_content(content, url):
    """
    针对 RFI.fr 页面：如果剪贴板内容包含"若要显此YouTube 内容，您需要授权受众测量和广告 Cookies"，
    则将该句和其后的所有内容清除
    """
    if "rfi.fr" in url.lower():
        target_text = "若要显此YouTube 内容，您需要授权受众测量和广告 Cookies"
        index = content.find(target_text)
        if index != -1:
            print("[RFI.fr] 已移除 YouTube Cookie 提示及后续内容。")
            return content[:index].rstrip()
    return content


def remove_original_english_note(content):
    """
    移除末尾以「本文原以英文撰寫」开头的内容：
      - 若最后一个段落（以空行分隔）以它开头 → 删除整个段落
      - 否则若最后一个非空行以它开头（BBC 等单换行分段的情况）→ 删除该行
    """
    lines = content.rstrip().splitlines()
    if not lines:
        return content

    # 找到最后一个段落的起始行（最后一个空行之后）
    para_start = 0
    for i in range(len(lines) - 1, -1, -1):
        if not normalize_for_match(lines[i]):
            para_start = i + 1
            break

    if normalize_for_match(lines[para_start]).startswith(_ORIGINAL_ENGLISH_NOTE):
        lines = lines[:para_start]
    elif normalize_for_match(lines[-1]).startswith(_ORIGINAL_ENGLISH_NOTE):
        lines = lines[:-1]
    else:
        return content

    print("[Clean] 移除末尾「本文原以英文撰寫」段落")
    return "\n".join(lines).rstrip()


def clean_clipboard():
    clipboard_content = pyperclip.paste() or ""
    if not clipboard_content.strip():
        print("剪贴板为空，未做任何处理。")
        return clipboard_content

    current_url = get_current_url()

    # 1. 移除"更多阅读 / 延伸阅读 / 相关阅读 / 拓展阅读"（含繁体）开头的行
    pattern = r'^[ \t\u3000]*(?:更多阅读|延伸阅读|相关阅读|拓展阅读|更多閱讀|延伸閱讀|相關閱讀|拓展閱讀).*(?:\r?\n|$)'
    content = re.sub(pattern, '', clipboard_content, flags=re.MULTILINE)

    # 2. 移除指定前缀开头的整行（原 keyword_check 功能，已迁移）
    content = remove_ignored_prefix_lines(content)

    # 3. 按行过滤："以下是..."且中文字符少于 10 个的行
    lines = content.splitlines()
    content = "\n".join(line for line in lines if not is_short_line_to_remove(line))

    # 4. Bloomberg：剔除末尾 newsletter / podcast 推广段
    if "bloomberg.com" in current_url.lower():
        content, removed = remove_bloomberg_tail(content)
        if removed:
            print("[Bloomberg] 已剔除末尾的 newsletter/podcast 推广段落。")

    # 5. RFI.fr：移除 YouTube Cookie 提示内容
    content = remove_rfi_youtube_content(content, current_url)

    # 6. 移除末尾「本文原以英文撰寫」开头的段落/行
    content = remove_original_english_note(content)

    # 统一结尾：去掉末尾空白，保留一个换行（与原脚本行为一致）
    final_content = content.rstrip() + "\n" if content.strip() else ""

    pyperclip.copy(final_content)
    return final_content


if __name__ == "__main__":
    try:
        clean_clipboard()
        print("剪贴板内容已清理完成！")
        print("已移除\"更多阅读\"等相关行、指定前缀开头的行，以及\"以下是...\"且中文少于10字的行。")
        print("如适用，还移除了 Bloomberg 推广段落、RFI YouTube Cookie 提示、末尾「本文原以英文撰寫」段落。")
    except Exception as e:
        print(f"发生错误: {str(e)}")
        sys.exit(1)