#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Title_Sanitizer.py —— 标题送翻前的「敏感词预替换」（供 Title_Engine.scpt 调用）

用法:
    Title_Sanitizer.py --in /tmp/segment_1.txt --out /tmp/title_sanitized.txt
    Title_Sanitizer.py --test "Trump-Xi summit; Xi's plan; Xi'an; Xiaomi"
    Title_Sanitizer.py --init          # 重置规则文件为内置默认（旧文件自动备份 .bak）
    Title_Sanitizer.py --list          # 列出当前生效的规则

规则文件: ~/Coding/python_code/Modules/title_sensitive_rules.json
    不存在时自动生成；以后新增敏感词只改这个 JSON，无需改代码。

stdout: "REPLACED=<n>"
退出码: 0 成功 / 3 参数或读写错误（调用方会降级为发送原文）
"""

import argparse
import json
import os
import re
import shutil
import sys
import time

USER_HOME = os.path.expanduser("~")
RULES_PATH = os.path.join(USER_HOME, "Coding", "python_code", "Modules", "title_sensitive_rules.json")
LOG_PATH = os.path.join(USER_HOME, "Coding", "News", "title_sanitize.log")

WORD_L = r"(?<![A-Za-z0-9])"
WORD_R = r"(?![A-Za-z0-9])"

DEFAULT_CONFIG = {
    "_readme": [
        "规则从上到下依次执行：更长 / 更具体的规则放前面。",
        "type=word    英文整词：自动加边界（左右不能是字母数字），词间空格自动兼容多个空白；可配 exclude_after 排除特定后缀（如 Xi'an）",
        "type=literal 纯文本子串替换，适合中文 / 日文",
        "type=regex   Python 正则；JSON 里反斜杠要写成双反斜杠",
        "enabled=false 临时停用；ignore_case=true 忽略大小写（默认区分大小写）",
        "改完立即生效；自测：python3 Title_Sanitizer.py --test \"你的句子\""
    ],
    "rules": [
        {
            "name": "Xi（含 China's/Chinese + President/leader 前缀、Jinping 后缀，排除 Xi'an）",
            "enabled": True,
            "type": "regex",
            "find": r"(?<![A-Za-z0-9])(?:(?:China['’]s\s+|Chinese\s+)?(?:President|president|Leader|leader)\s+)?Xi(?:\s+Jinping)?(?![A-Za-z0-9])(?!['’]an\b)",
            "replace": "China's President"
        },
        {
            "name": "習近平（日文，含 国家主席/主席/氏 后缀）",
            "enabled": True,
            "type": "regex",
            "find": r"習近平(?:国家主席|主席|氏)?",
            "replace": "中国国家主席"
        },
        {
            "name": "習主席 / 習氏（日文简称）",
            "enabled": True,
            "type": "regex",
            "find": r"習(?:主席|氏)",
            "replace": "中国国家主席"
        },
        {
            "name": "习近平（简体中文）",
            "enabled": True,
            "type": "regex",
            "find": r"习近平(?:主席)?",
            "replace": "中国国家主席"
        },
        {
            "name": "示例：英文整词（默认停用，按需复制修改）",
            "enabled": False,
            "type": "word",
            "find": "Winnie the Pooh",
            "replace": "the cartoon bear",
            "exclude_after": []
        },
        {
            "name": "示例：中日文字面替换（默认停用）",
            "enabled": False,
            "type": "literal",
            "find": "某敏感词",
            "replace": "替代词"
        }
    ]
}


def log_line(text):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def write_default(path, backup=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if backup and os.path.exists(path):
        shutil.copyfile(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)


def load_rules(path):
    if not os.path.exists(path):
        try:
            write_default(path)
            log_line("规则文件不存在，已生成默认规则：%s" % path)
        except Exception as e:
            log_line("生成默认规则失败：%s" % e)
        return DEFAULT_CONFIG["rules"]
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        rules = data.get("rules") if isinstance(data, dict) else data
        if not isinstance(rules, list):
            raise ValueError("rules 字段必须是列表")
        return rules
    except Exception as e:
        msg = "规则文件解析失败，本次改用内置默认规则：%s" % e
        log_line(msg)
        sys.stderr.write(msg + "\n")
        return DEFAULT_CONFIG["rules"]


def compile_rules(rules):
    compiled = []
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict) or r.get("enabled", True) is False:
            continue
        name = r.get("name") or ("rule#%d" % i)
        find = r.get("find")
        repl = r.get("replace")
        if not find or repl is None:
            log_line("规则 %s 缺少 find/replace，已跳过" % name)
            continue
        # 替换值里禁止换行，保证行数不变
        repl = str(repl).replace("\r", " ").replace("\n", " ")
        typ = (r.get("type") or "word").lower()
        flags = re.IGNORECASE if r.get("ignore_case") else 0
        try:
            if typ == "regex":
                rx = re.compile(find, flags)
                replacement = repl                      # 允许 \1 等反向引用
            elif typ == "literal":
                rx = re.compile(re.escape(find), flags)
                replacement = (lambda m, _v=repl: _v)
            else:  # word
                body = r"\s+".join(re.escape(w) for w in str(find).split())
                excl = "".join("(?!%s)" % re.escape(x) for x in (r.get("exclude_after") or []))
                rx = re.compile(WORD_L + body + WORD_R + excl, flags)
                replacement = (lambda m, _v=repl: _v)
            compiled.append((name, rx, replacement))
        except re.error as e:
            log_line("规则 %s 正则错误，已跳过：%s" % (name, e))
    return compiled


def sanitize_text(text, compiled):
    out_lines, changes, total = [], [], 0
    for line in text.split("\n"):
        new = line
        for _name, rx, replacement in compiled:
            new, n = rx.subn(replacement, new)
            total += n
        if new != line:
            changes.append((line, new))
        out_lines.append(new)
    return "\n".join(out_lines), total, changes


def main():
    ap = argparse.ArgumentParser(description="标题送翻前敏感词预替换")
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out", dest="out")
    ap.add_argument("--rules", default=RULES_PATH)
    ap.add_argument("--test", default=None)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.init:
        write_default(args.rules, backup=True)
        print("已重置规则文件：%s" % args.rules)
        return 0

    compiled = compile_rules(load_rules(args.rules))

    if args.list:
        for name, rx, _ in compiled:
            print("- %s\n    %s" % (name, rx.pattern))
        return 0

    if args.test is not None:
        result, n, _ = sanitize_text(args.test, compiled)
        print(result)
        print("REPLACED=%d" % n)
        return 0

    if not args.inp or not args.out:
        sys.stderr.write("需要 --in 和 --out\n")
        return 3

    try:
        with open(args.inp, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except Exception as e:
        sys.stderr.write("读取失败：%s\n" % e)
        return 3

    result, n, changes = sanitize_text(text, compiled)

    if result.count("\n") != text.count("\n"):   # 理论上不会发生，兜底保护
        log_line("行数校验失败，放弃替换：%s" % args.inp)
        result, n, changes = text, 0, []

    tmp = args.out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(result)
        os.replace(tmp, args.out)
    except Exception as e:
        sys.stderr.write("写出失败：%s\n" % e)
        return 3

    if n:
        log_line("%s 替换 %d 处" % (os.path.basename(args.inp), n))
        for before, after in changes:
            log_line("    - %s\n      + %s" % (before, after))

    print("REPLACED=%d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())