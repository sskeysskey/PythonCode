#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
News_Batch_Auto.py
------------------
新闻全自动批处理调度器：
  1. 定位 TodayCNH_YYMMDD.html（优先取 Chrome 中已打开的那个），解析出全部新闻链接；
  2. 去重；News_Engine 处理不了的链接（非目标域名 / 不支持的栏目 / WSJ 视频 / 首页）不打开，写入报告页；
     已经在 Chrome 中打开的同一文章不重复打开；
  3. 在 HTML 所在的 Chrome 窗口（你日常使用的 Chrome，带 cookie/插件）里逐个新开标签页，
     凑满一批（默认 20 个，已打开的目标新闻标签页也计入，防止内存爆）；
  4. 调用流水线 scpt（滚屏 → [Karing] → 总结 → txt2json → 同步），阻塞等待其返回状态；
  5. 返回 DONE 则继续下一批；其它状态（手动停止/出错/链条中止/超时）则停止并弹窗说明；
  6. 进度持久化到状态文件，中断后再次运行会从断点继续（已打开过的链接不会重复打开）。

停止：桌面放 stop_scpt.txt（与 News_AutoScroll / News_Engine 共用）。
依赖：仅 Python 标准库 + macOS osascript。
"""

import argparse
import fcntl
import glob
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse, unquote

# ============================ 配置区 ============================

AUTO_ENABLED = True            # 【总开关】False = 入口脚本什么都不做（一切照旧，手动挑新闻）

BATCH_SIZE = 20                # 每批目标标签页数（含 Chrome 中已存在的目标新闻标签页）
MIN_NEW_PER_BATCH = 5          # 即使遗留标签页很多，每批至少新开几个，保证进度
OPEN_INTERVAL = 1.5            # 每开一个标签页的间隔秒数（避免瞬间并发加载）
AFTER_OPEN_WAIT = 5            # 一批开完后再等几秒才启动流水线
BETWEEN_BATCH_WAIT = 5         # 两批之间的间隔秒数
HOOK_START_DELAY = 3           # 由前置程序以 --from-hook 启动时，先等几秒让 HTML 在 Chrome 中打开

PIPELINES = {
    "plain": "/Users/yanzhang/Coding/ScriptEditor/News_AutoScroll_Then_Engine.scpt",
    "shift": "/Users/yanzhang/Coding/ScriptEditor/News_Scroll_Shift_Engine.scpt",
}
DEFAULT_PIPELINE = "plain"     # 没有 --pipeline 参数时用哪个
REST_PIPELINE = None           # 第 2 批起用哪个；None = 与首批相同。例："plain" = 只有首批走 Karing 切换
PIPELINE_TIMEOUT = 8 * 3600    # 单批流水线最长秒数（超过则强制结束并停止）

SKIP_UNSUPPORTED = True        # News_Engine 不支持的链接不打开（写入报告页供你手动看）
SKIP_ALREADY_OPEN = True       # Chrome 中已打开的同一文章不重复打开
CLOSE_STALE_LEFTOVERS = True   # 经过 N 批流水线仍未被关闭的标签页，自动关闭（记入报告页）
LEFTOVER_MAX_BATCHES = 2

NEWS_DIR = "/Users/yanzhang/Coding/News"
HTML_NAME_RE = re.compile(r"^TodayCNH_(\d{6})\.html$")
HTML_MAX_AGE_HOURS = 36        # 找不到当天文件时，允许回退到多久以内的最新文件
STATE_FILE = os.path.join(NEWS_DIR, "batch_auto_state.json")
LOG_FILE = os.path.join(NEWS_DIR, "batch_auto.log")
LOCK_FILE = "/tmp/news_batch_auto.lock"
STOP_FILE = "/Users/yanzhang/Desktop/stop_scpt.txt"

_PY = "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
PYTHON = _PY if os.path.exists(_PY) else sys.executable
NOTIFY_SCRIPT = "/Users/yanzhang/Coding/python_code/Modules/notification.py"
OSA_TIMEOUT = 30

# 与 News_AutoScroll.py / News_Engine.scpt 保持一致
TARGET_DOMAINS = [
    "nytimes.com", "nikkei.com", "bloomberg.com", "technologyreview.com",
    "economist.com", "hbr.org", "ft.com", "wsj.com", "reuters.com",
    "washingtonpost.com", "asia.nikkei.com", "rfi.fr", "dw.com", "bbc.com",
]
# News_Engine 分支 1（英文 AI 总结）/ 分支 2（中文直接整理）的判定关键字（照搬 Engine 的 contains 规则）
ENGINE_EN_KEYS = ["technologyreview.com", "economist.com", "www.wsj.com", "reuters.com",
                  "washingtonpost.com", "asia.nikkei.com", "bloomberg.com", "nytimes.com"]
ENGINE_CN_KEYS = ["cn.wsj.com", "rfi.fr", "dw.com", "bbc.com/zhongwen"]

STATUS_TEXT = {
    "STOPPED": "总结阶段被 stop_scpt.txt 手动停止",
    "SCROLL_STOPPED": "滚屏阶段检测到停止文件",
    "SCROLL_FAIL": "滚屏未正常完成",
    "KARING_FAIL": "Karing 切换失败",
    "ENGINE_FAIL": "总结引擎异常",
    "ENGINE_ABORTED": "总结链条中止（某篇文章所有 AI 均失败/拒答；已完成部分已 txt2json+同步）",
    "POST_FAIL": "txt2json 或服务器同步失败",
    "CANCELED": "流程被终止（-128，多为弹窗中点了「终止」）",
    "TIMEOUT": "流水线运行超时",
    "ERROR": "流水线脚本出错",
    "UNKNOWN": "流水线未返回状态（请确认两个流水线 scpt 已按说明更新并重新保存）",
}

# ============================ AppleScript ============================

AS_IS_RUNNING = 'return application "Google Chrome" is running'

AS_LIST_TABS = r'''
set sep to character id 9
set nl to character id 10
set out to ""
tell application "Google Chrome"
	repeat with w in (every window)
		set wid to id of w
		set tids to id of every tab of w
		set urls to URL of every tab of w
		repeat with i from 1 to count of tids
			set out to out & (wid as text) & sep & ((item i of tids) as text) & sep & (item i of urls) & nl
		end repeat
	end repeat
end tell
return out
'''

AS_FRONT_WINDOW = r'''
tell application "Google Chrome"
	if (count of windows) is 0 then make new window
	return (id of front window) as text
end tell
'''

AS_OPEN_TAB = r'''
on run argv
	set wid to (item 1 of argv) as integer
	set u to item 2 of argv
	tell application "Google Chrome"
		try
			set w to window id wid
			get id of w
		on error
			return "__NO_WIN__"
		end try
		set t to make new tab at end of tabs of w with properties {URL:u}
		return (id of t) as text
	end tell
end run
'''

AS_ACTIVATE = r'''
on run argv
	set tidText to (item 1 of argv) as text
	tell application "Google Chrome"
		repeat with w in windows
			set tids to id of every tab of w
			repeat with i from 1 to count of tids
				if ((item i of tids) as text) is tidText then
					try
						set minimized of w to false
					end try
					set active tab index of w to i
					set index of w to 1
					activate
					return "ok"
				end if
			end repeat
		end repeat
	end tell
	return "__NO_TAB__"
end run
'''

AS_CLOSE = r'''
on run argv
	set tid to (item 1 of argv) as integer
	tell application "Google Chrome"
		repeat with w in windows
			try
				close (tab id tid of w)
				return "ok"
			end try
		end repeat
	end tell
	return "__NO_TAB__"
end run
'''

AS_DIALOG = r'''
on run argv
	activate
	display dialog (item 1 of argv) with title (item 2 of argv) buttons {"好"} default button 1 with icon note giving up after 3600
end run
'''

# ============================ 基础工具 ============================

log = logging.getLogger("nba")
_LOCK_FP = None


class OSAError(Exception):
    pass


def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    log.addHandler(fh)
    log.addHandler(sh)


def osa(script, *args, timeout=OSA_TIMEOUT):
    p = subprocess.run(["osascript", "-e", script, *[str(a) for a in args]],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise OSAError((p.stderr or "").strip())
    return p.stdout.rstrip("\n")


def notify(msg, color="blue", ms=2000):
    log.info("[通知] %s", msg)
    try:
        subprocess.run([PYTHON, NOTIFY_SCRIPT, msg, "-d", str(ms), "--bg", color, "--fg", "white"],
                       capture_output=True, timeout=ms / 1000 + 15)
    except Exception as e:
        log.warning("通知失败: %s", e)


def dialog(msg):
    log.info("[弹窗] %s", msg.replace("\n", " | "))
    try:
        subprocess.run(["osascript", "-e", AS_DIALOG, msg, "News 全自动批处理"],
                       capture_output=True, text=True)
    except Exception as e:
        log.error("弹窗失败: %s", e)


def stop_requested():
    return os.path.exists(STOP_FILE)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def start_keep_awake():
    """整个批处理期间（含总结阶段）阻止休眠；本进程退出时 caffeinate 自动结束。"""
    exe = shutil.which("caffeinate") or "/usr/bin/caffeinate"
    try:
        return subprocess.Popen([exe, "-dimsu", "-w", str(os.getpid())],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def _host_match(host, domain):
    return host == domain or host.endswith("." + domain)


def is_target(url):
    if not url.lower().startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(_host_match(host, d) for d in TARGET_DOMAINS)


def classify(url):
    """镜像 News_Engine 的判定：返回 (能否处理, 原因)。"""
    low = url.strip().lower()
    if not low.startswith(("http://", "https://")):
        return False, "非 http(s) 链接"
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False, "URL 无法解析"
    if not any(_host_match(host, d) for d in TARGET_DOMAINS):
        return False, f"非目标域名（{host}）"
    pos = low.find(host)
    if pos < 0 or len(low) - (pos + len(host)) < 8:     # Engine 的 IsTargetTab：路径过短视为首页/栏目页
        return False, "路径过短（疑似首页/栏目页）"
    if "www.wsj.com/video/" in low:
        return False, "WSJ 视频页（Engine 会直接关闭）"
    if _host_match(host, "ft.com") or any(k in low for k in ENGINE_EN_KEYS) \
            or any(k in low for k in ENGINE_CN_KEYS):
        return True, ""
    return False, f"News_Engine 暂不支持该站点/栏目（{host}）"


def norm_key(url):
    """去重键：主机(去 www.) + 路径(去末尾 /)，忽略 query/fragment（如 wsj 的 ?mod=）。"""
    try:
        u = urlparse(url.strip())
        host = (u.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host + ((u.path or "/").rstrip("/") or "/")
    except Exception:
        return url.strip()


# ============================ Chrome ============================

def list_tabs():
    tabs = []
    for line in osa(AS_LIST_TABS).splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            tabs.append({"wid": int(parts[0]), "tid": int(parts[1]), "url": parts[2]})
    return tabs


def html_path_of_tab(url):
    if not url.lower().startswith("file://"):
        return None
    p = unquote(urlparse(url).path)
    return os.path.realpath(p) if HTML_NAME_RE.match(os.path.basename(p)) else None


def find_html_tab(tabs, html_path):
    for t in tabs:
        if html_path_of_tab(t["url"]) == html_path:
            return t
    return None


def pick_window(state, tabs):
    t = find_html_tab(tabs, state["html"])
    if t:
        return t["wid"]
    wids = {x["wid"] for x in tabs}
    if state.get("wid") in wids:
        return state["wid"]
    return int(osa(AS_FRONT_WINDOW).strip())


def open_tab(state, wid, url):
    """返回 (tid, wid)；窗口没了会重新选一次窗口。"""
    for _ in range(2):
        r = osa(AS_OPEN_TAB, wid, url).strip()
        if r.isdigit():
            state["wid"] = wid
            return int(r), wid
        wid = pick_window(state, list_tabs())
    raise OSAError("找不到可用的 Chrome 窗口")


def activate_tab(tid):
    try:
        osa(AS_ACTIVATE, tid)
    except Exception as e:
        log.warning("激活标签页失败: %s", e)


def close_tab(tid):
    try:
        osa(AS_CLOSE, tid)
    except Exception as e:
        log.warning("关闭标签页失败: %s", e)


# ============================ HTML 解析 ============================

class _LinkParser(HTMLParser):
    """每个 <tr> 取第一个 http(s) 链接；第 2 列为 site。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._in_td, self._in_a = [], None, False, False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {"cells": [], "url": "", "title": ""}
        elif self._row is None:
            return
        elif tag in ("td", "th"):
            self._row["cells"].append("")
            self._in_td = True
        elif tag == "a" and not self._row["url"]:
            href = (dict(attrs).get("href") or "").strip()
            if href.lower().startswith(("http://", "https://")):
                self._row["url"] = href
                self._in_a = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_a = False
        elif tag in ("td", "th"):
            self._in_td = False
        elif tag == "tr" and self._row is not None:
            if self._row["url"]:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._row is None:
            return
        if self._in_td and self._row["cells"]:
            self._row["cells"][-1] += data
        if self._in_a:
            self._row["title"] += data


