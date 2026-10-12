#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 onews_YYMMDD.json 中的每个新闻项目添加时间字段。

规则：
  - 文件名 onews_261003.json  -> 日期 2026-10-03
  - 时间范围：当天 00:01:00 ~ 09:00:00（含两端），精确到秒
  - 每个项目单独分配时间，与所属分组无关
  - 伪随机但确定：同一日期 + 同一 url 每次结果相同（重复运行不变）
  - 同一文件内时间不重复
  - 已有合法时间字段的项目默认跳过（--force 强制重新生成）

用法：
  python3 add_timestamps.py                 # 处理默认两个目录
  python3 add_timestamps.py --dry-run       # 预览，不写入
  python3 add_timestamps.py --backup        # 写入前备份为 .json.bak
  python3 add_timestamps.py --force         # 覆盖已有时间
  python3 add_timestamps.py /path/a /path/b # 指定目录
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_DIRS = [
    "/Users/yanzhang/Coding/LocalServer/Resources/ONews",
    "/Users/yanzhang/Coding/News/done",
]

DEFAULT_FIELD = "timestamp"
TIME_FMT = "%Y-%m-%d %H:%M:%S"
START_SEC = 0 * 3600 + 1 * 60 + 0   # 00:01:00
END_SEC = 9 * 3600 + 0 * 60 + 0     # 09:00:00（含）
SPAN = END_SEC - START_SEC + 1

FILE_RE = re.compile(r"^onews_(\d{2})(\d{2})(\d{2})\.json$")


def parse_file_date(filename: str):
    """onews_261003.json -> date(2026, 10, 3)；不匹配或日期非法返回 None。"""
    m = FILE_RE.match(filename)
    if not m:
        return None
    yy, mm, dd = map(int, m.groups())
    try:
        return date(2000 + yy, mm, dd)
    except ValueError:
        return None


def item_key(item: dict) -> str:
    """用于生成确定性随机数的项目唯一标识：优先 url，其次英文/中文标题。"""
    for k in ("url", "topic_eng", "topic"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def existing_second(value, d: date):
    """若已有值合法（格式正确、日期一致、在范围内），返回当天秒数，否则 None。"""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.strptime(value, TIME_FMT)
    except ValueError:
        return None
    if dt.date() != d:
        return None
    sec = dt.hour * 3600 + dt.minute * 60 + dt.second
    return sec if START_SEC <= sec <= END_SEC else None


def pick_second(d: date, key: str, used: set) -> int:
    """基于哈希的确定性伪随机秒数；冲突时顺延到下一个空闲秒。"""
    digest = hashlib.sha256(f"{d.isoformat()}|{key}".encode("utf-8")).digest()
    offset = int.from_bytes(digest[:8], "big") % SPAN
    for i in range(SPAN):
        sec = START_SEC + (offset + i) % SPAN
        if sec not in used:
            used.add(sec)
            return sec
    # 理论上只有单文件项目数 > 32341 才会走到这里，此时允许重复
    return START_SEC + offset


def format_time(d: date, sec: int) -> str:
    return (datetime(d.year, d.month, d.day) + timedelta(seconds=sec)).strftime(TIME_FMT)


def atomic_write_json(path: Path, data) -> None:
    """先写同目录临时文件，再原子替换，保留原文件权限。"""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")
        try:
            shutil.copymode(str(path), tmp)
        except OSError:
            pass
        os.replace(tmp, str(path))
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def process_file(path: Path, field: str, force: bool, dry_run: bool, backup: bool):
    """返回 (新增/更新数, 跳过数, 示例列表)；失败返回 None。"""
    d = parse_file_date(path.name)
    if d is None:
        print(f"  [跳过] 文件名日期非法: {path}")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [错误] 读取/解析失败: {path} -> {e}")
        return None

    if not isinstance(data, dict):
        print(f"  [跳过] 顶层不是对象: {path}")
        return None

    # 收集所有项目
    items = []
    for group, lst in data.items():
        if not isinstance(lst, list):
            print(f"  [警告] 分组 '{group}' 不是列表，已忽略: {path.name}")
            continue
        for it in lst:
            if isinstance(it, dict):
                items.append(it)
            else:
                print(f"  [警告] 分组 '{group}' 中存在非对象项目，已忽略: {path.name}")

    # 第一遍：登记已有的合法时间（非 force 模式）
    used = set()
    need = []
    skipped = 0
    for it in items:
        sec = None if force else existing_second(it.get(field), d)
        if sec is not None:
            used.add(sec)
            skipped += 1
        else:
            need.append(it)

    # 第二遍：为需要的项目分配时间
    samples = []
    for it in need:
        sec = pick_second(d, item_key(it), used)
        it[field] = format_time(d, sec)
        if len(samples) < 3:
            samples.append((it.get("topic") or it.get("topic_eng") or "", it[field]))

    if need and not dry_run:
        if backup:
            bak = path.with_name(path.name + ".bak")
            if not bak.exists():
                shutil.copy2(str(path), str(bak))
        atomic_write_json(path, data)

    return len(need), skipped, samples


def main():
    ap = argparse.ArgumentParser(description="为 onews_YYMMDD.json 的每个项目添加时间字段")
    ap.add_argument("dirs", nargs="*", default=DEFAULT_DIRS, help="要处理的目录")
    ap.add_argument("--field", default=DEFAULT_FIELD, help=f"字段名（默认 {DEFAULT_FIELD}）")
    ap.add_argument("--force", action="store_true", help="覆盖已有的时间字段")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    ap.add_argument("--backup", action="store_true", help="写入前备份为 .json.bak")
    args = ap.parse_args()

    total_files = total_added = total_skipped = total_failed = 0

    for dir_str in args.dirs:
        dir_path = Path(dir_str).expanduser()
        print(f"\n=== 目录: {dir_path} ===")
        if not dir_path.is_dir():
            print("  [错误] 目录不存在")
            continue

        files = sorted(p for p in dir_path.iterdir() if p.is_file() and FILE_RE.match(p.name))
        if not files:
            print("  （没有匹配 onews_YYMMDD.json 的文件）")
            continue

        for p in files:
            res = process_file(p, args.field, args.force, args.dry_run, args.backup)
            if res is None:
                total_failed += 1
                continue
            added, skipped, samples = res
            total_files += 1
            total_added += added
            total_skipped += skipped
            tag = "预览" if args.dry_run else ("已写入" if added else "无变化")
            print(f"  [{tag}] {p.name}: 新增/更新 {added}，跳过 {skipped}")
            for topic, ts in samples:
                print(f"         · {ts}  {topic[:40]}")

    print("\n=== 汇总 ===")
    print(f"处理文件: {total_files}，失败/跳过文件: {total_failed}")
    print(f"新增/更新项目: {total_added}，已存在跳过: {total_skipped}")
    if args.dry_run:
        print("（dry-run 模式，未写入任何文件）")
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())