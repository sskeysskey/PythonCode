#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
review_blacklist.py
倒序逐条用 Chrome 打开 blacklist_url.json 里的播放地址，弹窗选择：
  移动 -> 从 blacklist 移到 url_mapping
  保留 -> 留在 blacklist，但移到 blacklist 文件的最上面（下次倒序复核时最后才轮到）
  终止 -> 结束本次复核

全程只使用一个专用 Chrome 窗口：每条都在该窗口的当前标签页里跳转新地址，
结束时自动关闭该窗口（加 --keep-tabs 则不关闭）。
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime

# ================= 配置 =================
BASE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo"
BLACKLIST = os.path.join(BASE_DIR, "blacklist_url.json")
MAPPING = os.path.join(BASE_DIR, "url_mapping.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
LOG_FILE = os.path.join(BASE_DIR, "review_blacklist.log")
MAX_BACKUPS = 20

# 如果 Chrome 直接下载 .m4u 而不播放，把这里改成你自己的 HLS 播放页，
# 例如 "http://localhost:8000/player.html?url={url_encoded}"
PLAYER_TEMPLATE = "{url}"

BTN_MOVE, BTN_KEEP, BTN_STOP = "移动", "保留", "终止"


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层不是 JSON 对象")
    return data


def save_json_atomic(path: str, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def backup_files() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in (BLACKLIST, MAPPING):
        if not os.path.exists(p):
            continue
        name = os.path.splitext(os.path.basename(p))[0]
        shutil.copy2(p, os.path.join(BACKUP_DIR, f"{name}_{ts}.json"))
        olds = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{name}_*.json")))
        for old in olds[:-MAX_BACKUPS]:
            os.remove(old)
    log(f"已备份到 {BACKUP_DIR}")


def osascript(script: str, *args: str):
    """脚本从 stdin 传入，参数通过 argv 传，避免引号/中文转义问题"""
    r = subprocess.run(["osascript", "-", *args], input=script,
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# 在“复核窗口”里跳转到新地址；窗口不存在（首次或被手动关掉）则新建。
# 返回复核窗口的 id。
OPEN_SCRIPT = '''
on run argv
    set theURL to item 1 of argv
    set widText to item 2 of argv
    tell application "Google Chrome"
        set targetWin to missing value
        if widText is not "" then
            try
                set targetWin to (first window whose id is (widText as integer))
            end try
        end if
        if targetWin is missing value then
            set targetWin to make new window
        end if
        set URL of active tab of targetWin to theURL
        set index of targetWin to 1
        activate
        return (id of targetWin) as text
    end tell
end run
'''

CLOSE_WINDOW_SCRIPT = '''
on run argv
    set widText to item 1 of argv
    tell application "Google Chrome"
        try
            close (first window whose id is (widText as integer))
            return "closed"
        end try
    end tell
    return "notfound"
end run
'''

DIALOG_SCRIPT = '''
on run argv
    set msg to item 1 of argv
    set bStop to item 2 of argv
    set bKeep to item 3 of argv
    set bMove to item 4 of argv
    set theTitle to item 5 of argv
    tell application "System Events"
        activate
        try
            set r to display dialog msg with title theTitle buttons {bStop, bKeep, bMove} default button bKeep cancel button bStop with icon note
            return button returned of r
        on error number -128
            return bStop
        end try
    end tell
end run
'''


def build_open_url(play_url: str) -> str:
    return PLAYER_TEMPLATE.format(url=play_url,
                                  url_encoded=urllib.parse.quote(play_url, safe=""))


def open_in_review_window(url: str, win_id):
    """在复核窗口中打开 url，返回窗口 id；失败返回 None（不再回退到 open -a）"""
    code, out, err = osascript(OPEN_SCRIPT, url, str(win_id) if win_id else "")
    if code == 0 and out:
        return out
    log(f"❌ AppleScript 打开 Chrome 失败：{err or out}")
    return None


def close_review_window(win_id) -> None:
    if win_id:
        osascript(CLOSE_WINDOW_SCRIPT, str(win_id))


def ask_osascript(msg: str, title: str) -> str:
    code, out, err = osascript(DIALOG_SCRIPT, msg, BTN_STOP, BTN_KEEP, BTN_MOVE, title)
    if code != 0 or out not in (BTN_MOVE, BTN_KEEP, BTN_STOP):
        log(f"弹窗异常（{err or out}），按终止处理")
        return BTN_STOP
    return out


def ask(msg: str, title: str) -> str:
    """按键：1=保留，2=移动，Esc=终止（小键盘 1/2 也可以）。关闭窗口视为终止。"""
    try:
        import tkinter as tk
    except ImportError:
        log("tkinter 不可用，改用 osascript 弹窗（数字键无效）")
        return ask_osascript(msg, title)

    result = {"choice": BTN_STOP}
    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    def choose(c: str) -> None:
        result["choice"] = c
        root.destroy()

    tk.Label(root, text=msg, justify="left", anchor="w",
             font=("PingFang SC", 13), padx=20, pady=16).pack(fill="both")

    bar = tk.Frame(root)
    bar.pack(fill="x", padx=20, pady=(0, 16))
    tk.Button(bar, text=f"终止 (Esc)", width=12,
              command=lambda: choose(BTN_STOP)).pack(side="left")
    tk.Button(bar, text="保留 (1)", width=12,
              command=lambda: choose(BTN_KEEP)).pack(side="right", padx=(8, 0))
    tk.Button(bar, text="移动 (2)", width=12,
              command=lambda: choose(BTN_MOVE)).pack(side="right")

    # 快捷键：主键盘和小键盘都支持
    root.bind("1", lambda e: choose(BTN_KEEP))
    root.bind("<KP_1>", lambda e: choose(BTN_KEEP))
    root.bind("2", lambda e: choose(BTN_MOVE))
    root.bind("<KP_2>", lambda e: choose(BTN_MOVE))
    root.bind("<Escape>", lambda e: choose(BTN_STOP))
    root.protocol("WM_DELETE_WINDOW", lambda: choose(BTN_STOP))

    # 把焦点拉到弹窗上，否则 Chrome 刚被激活，按键会打到 Chrome 里
    root.after(50, lambda: (root.lift(), root.focus_force()))
    root.mainloop()
    return result["choice"]


def is_valid(value) -> bool:
    return (isinstance(value, list) and len(value) >= 1
            and isinstance(value[0], str) and value[0].startswith("http"))


def move_item(key: str) -> bool:
    """写前重读；先写 mapping 再写 blacklist，保证不丢数据"""
    bl = load_json(BLACKLIST)
    if key not in bl:
        log(f"⚠️ blacklist 中已不存在该项，跳过：{key}")
        return False
    value = bl[key]
    mp = load_json(MAPPING)
    if key in mp and mp[key] != value:
        log(f"⚠️ url_mapping 已有该 key，旧值将被覆盖：{key} -> {mp[key]}")
    mp[key] = value
    save_json_atomic(MAPPING, mp)
    del bl[key]
    save_json_atomic(BLACKLIST, bl)
    return True


def move_to_top(key: str) -> bool:
    """
    把 key 对应的条目移到 blacklist 文件最前面（保留在黑名单中）。
    脚本是倒序复核的，排在最前面 = 下次最后才复核到。
    写前重读文件，原子写入。
    """
    bl = load_json(BLACKLIST)
    if key not in bl:
        log(f"⚠️ blacklist 中已不存在该项，无法置顶：{key}")
        return False
    if next(iter(bl)) == key:
        return True  # 已经在最上面，无需写文件
    new_bl = {key: bl[key]}
    for k, v in bl.items():
        if k != key:
            new_bl[k] = v
    save_json_atomic(BLACKLIST, new_bl)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="倒序复核 blacklist_url.json")
    ap.add_argument("--dry-run", action="store_true", help="只打开和弹窗，不修改文件")
    ap.add_argument("--keep-tabs", action="store_true", help="结束后不关闭复核窗口")
    args = ap.parse_args()

    try:
        bl = load_json(BLACKLIST)
    except Exception as e:
        sys.exit(f"读取 blacklist 失败：{e}")

    all_items = list(bl.items())[::-1]  # 倒序
    todo = [(k, v) for k, v in all_items if is_valid(v)]
    skipped = len(all_items) - len(todo)
    log(f"开始复核：共 {len(all_items)} 条，可复核 {len(todo)} 条，"
        f"跳过无播放地址 {skipped} 条{'（DRY-RUN）' if args.dry_run else ''}")
    if not todo:
        return

    moved = kept = 0
    backed_up = False
    win_id = None  # 专用复核窗口的 id

    def ensure_backup() -> None:
        nonlocal backed_up
        if not backed_up:
            backup_files()
            backed_up = True

    try:
        for idx, (key, value) in enumerate(todo, 1):
            play_url = value[0]
            title = value[1] if len(value) > 1 and isinstance(value[1], str) else "(无标题)"

            # 在同一个窗口里跳转到新地址（上一条的页面/播放会被替换掉）
            win_id = open_in_review_window(build_open_url(play_url), win_id)
            if win_id is None:
                log("无法控制 Chrome，终止（请检查 系统设置 > 隐私与安全性 > 自动化 权限）")
                break

            msg = (f"[{idx}/{len(todo)}]  {title}\n\n"
                   f"播放地址：\n{play_url}\n\n"
                   f"来源页：\n{key}\n\n"
                   f"2 = 移动（移到 url_mapping）\n"
                   f"1 = 保留（留在 blacklist，并移到最上面）\n"
                   f"Esc = 终止本次复核")
            choice = ask(msg, "Blacklist 复核")

            if choice == BTN_STOP:
                log("用户终止")
                break

            if choice == BTN_KEEP:
                kept += 1
                if args.dry_run:
                    log(f"[DRY-RUN] 保留并置顶：{title} | {play_url}")
                    continue
                try:
                    ensure_backup()
                    if move_to_top(key):
                        log(f"保留并置顶：{title} | {play_url}")
                except Exception as e:
                    log(f"❌ 置顶失败：{key} | {e}，为安全起见终止")
                    break
                continue

            # 移动
            if args.dry_run:
                moved += 1
                log(f"[DRY-RUN] 将移动：{title} | {key}")
                continue
            try:
                ensure_backup()
                if move_item(key):
                    moved += 1
                    log(f"已移动：{title} | {key}")
            except Exception as e:
                log(f"❌ 移动失败：{key} | {e}，为安全起见终止")
                break
    finally:
        if not args.keep_tabs:
            close_review_window(win_id)

    log(f"结束：移动 {moved} 条，保留(置顶) {kept} 条，跳过 {skipped} 条")


if __name__ == "__main__":
    main()