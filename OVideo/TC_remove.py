#!/usr/bin/env python3
import re
import json
import shutil
import subprocess
from pathlib import Path
from datetime import date

BASE = Path("/Users/yanzhang/Coding/LocalServer/Resources/OVideo")
OVIDEOS = BASE / "OVideos.json"
MAPPING = BASE / "url_mapping.json"
BLACKLIST = BASE / "blacklist_url.json"
KEYWORDS = ["TC", "TS", "抢先", "HC"]

# 匹配字符串开头的日期部分：2026 / 2026-10 / 2026-10-14
LEADING_DATE_RE = re.compile(r"^\s*\d{4}(?:-\d{1,2}(?:-\d{1,2})?)?")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    # 先备份，再写入
    shutil.copy(path, str(path) + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def has_hd_source(movie):
    """playlist 中是否存在名称含 HD 的正式资源"""
    for playlist in movie.get("playlist", []):
        for ep_name in playlist.get("episodes", {}):
            if "HD" in ep_name and not any(k in ep_name for k in KEYWORDS):
                return True
    return False


def update_info(movie):
    """有 HD 资源时，把 info 中的枪版关键字替换为 HD"""
    info = movie.get("info", "")
    if not any(k in info for k in KEYWORDS):
        return False
    if not has_hd_source(movie):
        print(f"注意：《{movie['name']}》没有 HD 正式资源，info 保持不变")
        return False
    new_info = info
    for k in KEYWORDS:
        new_info = new_info.replace(k, "HD")
    movie["info"] = new_info
    return True

def update_date(movie):
    """
    只替换 date 开头的第一个日期为今天，后面的内容保持不变。
      "2026"                                  -> "2026-11-12"
      "2026-10-14(法国) / 2026-10-15(中国香港)" -> "2026-11-12(法国) / 2026-10-15(中国香港)"
    没有 date_re 时：新增 date_re，值为修改前的完整 date
    已有 date_re 时：date_re 不变，只更新 date
    返回是否发生修改
    """
    if "date" not in movie or not isinstance(movie["date"], str):
        return False

    old_date = movie["date"]
    today = date.today().isoformat()  # YYYY-MM-DD

    new_date, count = LEADING_DATE_RE.subn(lambda m: today, old_date, count=1)
    if count == 0:
        print(f"注意：《{movie.get('name')}》的 date 格式无法识别，未修改：{old_date}")
        return False
    if new_date == old_date:
        return False

    if "date_re" in movie:
        # 已有 date_re：只更新 date
        movie["date"] = new_date
    else:
        # 没有 date_re：重建字典，让 date_re 紧跟在 date 后面
        new_movie = {}
        for k, v in movie.items():
            if k == "date":
                new_movie["date"] = new_date
                new_movie["date_re"] = old_date
            else:
                new_movie[k] = v
        movie.clear()
        movie.update(new_movie)

    return True

def main():
    # 读取剪贴板（macOS）
    clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    if not clip:
        print("剪贴板为空")
        return

    ovideos = load_json(OVIDEOS)
    movie = next((m for m in ovideos.get("Movie", []) if m.get("name") == clip), None)
    if movie is None:
        print(f"Movie 分类中未找到：{clip}")
        return

    mapping = load_json(MAPPING)
    blacklist = load_json(BLACKLIST)
    moved, added, skipped = 0, 0, 0

    # 1. 处理枪版资源的 URL
    for playlist in movie.get("playlist", []):
        for ep_name, url in playlist.get("episodes", {}).items():
            # 只处理枪版资源
            if not any(k in ep_name for k in KEYWORDS):
                continue

            if url in mapping:
                # 在 mapping 里：移动到 blacklist（已在 blacklist 中则不覆盖）
                if url not in blacklist:
                    blacklist[url] = mapping[url]
                    moved += 1
                else:
                    skipped += 1
                del mapping[url]
            else:
                # 不在 mapping 里：直接写入 blacklist（已存在则跳过）
                if url not in blacklist:
                    blacklist[url] = ""
                    added += 1
                else:
                    skipped += 1

    # 2. 更新 info 字段
    info_changed = update_info(movie)

    # 3. 更新 date / date_re 字段
    date_changed = update_date(movie)

    # 4. 写回文件
    save_json(MAPPING, mapping)
    save_json(BLACKLIST, blacklist)
    if info_changed or date_changed:
        save_json(OVIDEOS, ovideos)

    print(f"《{clip}》处理完成：")
    print(f"  mapping 移动到 blacklist：{moved} 条")
    print(f"  直接新增到 blacklist：{added} 条")
    print(f"  已存在跳过：{skipped} 条")
    print(f"  info 已替换为：{movie.get('info')}" if info_changed else "  info 无需修改")
    if date_changed:
        print(f"  date 已更新为：{movie.get('date')}，date_re：{movie.get('date_re')}")
    else:
        print("  date 无需修改")


if __name__ == "__main__":
    main()