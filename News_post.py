#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的「AI 中文结果落盘」脚本
替代 Qianwen_News.py / Deepseek_News.py / Doubao_News.py / Poe_News.py

用法:
    News_post.py <provider> <url>
        provider : qianwen | deepseek | doubao
                   也接受带通道后缀的写法：qianwen_ui / qianwen_api / deepseek_ui /
                   deepseek_api / doubao_ui ...（后缀只用于日志标注，不影响清洗规则）
        url      : 当前文章 URL

清洗流水线（按「品牌」决定，与通道无关）：
    1. 通用预处理（所有 provider，含 raw）：去 markdown 符号 / 思维链 / 代码围栏 / 空行
    2. 公共头部：来源推广（Newsletter / Odd Lots ...）           [common_rules=True 时]
    3. 品牌头部：clean_head_qianwen / clean_head_doubao / clean_head_deepseek
    4. 模块前缀剥离（"模块一："）                                [strip_module_prefix=True 时]
    5. 公共尾部：来源推广截断 + AI 追问/声明截断 + 尾部分隔线    [common_rules=True 时]
    6. 公共全局过滤：分隔线 / 广告 / 过渡句 ...                  [common_rules=True 时]

所有关键词只在「公共清洗词表」处配置一份。
"""

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
DEFAULT_HTML_FILE = "other.html"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}

# ================= provider 归一化 =================
PROVIDER_ALIASES = {
    "qwen": "qianwen",
    "tongyi": "qianwen",
    "ds": "deepseek",
}

# 需要剥离的通道后缀（仅用于识别，不影响清洗规则）
CHANNEL_SUFFIXES = ("_api", "-api", "_ui", "-ui", "_web", "-web", "_chrome", "-chrome")
API_SUFFIXES = ("_api", "-api")

# 是否把被删除的文本记录到 News/delete_content.txt
LOG_DELETED = True

# 是否剥离整行的 markdown 代码围栏（``` / ```markdown / ~~~）。
STRIP_CODE_FENCES = True


# =========================================================
#   公共清洗词表（只在这里配置一份，所有品牌共用）
# =========================================================

# 常见的 AI 开场引导句前缀
AI_INTRO_PREFIXES = (
    "意图确认", "意图理解", "意图分析", "您贴出的是", "您提供的", "本周刊", "这是一份", "以下是",
    "这段是", "这篇是", "这是一篇", "这是一则", "该内容是", "本文是", "本篇是", "这篇新闻", "这段英文",
)

# 常见的引导过渡词
AI_INTRO_TAIL_KEYWORDS = ("如下", "梳理", "总结", "整理", "要点", "速览", "概述", "核心内容", "中文")

# 常见的段落标签/短标题词
SHORT_TAG_KEYWORDS = ("总结", "分模块", "简报", "主旨", "导读", "速览", "概览", "要点", "核心事件", "中文")

# ---- AI 尾部「追问 / 邀约」关键词 ----
AI_ASK_KEYWORDS = (
    "需要我", "是否需要", "你是否", "我可以", "要不要我", "要不要说说", "要不要展开",
    "如果你需要", "如果需要", "或者需要", "希望我", "你觉得", "您觉得", "如需", "如需我",
    "哪个方向", "想继续了解", "需要吗", "想继续深", "哪个模块", "需要的话", "如果你希望",
    "以上就是", "以上总结", "这份总结", "符合你的预期", "符合您的预期", "某模块深挖",
    "每个工作日", "每工作日", "要不要聊聊", "每周一到周五", "每天早上", "这个总结是",
    "告诉我即可", "请告诉我", "随时告诉我", "要不要顺着", "工作日每天", "要不要介绍",
)
AI_ASK_MAX_LEN = 150

# ---- AI 「征求反馈」：行内同时包含 触发词 + 目标词 → AI 尾巴 ----
AI_FEEDBACK_TRIGGERS = ("你觉得", "您觉得")
AI_FEEDBACK_TARGETS = ("总结", "以上就是", "符合你的预期", "符合您的预期", "摘要", "梳理")

# ---- AI 声明 / 免责：行内包含即视为 AI 尾巴 ----
AI_STATEMENT_KEYWORDS = (
    "以上内容基于", "未添加任何主观", "基于所提供新闻", "本总结仅供参考",
    "由 AI 生成", "需要的话", "资料来源：", "数据来源：", "【AI免責聲明】",
    "（由AI生成）", "(由AI生成)", "本内容由AI生成", "本文由AI生成",
    "本篇由AI生成", "由AI辅助生成", 
)

# 在最后多少段内寻找 AI 尾巴
TAIL_SCAN_WINDOW = 7

# ---- 来源网页推广（与模型无关，来自新闻原文） ----
PROMO_KEYWORDS = ("Odd Lots",)                    # 包含即命中
PROMO_KEYWORD_COMBOS = (("Bloomberg 订阅", "简报"),)  # 同时包含才命中
NEWSLETTER_WORD = "Newsletter"
NEWSLETTER_MAX_LEN = 20                           # 短行且含 Newsletter → 推广
HEAD_PROMO_WINDOW = 4                             # 头部前 N 段内清理推广
TAIL_PROMO_WINDOW = 15                            # 尾部最后 N 段内出现推广则从该处截断

# ---- 全局过滤 ----
GLOBAL_DROP_EXACT = {"广告"}
GLOBAL_DROP_PREFIXES = ("AdChoices", "拓展阅读")
TRANSITION_KEYWORDS = ("以下", "新闻", "事件", "模块", "总结", "详细", "核心", "内容", "要点", "简报")
TRANSITION_MAX_LEN = 40

# ---- 品牌头部用到的阈值 ----
HEAD_TITLE_MAX_LEN = 70   # 千问：首行含"总结"等且长度不超过此值才视为标题删除（防误删正文首段）

# ---- 正则（预编译）----
SEPARATOR_RE = re.compile(r'[-—–－─━=＝_\s]+')
CODE_FENCE_RE = re.compile(r'(?:`{3,}|~{3,})[\w+\-]*')
THINK_RE = re.compile(r'<(think|thinking)>.*?</\1>', flags=re.S | re.I)
MODULE_PREFIX_RE = re.compile(r'^模块\s*[一二三四五六七八九十百\d]+\s*[：:]\s*')
CJK_RE = re.compile(r'[\u4e00-\u9fff]')


# =========================================================
#   公共判定函数
# =========================================================
def is_ai_intro_line(s: str) -> bool:
    """识别如：'这段是一则英文财经新闻...以下是中文要点梳理：' 这一类 AI 开场白"""
    s = s.strip()
    if not s:
        return False
    # 1. 命中典型开场词
    if s.startswith(AI_INTRO_PREFIXES):
        # 如果整段结尾带有引导冒号，或者明确包含引导过渡意图
        if s.endswith(("：", ":", "如下", "如下：", "如下。")) or "以下" in s or "梳理" in s:
            return True
        # 短的背景交代句（<= 60字）直接剔除
        if len(s) <= 60 and any(k in s for k in ("新闻", "报道", "文章", "内容", "讲")):
            return True

    # 2. 以“以下是...”结尾的引导句（放宽长度限制到 80 字）
    if len(s) <= 80 and s.endswith(("：", ":")):
        if "以下" in s and any(k in s for k in AI_INTRO_TAIL_KEYWORDS):
            return True

    return False

def count_cjk(s: str) -> int:
    return len(CJK_RE.findall(s))


def is_separator_line(s: str) -> bool:
    """整行仅由横线 / 破折号 / 等号等组成（兼容 ---、——、- - -、=== 等）"""
    s = s.strip()
    return bool(s) and bool(SEPARATOR_RE.fullmatch(s))


def has_question_mark(s: str) -> bool:
    return "？" in s or "?" in s


def is_ai_tail_line(s: str) -> bool:
    """是否为 AI 的追问 / 邀约 / 征求反馈 / 免责声明"""
    # 1. 强特征词：只要在短句中包含即视为 AI 尾巴（无需问号，涵盖“如需我...告诉我即可”）
    strong_tail_words = ("告诉我即可", "如需我", "如需进一步", "请随时告诉我")
    if len(s) <= AI_ASK_MAX_LEN and any(k in s for k in strong_tail_words):
        return True

    # 2. 以邀约词开头
    if s.startswith(AI_ASK_KEYWORDS):
        return True

    # 3. 带问号的常规追问
    if len(s) <= AI_ASK_MAX_LEN and has_question_mark(s) and any(k in s for k in AI_ASK_KEYWORDS):
        return True

    # 4. 反馈与声明
    if any(t in s for t in AI_FEEDBACK_TRIGGERS) and any(w in s for w in AI_FEEDBACK_TARGETS):
        return True
    # 声明词加上短句限制（例如不超过 40 字），或者要求特定前后缀
    if len(s) <= 40 and any(k in s for k in AI_STATEMENT_KEYWORDS):
        return True

    return False


def is_promo_line(s: str) -> bool:
    if any(k in s for k in PROMO_KEYWORDS):
        return True
    return any(all(k in s for k in combo) for combo in PROMO_KEYWORD_COMBOS)


def is_transition_line(s: str) -> bool:
    """'以下是详细总结：' 这类过渡句"""
    if len(s) > TRANSITION_MAX_LEN:
        return False
    hit = sum(1 for k in TRANSITION_KEYWORDS if k in s)
    if "以下" in s and hit >= 2 and s.endswith(("：", ":")):
        return True
    return hit >= 3


# =========================================================
#   公共清洗步骤
# =========================================================
def preprocess(content: str):
    """通用预处理：对所有 provider（含 raw）生效"""
    content = THINK_RE.sub('', content)
    content = content.replace('#', '').replace('*', '')
    lines = [ln.strip() for ln in content.splitlines()]
    if STRIP_CODE_FENCES:
        lines = [ln for ln in lines if not CODE_FENCE_RE.fullmatch(ln)]
    return [ln for ln in lines if ln]


def strip_head_promo(lines, deleted):
    """头部前 N 段内的来源推广（Newsletter / Odd Lots ...）"""
    idx = [
        i for i in range(min(HEAD_PROMO_WINDOW, len(lines)))
        if is_promo_line(lines[i])
        or (len(lines[i]) <= NEWSLETTER_MAX_LEN and NEWSLETTER_WORD in lines[i])
    ]
    for i in reversed(idx):
        deleted.append(lines.pop(i))
    return lines


def strip_module_prefix(lines):
    return [MODULE_PREFIX_RE.sub('', ln).strip() for ln in lines]


def strip_tail(lines, deleted):
    """尾部：来源推广截断 → AI 尾巴截断 / 尾部分隔线，循环到稳定"""
    # 1) 来源推广：最后 N 段内首次出现即从该处截断
    start = max(0, len(lines) - TAIL_PROMO_WINDOW)
    for i in range(start, len(lines)):
        if is_promo_line(lines[i]):
            deleted.extend(lines[i:])
            lines = lines[:i]
            break

    # 2) AI 尾巴（从窗口内最早命中处整段截断）+ 尾部分隔线
    while lines:
        start = max(0, len(lines) - TAIL_SCAN_WINDOW)
        cut = next((i for i in range(start, len(lines)) if is_ai_tail_line(lines[i])), None)
        if cut is not None:
            deleted.extend(lines[cut:])
            lines = lines[:cut]
            continue
        if is_separator_line(lines[-1]):
            deleted.append(lines.pop())
            continue
        break
    return lines


def filter_global(lines, deleted):
    kept = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if (is_separator_line(s)
                or s in GLOBAL_DROP_EXACT
                or s.startswith(GLOBAL_DROP_PREFIXES)
                or is_transition_line(s)):
            deleted.append(line)
            continue
        kept.append(line)
    return kept


# =========================================================
#   品牌头部 1：千问
# =========================================================
# 扩展千问常见的意图说明与标题关键词
QIANWEN_INTRO_PREFIXES = ("意图确认", "意图理解", "意图分析", "您贴出的是", "您提供的")
QIANWEN_TITLE_KEYWORDS = ("总结", "简报", "快讯", "快报", "速览", "概览", "资讯", "主旨")

def clean_head_qianwen(lines, deleted):
    changed = True
    while changed and lines:
        changed = False
        first = lines[0].strip()

        # 判定 A：千问/通用的开场意图与过渡句
        if is_ai_intro_line(first):
            deleted.append(lines.pop(0))
            changed = True
            continue

        # 判定 B：标题行或元标签（如“全球市场中文简报”、“一句话主旨”）
        is_title = len(first) <= HEAD_TITLE_MAX_LEN and (
            any(k in first for k in QIANWEN_TITLE_KEYWORDS)
            or ("核心" in first and "概述" in first)
        )
        if is_title:
            deleted.append(lines.pop(0))
            changed = True
            continue

        # 判定 C：头部空行或分隔线
        if is_separator_line(first):
            deleted.append(lines.pop(0))
            changed = True
            continue

    # 清理前部的超短引导标签（如“一句话主旨”、“分模块总结”等，长度 <= 10 且含特征词，或首行 <= 8 个字的小标签）
    while lines and (
        (len(lines[0]) <= 12 and any(k in lines[0] for k in SHORT_TAG_KEYWORDS))
        or len(lines[0]) <= 6
    ):
        deleted.append(lines.pop(0))

    return lines


# =========================================================
#   品牌头部 2：豆包
# =========================================================
DOUBAO_TITLE_BASE_KEYWORDS = (
    "中文精简分模块总结", "中文分模块总结", "分模块总结", "核心内容总结",
    "中文模块总结", "中文要点总结", "核心信息总结", "事件中文总结", "中文结构化总结",
    "--全文", "核心总结", "核心内容", "核心事件", "核心信息", "事件总结",
    "核心定位", "要点总结", "--英文报道",
    "分模块", "中文", "—— ", "（）", "总结",
)
DOUBAO_TITLE_CHECK_KEYWORDS = (
    "中文", "英文", "分模块", "总结", "文章", "新闻",
    "核心内容", "核心", "事件", "信息精简版", "现象",
)
DOUBAO_INTRO_HINTS = ("总结", "以下", "方面", "几点")


def _build_doubao_title_re():
    variants = set()
    for kw in DOUBAO_TITLE_BASE_KEYWORDS:
        variants.update((f"（{kw}）", f"({kw})", kw))
    body = '|'.join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    punc = r'[，。：；！？、,.?:;]*'
    return re.compile(f'{punc}(?:{body}){punc}')


DOUBAO_TITLE_RE = _build_doubao_title_re()
DOUBAO_INTRO_RE = re.compile(r'[，。]\s*.*?(?:总结|以下|方面|几点).*?[:：]')


def clean_head_doubao(lines, deleted):
    changed = True
    while changed and lines:
        changed = False
        first = lines[0]

        # 长首段：剔除"中文分模块总结"之类的字样，保留正文
        if count_cjk(first) > 14 and any(kw in first for kw in DOUBAO_TITLE_BASE_KEYWORDS):
            new = DOUBAO_TITLE_RE.sub('', first).strip()
            if new != first:
                deleted.append(f"[首段改写前] {first}")
                changed = True
                if not new:
                    lines.pop(0)
                    continue
                lines[0] = first = new

        hit = sum(1 for k in DOUBAO_TITLE_CHECK_KEYWORDS if k in first)
        if hit >= 2 and len(first) <= 14:
            deleted.append(lines.pop(0)); changed = True; continue

        if first.startswith(("下面是对你", "请使用文章顶部")):
            deleted.append(lines.pop(0)); changed = True; continue

        if ((first.startswith(("中文译文", "译文")) and count_cjk(first) < 10)
                or first.startswith(("以下", "这是", "这篇"))
                or ("以下" in first and ("翻译" in first or "全译" in first))):
            deleted.append(lines.pop(0)); changed = True; continue

        if any(kw in first for kw in DOUBAO_INTRO_HINTS):
            modified = DOUBAO_INTRO_RE.sub('：', first, count=1).strip()
            if modified and modified != first:
                lines[0] = modified

        if is_separator_line(lines[0]):
            deleted.append(lines.pop(0)); changed = True; continue

    # 第一段字符数 <= 22 则移除
    if lines and len(lines[0].strip()) <= 22:
        deleted.append(lines.pop(0))
    return lines


# =========================================================
#   品牌头部 3：DeepSeek
# =========================================================
def clean_head_deepseek(lines, deleted):
    # DeepSeek 同样先剥离通用开场白
    while lines and is_ai_intro_line(lines[0]):
        deleted.append(lines.pop(0))

    # 剥离短标题/元标签
    while lines and (
        (len(lines[0].strip()) < 22 and any(k in lines[0] for k in SHORT_TAG_KEYWORDS))
        or len(lines[0].strip()) <= 6
    ):
        deleted.append(lines.pop(0))

    return lines


# =========================================================
#   清洗档案注册表（新增品牌只需在这里加一行）
# =========================================================
PROFILES = {
    "qianwen":  {"head": clean_head_qianwen,  "strip_module_prefix": True, "common_rules": True},
    "doubao":   {"head": clean_head_doubao,   "strip_module_prefix": True, "common_rules": True},
    "deepseek": {"head": clean_head_deepseek, "strip_module_prefix": True,  "common_rules": True},
}
RAW_PROFILE = "raw"


def normalize_provider(raw: str):
    """
    把 qianwen_ui / qianwen_api / deepseek-api / qwen 等归一化。
    返回 (品牌名, is_api)；is_api 只用于日志标注。
    """
    p = (raw or "").strip().lower()
    is_api = p.endswith(API_SUFFIXES)
    for suf in CHANNEL_SUFFIXES:
        if p.endswith(suf):
            p = p[: -len(suf)]
            break
    return PROVIDER_ALIASES.get(p, p), is_api


def clean_content(profile: str, content: str):
    """返回 (清洗后的正文, 被删除的行列表)"""
    if not content:
        return "", []

    lines = preprocess(content)
    deleted = []
    cfg = PROFILES.get(profile)

    if cfg:
        if cfg["common_rules"]:
            lines = strip_head_promo(lines, deleted)
        lines = cfg["head"](lines, deleted)
        if cfg["strip_module_prefix"]:
            lines = strip_module_prefix(lines)
        if cfg["common_rules"]:
            lines = strip_tail(lines, deleted)
            lines = filter_global(lines, deleted)

    lines = [ln for ln in lines if ln.strip()]
    return "\n".join(lines), deleted


# ================= 通用工具 =================
def check_english_ratio() -> bool:
    """把剪贴板英文占比结果写入 english_ratio_result.txt（任何情况都写，避免残留旧结果）"""
    text = pyperclip.paste() or ""
    english_chars = sum(1 for c in text if ('a' <= c <= 'z') or ('A' <= c <= 'Z'))
    total_chars = sum(1 for c in text if not c.isspace())
    result = total_chars > 0 and english_chars / total_chars > 0.5
    with open(RATIO_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write('true' if result else 'false')
    return result


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


def atomic_write(file_path: str, text: str, encoding: str = 'utf-8-sig') -> None:
    """先写临时文件再替换，避免中途崩溃导致文件损坏"""
    directory = os.path.dirname(file_path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".html")
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def remove_file(file_path: str) -> None:
    try:
        os.remove(file_path)
    except OSError:
        pass


def unique_path(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{n}{ext}")
        n += 1
    return candidate


# ================= HTML =================
HTML_HEADER_ROW_END = "</tr>"
HTML_CLOSING = "    </table>\n</body>\n</html>\n"
HTML_CLOSING_RE = re.compile(r'(?:\s*</table>\s*</body>\s*</html>)+\s*$', flags=re.I)


def build_html_skeleton(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(title or "News")}</title>
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
"""


