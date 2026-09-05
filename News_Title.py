#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的「标题翻译结果清洗 + 行数校验 + 落盘」脚本
替代 Qianwen_Title.py / Doubao_Title.py

用法:
    News_Title.py <provider> [segment_path]
        provider     : qianwen | doubao | deepseek
        segment_path : 可选。本次对照的原文分段文件；省略则自动取 TEMP_DIR 下编号最小的 segment_*.txt

退出码（Title_Engine.scpt 依赖）:
    0  成功：行数一致 -> 已追加写入 today_chn.txt，并把 segment_N.txt 重命名为 done_N.txt
    4  未找到 segment 文件（无事可做）
    5  检测到 AI 拒答 / 敏感拦截          -> 立刻交接给下一个 AI
    6  行数与原文不匹配                    -> 同一 AI 重试，超限后交接
    7  剪贴板无效（Prompt 回显 / 空 / 没抓到新内容 / 无有效行）-> 重试，超限后交接
    1  其他未预期异常
"""

import codecs
import glob
import hashlib
import os
import re
import sys
import tempfile
from datetime import datetime

import pyperclip

# ================= 路径配置（跨平台） =================
USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
NEWS_DIR = os.path.join(BASE_CODING_DIR, "News")
NEWS_FILE_PATH = os.path.join(NEWS_DIR, "today_chn.txt")

TEMP_DIR = tempfile.gettempdir() if os.name == "nt" else "/tmp"
DIFF_LOG_PATH = os.path.join(TEMP_DIR, "title_diff.txt")
LAST_HASH_PATH = os.path.join(TEMP_DIR, "title_last_hash.txt")

# ================= 退出码 =================
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_SEGMENT = 4
EXIT_REFUSAL = 5
EXIT_LINE_MISMATCH = 6
EXIT_INVALID_CLIPBOARD = 7

PROVIDER_LABELS = {"qianwen": "千问", "doubao": "豆包", "deepseek": "DeepSeek"}

# ================= 检测词表 =================
# 完整拒答话术（与 News_auto.py 保持一致）
REFUSAL_PHRASES = [
    "抱歉，我无法回答这个问题，我们聊聊别的吧",
    "抱歉，我无法回答这个问题",
    "我们聊聊别的吧",
    "无法回答这个问题",
    "不能回答这个问题",
    "无法协助处理该请求",
    "我无法协助完成该请求",
    "我不能协助完成该请求",
    "该内容无法处理",
    "很抱歉，我不能",
    "很抱歉，我无法",
    "违反我们的使用规范",
    "违反相关规范",
    "这个话题我暂时无法回答",
    "换个话题吧",
]

# 短文本（<SHORT_TEXT_LIMIT 字）时才生效的宽松关键词
SHORT_REFUSAL_KEYWORDS = [
    "抱歉",
    "无法回答",
    "违反我们的使用规范",
    "违反相关规范",
    "长按消息后选择",
    "不喜欢",
    "我不能",
    "重新生成",
]
SHORT_TEXT_LIMIT = 60

# Prompt 回显（说明复制到的是我们自己发出去的消息，而不是回答）
PROMPT_ECHO_MARKERS = [
    "<document>",
    "</document>",
    "只输出翻译内容",
    "保持行数完全不变",
    "逐行翻译成精准地道的中文",
]

# 首行"介绍性废话"特征
INTRO_HINTS = ["以下", "如下", "译文", "翻译", "中文", "结果"]
# 末行"AI 反问/免责"特征
OUTRO_HINTS = [
    "需要我", "是否需要", "你是否", "我可以", "要不要我", "如果你需要",
    "希望我", "以上就是", "以上翻译", "如需", "本回答由AI生成", "内容由AI生成",
]

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


# ================= 基础工具 =================
def log(msg):
    print(msg)


def fail(code, msg):
    """失败统一出口：stdout + stderr 都写一遍，AppleScript 的 errMsg 取 stderr"""
    print(msg)
    print(msg, file=sys.stderr)
    sys.exit(code)


def safe_remove(path):
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        pass


def read_text(path):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with codecs.open(path, "r", enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "r", errors="ignore") as f:
        return f.read()


def count_non_empty_lines(text):
    return sum(1 for line in text.splitlines() if line.strip())


def extract_number(filename):
    m = re.search(r"segment_(\d+)\.txt$", os.path.basename(filename))
    return int(m.group(1)) if m else None


def find_min_segment_file(directory):
    files = glob.glob(os.path.join(directory, "segment_*.txt"))
    valid = [f for f in files if extract_number(f) is not None]
    return min(valid, key=extract_number) if valid else None


def read_last_hash():
    if not os.path.exists(LAST_HASH_PATH):
        return ""
    try:
        return read_text(LAST_HASH_PATH).strip()
    except Exception:
        return ""


def write_last_hash(h):
    try:
        with codecs.open(LAST_HASH_PATH, "w", "utf-8") as f:
            f.write(h)
    except Exception:
        pass


# ================= 内容检测 =================
def is_refusal(text):
    if not text:
        return False
    normalized = re.sub(r"\s+", "", text)
    for p in REFUSAL_PHRASES:
        if p in normalized:
            return True
    if len(normalized) < SHORT_TEXT_LIMIT:
        for k in SHORT_REFUSAL_KEYWORDS:
            if k in normalized:
                return True
    return False


def is_prompt_echo(text):
    return any(m in text for m in PROMPT_ECHO_MARKERS)


# ================= 内容清洗 =================
def normalize_text(text):
    """去 Markdown 记号、全角数字转半角、去掉行首引用符/项目符号"""
    text = text.replace("\u3000", " ")
    text = text.translate(FULLWIDTH_DIGITS)
    text = text.replace("#", "").replace("*", "").replace("`", "")
    out = []
    for line in text.splitlines():
        s = line.strip()
        s = re.sub(r"^[>\-•·–—\s]+", "", s)
        out.append(s)
    return "\n".join(out)


def merge_wrapped_paragraphs(text):
    """
    某些页面复制下来是「一段正文 + 一个空行」的形式，且空行很多。
    这种情况下把同一段落内的多行合并成一行（保留原 Doubao_Title.py 的行为）。
    """
    lines = text.splitlines()
    empty_count = sum(1 for l in lines if not l.strip())
    if empty_count <= 5:
        return text

    result, seg = [], []
    for line in lines:
        if line.strip():
            seg.append(line.strip())
        else:
            if seg:
                result.append(" ".join(seg))
                seg = []
            if result and result[-1] != "":
                result.append("")
    if seg:
        result.append(" ".join(seg))
    return "\n".join(result)


def candidate_numbered(text):
    """候选 A：只保留以数字开头的行（最稳）"""
    return [l.strip() for l in text.splitlines()
            if l.strip() and re.match(r"^\d", l.strip())]


def candidate_all(text):
    """候选 B：所有非空行"""
    return [l.strip() for l in text.splitlines() if l.strip()]


def candidate_trimmed(lines):
    """候选 C：在 B 的基础上，砍掉首部的介绍句和尾部的 AI 反问/免责句"""
    res = list(lines)

    while res:
        first = res[0]
        looks_intro = (
            len(first) <= 40
            and any(h in first for h in INTRO_HINTS)
            and (first.endswith("：") or first.endswith(":"))
        )
        if looks_intro:
            res.pop(0)
        else:
            break

    while res:
        last = res[-1]
        looks_outro = last.startswith(tuple(OUTRO_HINTS)) or (
            any(h in last for h in OUTRO_HINTS) and ("？" in last or "?" in last)
        )
        if looks_outro or (last and last.replace("-", "").strip() == ""):
            res.pop(-1)
        else:
            break
    return res


def pick_lines(cleaned, expected):
    """
    返回 (lines, source_tag)。优先选择行数正好等于原文的候选；
    都不等则返回候选 A（若为空则返回候选 B）用于报错对照。
    """
    a = candidate_numbered(cleaned)
    b = candidate_all(cleaned)
    c = candidate_trimmed(b)

    for lines, tag in ((a, "numbered"), (b, "all"), (c, "trimmed")):
        if lines and len(lines) == expected:
            return lines, tag

    if a:
        return a, "numbered(mismatch)"
    if c:
        return c, "trimmed(mismatch)"
    return b, "all(mismatch)"


# ================= 落盘 =================
def append_to_news_file(content, file_path):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with codecs.open(file_path, "a+", "utf-8") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(f.tell() - 1, os.SEEK_SET)
            if f.read(1) != "\n":
                f.write("\n")
        f.write(content.rstrip("\n") + "\n")


def mark_segment_done(seg_path):
    directory = os.path.dirname(seg_path)
    base = os.path.basename(seg_path)
    new_name = "done_" + base[len("segment_"):] if base.startswith("segment_") else "done_" + base
    new_path = os.path.join(directory, new_name)
    try:
        if os.path.exists(new_path):
            os.remove(new_path)
        os.rename(seg_path, new_path)
        log(f"已重命名：{base} -> {new_name}")
    except OSError as e:
        log(f"警告：重命名 {base} 失败：{e}")


def write_diff_log(provider, seg_path, expected, got, tag, lines, raw):
    try:
        with codecs.open(DIFF_LOG_PATH, "w", "utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] provider={provider}\n")
            f.write(f"segment={seg_path}\n")
            f.write(f"原文行数={expected}  译文行数={got}  候选={tag}\n")
            f.write("-" * 50 + "\n")
            f.write("【解析出的译文行】\n")
            f.write("\n".join(lines) + "\n")
            f.write("-" * 50 + "\n")
            f.write("【原始剪贴板】\n")
            f.write(raw + "\n")
    except Exception:
        pass


# ================= 主流程 =================
def main():
    provider = (sys.argv[1] if len(sys.argv) > 1 else "qianwen").strip().lower()
    label = PROVIDER_LABELS.get(provider, provider)
    seg_arg = sys.argv[2].strip() if len(sys.argv) > 2 else ""

    safe_remove(DIFF_LOG_PATH)

    # 1. 定位原文分段
    seg_path = seg_arg if (seg_arg and os.path.exists(seg_arg)) else find_min_segment_file(TEMP_DIR)
    if not seg_path:
        fail(EXIT_NO_SEGMENT, f"未在 {TEMP_DIR} 找到任何 segment_*.txt")

    file_content = read_text(seg_path)
    expected = count_non_empty_lines(file_content)
    if expected == 0:
        log(f"{os.path.basename(seg_path)} 是空文件，直接标记为完成。")
        mark_segment_done(seg_path)
        sys.exit(EXIT_OK)

    # 2. 读剪贴板
    raw = pyperclip.paste() or ""

    if not raw.strip():
        fail(EXIT_INVALID_CLIPBOARD, f"[{label}] 剪贴板为空")

    # 3. 拒答检测（最高优先级）
    if is_refusal(raw):
        head = (raw.strip().splitlines() or ["Empty"])[0][:60]
        fail(EXIT_REFUSAL, f"[{label}] 检测到拒答/敏感拦截 -> 请求交接。首行：{head}")

    # 4. Prompt 回显（复制到了自己发的消息）
    if is_prompt_echo(raw):
        fail(EXIT_INVALID_CLIPBOARD, f"[{label}] 剪贴板是 Prompt 原文，没有抓到译文 -> 重试")

    # 5. 剪贴板没刷新（和上一次成功写入的内容一模一样）
    cur_hash = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()
    if cur_hash and cur_hash == read_last_hash():
        fail(EXIT_INVALID_CLIPBOARD, f"[{label}] 剪贴板内容与上一段完全相同，判定为复制失败 -> 重试")

    # 6. 清洗
    cleaned = normalize_text(raw)
    cleaned = merge_wrapped_paragraphs(cleaned)
    lines, tag = pick_lines(cleaned, expected)

    if not lines:
        fail(EXIT_INVALID_CLIPBOARD, f"[{label}] 清洗后没有任何有效行 -> 重试")

    got = len(lines)
    log(f"[{label}] 原文 {expected} 行 / 译文 {got} 行（候选={tag}）")

    # 7. 行数校验
    if got != expected:
        write_diff_log(provider, seg_path, expected, got, tag, lines, raw)
        fail(EXIT_LINE_MISMATCH,
             f"[{label}] 行数不匹配：原文 {expected} 行，译文 {got} 行。详见 {DIFF_LOG_PATH}")

    # 8. 写入 + 收尾
    append_to_news_file("\n".join(lines), NEWS_FILE_PATH)
    write_last_hash(cur_hash)
    mark_segment_done(seg_path)
    log(f"[{label}] {os.path.basename(seg_path)} 处理完成，已写入 {NEWS_FILE_PATH}")
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        fail(EXIT_ERROR, f"News_Title.py 未预期异常：{e}")