def parse_html(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        p = _LinkParser()
        p.feed(f.read())
    out = []
    for r in p.rows:
        cells = r["cells"]
        out.append({"url": r["url"], "title": " ".join(r["title"].split()),
                    "site": cells[1].strip() if len(cells) >= 2 else ""})
    return out


def resolve_html(arg_path, tabs, prev_html=None):
    if arg_path:
        p = os.path.realpath(os.path.expanduser(arg_path))
        return p if os.path.isfile(p) else None
    today = os.path.realpath(os.path.join(NEWS_DIR, f"TodayCNH_{datetime.now():%y%m%d}.html"))
    cands = [p for p in (html_path_of_tab(t["url"]) for t in tabs) if p and os.path.isfile(p)]
    if cands:
        return today if today in cands else max(cands, key=os.path.basename)
    if os.path.isfile(today):
        return today
    # 新增：txt2json 已把 HTML 移入 backup/backup，断点续跑时从那里找回
    if prev_html:
        for p in (prev_html,
                  os.path.join(NEWS_DIR, "backup", "backup", os.path.basename(prev_html))):
            if os.path.isfile(p):
                return os.path.realpath(p)
    files = [os.path.realpath(f) for f in glob.glob(os.path.join(NEWS_DIR, "TodayCNH_*.html"))
             if HTML_NAME_RE.match(os.path.basename(f))
             and time.time() - os.path.getmtime(f) <= HTML_MAX_AGE_HOURS * 3600]
    return max(files, key=os.path.getmtime) if files else None


# ============================ 状态 / 报告 ============================

def load_state(html_path, reset=False):
    st = None
    if not reset and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                st = json.load(f)
        except Exception as e:
            log.warning("状态文件损坏，重新开始: %s", e)
    if not st or st.get("html") != html_path:
        st = {"version": 1, "html": html_path, "created": now_str(), "items": {}, "order": [],
              "batches": [], "dirty": False, "finished": False}
    return st


def save_state(st):
    st["updated"] = now_str()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def sync_items(st, rows):
    """把 HTML 中的新链接并入状态（HTML 被重新生成、新增了链接时也能接上）。"""
    added = 0
    for r in rows:
        k = norm_key(r["url"])
        if k in st["items"]:
            continue
        ok, reason = classify(r["url"])
        st["items"][k] = {"url": r["url"], "title": r["title"], "site": r["site"],
                          "status": "pending" if (ok or not SKIP_UNSUPPORTED) else "skipped",
                          "reason": reason}
        st["order"].append(k)
        added += 1
    if added:
        st["finished"] = False
    return added


def items_with(st, *statuses):
    return [st["items"][k] for k in st["order"] if st["items"][k]["status"] in statuses]


def report_path(st):
    stem = os.path.splitext(os.path.basename(st["html"]))[0]
    return os.path.join(NEWS_DIR, f"BatchAuto_{stem}.html")   # 不以 TodayCNH_ 开头，避免被误识别


def write_report(st):
    groups = [
        ("未打开：News_Engine 不支持（可手动处理）", items_with(st, "skipped")),
        ("打开失败", items_with(st, "open_fail")),
        (f"经过 {LEFTOVER_MAX_BATCHES} 批流水线仍未被处理，已自动关闭", items_with(st, "left_closed")),
        ("遗留标签页（流水线跑过但仍未关闭，仍在 Chrome 中）",
         [i for i in items_with(st, "opened", "already_open") if i.get("left")]),
    ]
    parts = [f"<h1>全自动批处理报告</h1><p class='tip'>{html.escape(st['html'])} · 更新于 {now_str()}</p>"]
    for title, its in groups:
        if not its:
            continue
        parts.append(f"<h2>{html.escape(title)}（{len(its)}）</h2><ul>")
        for i in its:
            parts.append(f"<li><a href=\"{html.escape(i['url'], quote=True)}\" target=\"_blank\">"
                         f"{html.escape(i.get('title') or i['url'])}</a>"
                         f"<div class='meta'>{html.escape(i.get('site', ''))} · "
                         f"{html.escape(i.get('reason') or '')}</div></li>")
        parts.append("</ul>")
    parts.append("<h2>批次记录</h2><ul>")
    for b in st["batches"]:
        parts.append(f"<li>第 {b['no']} 批 · {b['pipeline']} · 新开 {b['opened']} · 状态 {b['status']} · "
                     f"遗留 {b.get('left', '-')} · {b['start']} · {b['minutes']} 分钟</li>")
    parts.append("</ul>")
    doc = ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'><title>全自动批处理报告</title>"
           "<style>body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:980px;margin:32px auto;"
           "padding:0 16px;color:#222}li{padding:8px 0;border-bottom:1px solid #eee;list-style:none}"
           "a{color:#0b57d0;text-decoration:none}a:visited{color:#7b1fa2}.meta,.tip{color:#888;font-size:12px}"
           "</style></head><body>" + "".join(parts) + "</body></html>")
    path = report_path(st)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(doc)
    os.replace(tmp, path)
    return path