def append_to_html(file_path: str, title: str, current_time: str, content: str) -> None:
    """在表头后插入新行（最新在上），并保证文件末尾只有一份闭合标签（可自动修复旧文件）"""
    doc = read_file(file_path) if os.path.isfile(file_path) else ""
    pos = doc.find(HTML_HEADER_ROW_END)
    if pos == -1:
        if doc:
            backup = f"{file_path}.bak_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copy2(file_path, backup)
            print(f"[WARN] HTML 结构异常，已备份到 {backup} 并重建", file=sys.stderr)
        doc = build_html_skeleton(title)
        pos = doc.find(HTML_HEADER_ROW_END)
    pos += len(HTML_HEADER_ROW_END)

    escaped = html.escape(content).replace('\n', '<br>\n')
    new_row = f"""
        <tr>
            <td>{html.escape(current_time)}</td>
            <td>{escaped}</td>
        </tr>"""
    doc = doc[:pos] + new_row + doc[pos:]
    doc = HTML_CLOSING_RE.sub('', doc).rstrip() + "\n" + HTML_CLOSING
    atomic_write(file_path, doc)


# ================= 图片 =================
def move_and_record_images(url: str) -> None:
    today = datetime.now().strftime("%y%m%d")
    target_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    record_file = os.path.join(TXT_DIRECTORY, f"article_copier_{today}.txt")
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)

    moved = []
    try:
        entries = sorted(os.listdir(DOWNLOADS_DIR))
    except OSError as e:
        print(f"Error listing {DOWNLOADS_DIR}: {e}", file=sys.stderr)
        entries = []

    for filename in entries:
        src = os.path.join(DOWNLOADS_DIR, filename)
        if not os.path.isfile(src):
            continue
        if os.path.splitext(filename)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        dst = unique_path(target_dir, filename)
        try:
            shutil.move(src, dst)
            moved.append(os.path.basename(dst))
        except Exception as e:
            print(f"Error moving file {src}: {e}", file=sys.stderr)

    content = f"{url}\n\n"
    if moved:
        content += "\n".join(moved) + "\n\n"
    with open(record_file, 'a', encoding='utf-8') as f:
        f.write(content)


# ================= 日志 =================
def log_deleted(provider_label, url, deleted):
    if not (LOG_DELETED and deleted):
        return
    os.makedirs(TXT_DIRECTORY, exist_ok=True)
    path = os.path.join(TXT_DIRECTORY, "delete_content.txt")
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"[{now_str}] ({provider_label}) URL: {url}\n")
        f.write("\n".join(deleted) + "\n")
        f.write("-" * 50 + "\n\n")


# ================= 主流程 =================
def main() -> int:
    raw_provider = (sys.argv[1] if len(sys.argv) > 1 else "qianwen").strip()
    url = sys.argv[2] if len(sys.argv) > 2 else "No URL provided"

    provider, is_api = normalize_provider(raw_provider)
    profile = provider if provider in PROFILES else RAW_PROFILE
    if profile == RAW_PROFILE:
        print(f"[WARN] 未知 provider '{raw_provider}'，仅做通用预处理", file=sys.stderr)
    provider_label = f"{raw_provider} -> {profile}{' (API)' if is_api else ''}"

    check_english_ratio()
    sleep(0.2)

    clipboard_content = get_clipboard_content()
    clipboard_content, deleted = clean_content(profile, clipboard_content)
    log_deleted(provider_label, url, deleted)

    if not clipboard_content.strip():
        # 不写空摘要；保留 segment/site 临时文件，便于重试
        print(f"[ERROR] 清洗后内容为空，未写入。provider={provider_label} url={url}", file=sys.stderr)
        return 1

    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)
    final_content = f"{site_content}\n\n{clipboard_content}"

    now = datetime.now()
    os.makedirs(TXT_DIRECTORY, exist_ok=True)
    txt_file_path = os.path.join(TXT_DIRECTORY, f"News_{now.strftime('%y_%m_%d')}.txt")
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content + '\n\n')

    html_file_name = SEGMENT_TO_HTML_FILE.get(segment_content.lower(), DEFAULT_HTML_FILE)
    html_file_path = os.path.join(HTML_DIRECTORY, html_file_name)
    append_to_html(html_file_path, segment_content, now.strftime('%Y-%m-%d %H:%M:%S'), clipboard_content)

    move_and_record_images(url)
    sleep(0.3)

    remove_file(SEGMENT_FILE_PATH)
    remove_file(SITE_FILE_PATH)
    return 0


if __name__ == '__main__':
    sys.exit(main())