# ============================ 流水线 ============================

def run_pipeline(path):
    log.info("启动流水线: %s", os.path.basename(path))
    try:
        p = subprocess.run(["osascript", path], capture_output=True, text=True,
                           timeout=PIPELINE_TIMEOUT or None)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", f"超过 {PIPELINE_TIMEOUT} 秒"
    out = [x.strip() for x in (p.stdout or "").splitlines() if x.strip()]
    err = (p.stderr or "").strip()
    if p.returncode != 0:
        return ("CANCELED" if "-128" in err else "ERROR"), err[-300:]
    if not out:
        return "UNKNOWN", ""
    return out[-1], ""


# ============================ 主流程 ============================

def main(args):
    global BATCH_SIZE, _LOCK_FP
    if args.batch_size:
        BATCH_SIZE = max(1, args.batch_size)

    if not AUTO_ENABLED and not args.force and not args.dry_run:
        if not args.from_hook:
            notify("全自动批处理开关未开启（AUTO_ENABLED = False），未执行任何操作", "orange", 3000)
        return 0

    _LOCK_FP = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_LOCK_FP, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if not args.from_hook:
            notify("全自动批处理已在运行中", "orange", 2500)
        return 1

    setup_logging()
    log.info("=" * 60)
    first_pipe = args.pipeline or DEFAULT_PIPELINE
    rest_pipe = REST_PIPELINE or first_pipe
    log.info("全自动批处理启动：首批流水线=%s，后续=%s，每批=%d", first_pipe, rest_pipe, BATCH_SIZE)
    for k in {first_pipe, rest_pipe}:
        if k not in PIPELINES or not os.path.isfile(PIPELINES[k]):
            dialog(f"流水线配置错误：{k}\n{PIPELINES.get(k, '（未定义）')}")
            return 1

    if args.from_hook:
        time.sleep(HOOK_START_DELAY)
    if stop_requested() and not args.dry_run:
        dialog(f"检测到停止文件，未执行任何操作：\n{STOP_FILE}\n\n删除该文件后再运行。")
        return 2

    try:
        if osa(AS_IS_RUNNING).strip() != "true":
            dialog("Google Chrome 没有运行。")
            return 1
        tabs = list_tabs()
    except OSAError as e:
        if "-1743" in str(e):
            dialog("没有控制 Chrome 的权限。\n请到「系统设置 → 隐私与安全性 → 自动化」里允许后重试。")
        else:
            dialog(f"无法读取 Chrome 标签页：\n{e}")
        return 1

    html_path = resolve_html(args.html, tabs)
    if not html_path:
        dialog(f"找不到 TodayCNH_YYMMDD.html：\nChrome 中未打开，{NEWS_DIR} 中也没有 "
               f"{HTML_MAX_AGE_HOURS} 小时内的文件。")
        return 1
    rows = parse_html(html_path)
    if not rows:
        dialog(f"{os.path.basename(html_path)} 中没有解析到任何新闻链接。")
        return 1

    state = load_state(html_path, reset=args.reset)
    sync_items(state, rows)
    save_state(state)
    total = len(state["order"])
    n_skip = len(items_with(state, "skipped"))
    n_pend = len(items_with(state, "pending"))
    log.info("%s：共 %d 条，待处理 %d，不支持跳过 %d", os.path.basename(html_path), total, n_pend, n_skip)

    if args.dry_run:
        for k in state["order"]:
            i = state["items"][k]
            print(f"[{i['status']:>12}] {i.get('site', ''):<10} {i['url']}  {i.get('reason') or ''}")
        print(f"\n共 {total} 条，待处理 {n_pend}，不支持跳过 {n_skip}")
        return 0

    notify(f"全自动批处理启动：共 {total} 条，待处理 {n_pend}，跳过 {n_skip}，每批 {BATCH_SIZE}", "blue", 3500)

    t_start = time.time()
    stop_reason = None
    pipe_runs = 0
    try:
        while True:
            if stop_requested():
                stop_reason = "检测到停止文件 stop_scpt.txt"
                break

            tabs = list_tabs()
            open_ids = {t["tid"] for t in tabs}
            # 之前打开过、现在已不在的标签页 → 已被流水线处理（或被关闭）
            for i in items_with(state, "opened", "already_open"):
                if i.get("tid") not in open_ids:
                    i["status"] = "done"

            batch_no = len(state["batches"]) + 1
            pending_keys = [k for k in state["order"] if state["items"][k]["status"] == "pending"]
            if SKIP_ALREADY_OPEN and pending_keys:
                open_map = {norm_key(t["url"]): t for t in tabs if is_target(t["url"])}
                for k in pending_keys:
                    if k in open_map:
                        state["items"][k].update(status="already_open", tid=open_map[k]["tid"],
                                                 batch=batch_no, reason="已在 Chrome 中打开")
                        state["dirty"] = True
                pending_keys = [k for k in pending_keys if state["items"][k]["status"] == "pending"]

            if not pending_keys and not state["dirty"]:
                state["finished"] = True
                break

            opened_now = []
            if pending_keys:
                existing = sum(1 for t in tabs if is_target(t["url"]))
                n = min(len(pending_keys), max(MIN_NEW_PER_BATCH, BATCH_SIZE - existing))
                wid = pick_window(state, tabs)
                notify(f"第 {batch_no} 批：打开 {n} 篇（剩余 {len(pending_keys)}，已有目标标签页 {existing}）",
                       "blue", 2500)
                fails = 0
                for k in pending_keys[:n]:
                    if stop_requested():
                        break
                    it = state["items"][k]
                    try:
                        tid, wid = open_tab(state, wid, it["url"])
                        fails = 0
                    except (OSAError, subprocess.TimeoutExpired, ValueError) as e:
                        fails += 1
                        it.update(status="open_fail", reason=str(e)[:200])
                        log.error("打开失败: %s | %s", it["url"], e)
                        if fails >= 3:
                            raise OSAError(f"连续 3 次打开标签页失败：{e}")
                        continue
                    it.update(status="opened", tid=tid, batch=batch_no, ts=now_str())
                    opened_now.append(tid)
                    state["dirty"] = True
                    save_state(state)
                    log.info("  已打开 [%d/%d] %s", len(opened_now), n, it["url"])
                    time.sleep(OPEN_INTERVAL)
                save_state(state)
                if stop_requested():
                    stop_reason = "检测到停止文件 stop_scpt.txt（本批标签页已打开，下次运行会先处理它们）"
                    break
                html_tab = find_html_tab(list_tabs(), state["html"])
                if html_tab:
                    activate_tab(html_tab["tid"])     # 回到 HTML 页，同时把该窗口提到最前
                time.sleep(AFTER_OPEN_WAIT)

            if not state["dirty"]:
                continue   # 本批全部打开失败，继续尝试剩余链接

            batch_tids = [i["tid"] for i in items_with(state, "opened", "already_open") if i.get("tid")]
            pipe_key = first_pipe if pipe_runs == 0 else rest_pipe
            t0 = time.time()
            status, detail = run_pipeline(PIPELINES[pipe_key])
            pipe_runs += 1
            rec = {"no": batch_no, "pipeline": pipe_key, "opened": len(opened_now), "status": status,
                   "detail": detail[:300], "start": datetime.fromtimestamp(t0).strftime("%m-%d %H:%M"),
                   "minutes": round((time.time() - t0) / 60, 1)}
            state["batches"].append(rec)
            log.info("第 %d 批流水线结束：%s %s（%.1f 分钟）", batch_no, status, detail, rec["minutes"])
            if status != "DONE":
                stop_reason = STATUS_TEXT.get(status, f"流水线返回未知状态：{status}") \
                    + (f"\n{detail}" if detail else "")
                break
            state["dirty"] = False

            # ---- 收尾：统计遗留标签页 ----
            open_ids = {t["tid"] for t in list_tabs()}
            still = [tid for tid in batch_tids if tid in open_ids]
            rec["left"] = len(still)
            for i in items_with(state, "opened", "already_open"):
                if i.get("tid") in open_ids:
                    i["left"] = i.get("left", 0) + 1
                    if CLOSE_STALE_LEFTOVERS and i["left"] >= LEFTOVER_MAX_BATCHES:
                        close_tab(i["tid"])
                        i.update(status="left_closed",
                                 reason=f"经过 {i['left']} 批流水线仍未被处理，已自动关闭")
                else:
                    i["status"] = "done"
            save_state(state)
            write_report(state)
            if batch_tids and len(still) == len(batch_tids):
                stop_reason = (f"第 {batch_no} 批的 {len(batch_tids)} 个标签页全部未被处理"
                               f"（流水线可能没有找到它们），为避免空转已停止。")
                break
            left_n = len(items_with(state, "pending"))
            notify(f"第 {batch_no} 批完成（遗留 {len(still)}），剩余待打开 {left_n} 篇", "green", 2500)
            time.sleep(BETWEEN_BATCH_WAIT)
    except OSAError as e:
        stop_reason = f"控制 Chrome 失败：{str(e)[:300]}"
    except Exception as e:
        log.exception("内部错误")
        stop_reason = f"内部错误：{e}"
    finally:
        save_state(state)
        rpt = write_report(state)

    mins, secs = divmod(int(time.time() - t_start), 60)
    cnt = lambda *s: len(items_with(state, *s))
    head = f"⏹ 已停止：{stop_reason}" if stop_reason else "✅ 所有新闻已全部处理完毕！"
    msg = (f"{head}\n\n"
           f"HTML：{os.path.basename(html_path)}\n"
           f"链接总数：{total}\n"
           f"已处理（标签页已关闭）：{cnt('done')}\n"
           f"不支持未打开：{cnt('skipped')}\n"
           f"仍待打开：{cnt('pending')}\n"
           f"遗留在 Chrome：{cnt('opened', 'already_open')}　自动关闭：{cnt('left_closed')}　"
           f"打开失败：{cnt('open_fail')}\n"
           f"本次批次：{pipe_runs}　用时：{mins} 分 {secs} 秒")
    if cnt("skipped", "left_closed", "open_fail") or any(i.get("left") for i in items_with(state, "opened")):
        msg += f"\n\n报告页：{rpt}"
    if stop_reason:
        msg += "\n\n再次运行会从断点继续（不会重复打开已打开过的链接）。"
        if stop_requested():
            msg += f"\n请先删除 {STOP_FILE}。"
    log.info(msg.replace("\n", " | "))
    dialog(msg)
    return 2 if stop_reason else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="新闻全自动批处理")
    ap.add_argument("--pipeline", choices=sorted(PIPELINES), help="首批使用的流水线（默认 DEFAULT_PIPELINE）")
    ap.add_argument("--html", help="指定 TodayCNH_*.html 路径（默认自动定位）")
    ap.add_argument("--batch-size", type=int, help="覆盖 BATCH_SIZE")
    ap.add_argument("--force", action="store_true", help="忽略 AUTO_ENABLED 开关强制运行")
    ap.add_argument("--from-hook", action="store_true", help="由前置程序调用：开关关闭/已在运行时静默退出")
    ap.add_argument("--reset", action="store_true", help="丢弃该 HTML 的断点进度，从头开始")
    ap.add_argument("--dry-run", action="store_true", help="只解析并打印分类结果，不打开任何标签页")
    a = ap.parse_args()
    keep = start_keep_awake()
    try:
        sys.exit(main(a))
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        if keep and keep.poll() is None:
            keep.terminate()