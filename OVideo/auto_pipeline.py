#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全自动流水线（Ctrl+1）
  阶段1  退出 Chrome → open(CDP Chrome) → 等 Cloudflare 自动通过 → cdp fast 爬取 → 关闭 CDP Chrome
  阶段2  重开日常 Chrome → 循环扫描 date/date_re 为「年份 / 年份(待定)」的项目
         → 逐个调用 auto_douban_imdb.py 补全 → 仍待定则兜底写 {年份}-01-01

可选参数：
  --list          只列出当前待补全项目，不执行任何操作
  --skip-crawl    跳过阶段1（只做补全）
  --skip-detail   跳过阶段2（只爬取）

退出码：0=全部完成  1=致命错误  2=完成但有项目补全失败
"""
import os
import re
import sys
import json
import time
import random
import shutil
import atexit
import argparse
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.request import urlopen

try:
    import fcntl
except ImportError:
    fcntl = None

# ===================== 配置区 =====================
PYTHON       = sys.executable
CRAWLER_PY   = "/Users/yanzhang/Coding/python_code/OVideo/Crawl_shangxidq.py"
DETAIL_PY    = "/Users/yanzhang/Coding/python_code/JavaScript/douban_grabber/auto_douban_imdb.py"
JSON_PATH    = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
STATE_PATH   = os.path.expanduser("~/.auto_pipeline_state.json")   # 失败记录/冷却
LOG_DIR      = os.path.join(os.path.dirname(JSON_PATH), "logs")

USER_DATA_DIR = os.path.expanduser("~/.shangxidq_chrome_profile")  # 与 Crawl 脚本一致
CDP_PORT      = 9222
SITE_KEY      = "shangxidq.com"

# —— 阶段1：Chrome / Cloudflare ——
QUIT_CHROME_FIRST      = True    # 与你原流程一致：先退出所有 Chrome
FORCE_KILL_IF_STUCK    = True    # 优雅退出 20 秒仍未退出，则强杀
CF_WAIT_TIMEOUT        = 240     # 等 Cloudflare 自动通过的上限（秒）；超时也继续，爬虫自己还会再等
CF_STABLE_POLLS        = 3       # 连续 N 次判定"已通过"才算数
CF_POLL_INTERVAL       = 2.0
CHALLENGE_TITLE_WORDS  = ("just a moment", "请稍候", "稍等", "attention required",
                          "checking your browser", "verify", "安全检查")
CONTINUE_ON_CRAWL_FAIL = True    # 爬取失败也继续做阶段2（处理历史遗留的待定项）

# —— 第一站点：jjztq（直连爬取，无需 CDP / 预热）——
SHANGXIDQ_ENABLED    = True
SHANGXIDQ_CRAWLER_PY = "/Users/yanzhang/Coding/python_code/OVideo/Crawl_shangxidq.py"
SHANGXIDQ_ARGS       = []          # 可选，例如 ["pages=2"]；不要加 open / cdp
SHANGXIDQ_TIMEOUT    = 3600        # 秒。被拦截时脚本会弹 Chrome 等人工验证，需要留足时间

# —— 第二站点：jjztq（直连爬取，无需 CDP / 预热）——
JJZTQ_ENABLED    = True
JJZTQ_CRAWLER_PY = "/Users/yanzhang/Coding/python_code/OVideo/Crawl_jjztq.py"
JJZTQ_ARGS       = []          # 可选，例如 ["pages=2"]；不要加 open / cdp
JJZTQ_TIMEOUT    = 3600        # 秒。被拦截时脚本会弹 Chrome 等人工验证，需要留足时间

# —— 第三站点：312f（直连爬取，无需 CDP / 预热）——
PHASE312F_ENABLED = True
F312_CRAWLER_PY   = "/Users/yanzhang/Coding/python_code/OVideo/Crawl_312f.py"
F312_ARGS         = []
F312_TIMEOUT      = 3600

# —— 第四站点：sxkljc（直连爬取，无需 CDP / 预热）——
PHASESXKLJC_ENABLED = True
SXKLJC_CRAWLER_PY   = "/Users/yanzhang/Coding/python_code/OVideo/Crawl_sxkljc.py"
SXKLJC_ARGS         = []
SXKLJC_TIMEOUT      = 3600

# —— 第五站点：xb6v（直连爬取，无需 CDP / 预热）——
PHASEXB6V_ENABLED = True
XB6V_CRAWLER_PY   = "/Users/yanzhang/Coding/python_code/OVideo/Crawl_xb6v.py"
XB6V_ARGS         = []
XB6V_TIMEOUT      = 3600

# —— 阶段2：待补全判定 ——
# 匹配：2026 / 2026(待定) / 2026（待定） / 2026 待定 / 2026-待定 / 2026(TBD) ...
RE_PENDING = re.compile(
    r'^\s*((?:19|20)\d{2})\s*'
    r'(?:[-–—/·\s]*[(（\[【]?\s*(?:待定|未定|待确认|TBD)\s*[)）\]】]?)?\s*$', re.I)
PENDING_YEARS     = {"2026","2027"}         # None=任何年份；或如 {"2026", "2027"} 限定年份
FALLBACK_DATE     = "{year}-01-01"   # 补全后仍待定（低分/页面无变化）时写入的值
YEAR_TOLERANCE    = 0            # 传给豆瓣的目标年份范围：待定年份 ±N（0=只认该年）
MAX_ITEMS_PER_RUN = 0            # 单次最多处理多少个，0=不限

ITEM_TIMEOUT        = 480        # 单个项目最长耗时（秒）
MAX_ATTEMPTS        = 2          # 单个项目失败后本次最多尝试几次
ITEM_INTERVAL       = (3, 6)     # 项目之间随机间隔（秒），降低豆瓣风控概率
CONSECUTIVE_FAIL_ABORT = 5       # 连续失败 N 个就中止（多半是风控/Chrome 异常）
COOLDOWN_HOURS      = 6          # 失败项目在该时间内不再重试（跨次运行）
# ==================================================


# ---------------- 日志 ----------------
class Tee:
    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, s):
        self.stream.write(s)
        self.stream.flush()
        self.fh.write(s)
        self.fh.flush()

    def flush(self):
        self.stream.flush()
        self.fh.flush()

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"pipeline_{time.strftime('%Y%m%d_%H%M%S')}.log")
    fh = open(path, "a", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, fh)
    sys.stderr = Tee(sys.stderr, fh)
    print(f">>> [日志] 流水线日志: {path}（子脚本输出见各自日志/终端）")


def log(msg=""):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def banner(t):
    print("\n" + "=" * 70)
    print("  " + t)
    print("=" * 70, flush=True)


# ---------------- 通用工具 ----------------
def run_cmd(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        class _R:
            returncode, stdout, stderr = -1, "", str(e)
        return _R()


def wait_until(fn, timeout, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def notify(title, msg):
    run_cmd(["osascript",
             "-e", "on run argv",
             "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
             "-e", "end run", title, msg])


_LOCK_FH = None


def acquire_single_instance():
    global _LOCK_FH
    if fcntl is None:
        return
    _LOCK_FH = open("/tmp/auto_pipeline.lock", "a+")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("⚠️ 已有另一个流水线实例在运行，本次退出。")
        sys.exit(0)


_caff = None


def start_caffeinate():
    global _caff
    try:
        _caff = subprocess.Popen(["caffeinate", "-idmu"])
        atexit.register(lambda: _caff and _caff.terminate())
        log("已开启防休眠 (caffeinate)")
    except Exception as e:
        log(f"无法启动 caffeinate: {e}")


@contextmanager
def data_lock():
    """与 Crawl 脚本共用同一把文件锁，避免同时写 OVideos.json"""
    if fcntl is None:
        yield
        return
    fh = open(JSON_PATH + ".lock", "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


# ---------------- JSON 读写 ----------------
def load_json():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        txt = f.read()
    if not txt.strip():
        raise ValueError("OVideos.json 为空")
    data = json.loads(txt)
    if not isinstance(data, dict):
        raise ValueError("OVideos.json 顶层不是 dict")
    return data


def save_json(data):
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JSON_PATH)


_backed_up = False


def backup_once():
    global _backed_up
    if _backed_up:
        return
    try:
        shutil.copy2(JSON_PATH, JSON_PATH + ".pipeline.bak")
        _backed_up = True
        log("已备份 OVideos.json -> OVideos.json.pipeline.bak")
    except Exception as e:
        log(f"备份失败（继续）: {e}")


# ---------------- 待补全判定 ----------------
def pending_year(v):
    if v is None:
        return None
    m = RE_PENDING.match(str(v))
    if not m:
        return None
    y = m.group(1)
    if PENDING_YEARS and y not in PENDING_YEARS:
        return None
    return y

def strip_year_suffix(name: str, year: str) -> str:
    """'陷阱2026' + '2026' -> '陷阱'；只去掉与待定年份一致的末尾年份"""
    s = str(name or "").strip()
    pat = re.compile(
        r'^(?P<n>.*?\S)[\s\-－—_·]*[\(（\[【]?\s*' + re.escape(year) +
        r'\s*[\)）\]】]?$')
    m = pat.match(s)
    return m.group("n").strip() if m else s

def scan_pending(data):
    out, seen = [], set()
    for group, items in data.items():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", "")).strip()
            if not name or name in seen:
                continue
            year = pending_year(it.get("date"))   # 只判断 date，忽略 date_re
            if year:
                seen.add(name)
                out.append({"group": group, "name": name, "year": year})
    return out


def apply_fallback(name):
    """补全后该名字下仍是"待定"的字段 → 写成 {年份}-01-01。返回变更说明列表。"""
    changes = []
    with data_lock():
        data = load_json()
        for group, items in data.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict) or str(it.get("name", "")).strip() != name:
                    continue
                for field in ("date",):
                    y = pending_year(it.get(field))
                    if y:
                        new = FALLBACK_DATE.format(year=y)
                        changes.append(f"{group}/{field}: {it.get(field)!r} -> {new!r}")
                        it[field] = new
        if changes:
            backup_once()
            save_json(data)
    return changes


# ---------------- 失败记录 / 冷却 ----------------
CRAWL_DONE_PATH = os.path.expanduser("~/.auto_pipeline_crawl_done.json")

def load_crawl_done():
    try:
        with open(CRAWL_DONE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def crawl_done_today(site):
    """该站点今天是否已成功爬取过"""
    return load_crawl_done().get(site) == datetime.now().strftime("%Y-%m-%d")

def mark_crawl_done(site):
    """爬取成功后调用，记录今天的日期"""
    d = load_crawl_done()
    d[site] = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(CRAWL_DONE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"保存爬取标记失败: {e}")
        
def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"保存状态文件失败: {e}")


def in_cooldown(state, name):
    e = state.get(name)
    if not e:
        return False
    try:
        last = datetime.fromisoformat(e["last"])
    except Exception:
        return False
    return datetime.now() - last < timedelta(hours=COOLDOWN_HOURS)


# ---------------- Chrome 控制 ----------------
def chrome_main_running():
    return run_cmd(["pgrep", "-x", "Google Chrome"]).returncode == 0


def cdp_proc_pattern():
    return f"user-data-dir={USER_DATA_DIR}"


def cdp_proc_running():
    return run_cmd(["pgrep", "-f", cdp_proc_pattern()]).returncode == 0


def cdp_alive(timeout=1.5):
    try:
        with urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=timeout) as r:
            json.loads(r.read().decode("utf-8", "ignore"))
        return True
    except Exception:
        return False


def quit_chrome():
    if not chrome_main_running():
        return
    log("正在退出 Chrome ...")
    run_cmd(["osascript", "-e", 'quit app "Google Chrome"'])
    if wait_until(lambda: not chrome_main_running(), 20):
        time.sleep(1)
        return
    if FORCE_KILL_IF_STUCK:
        log("Chrome 20 秒内未退出，强制结束")
        run_cmd(["pkill", "-x", "Google Chrome"])
        wait_until(lambda: not chrome_main_running(), 8)
    time.sleep(1)


def stop_cdp_chrome():
    """只结束脚本专用 profile 的 Chrome，不影响其它实例"""
    if not (cdp_alive() or cdp_proc_running()):
        return
    log("正在关闭爬虫专用 Chrome（CDP）...")
    run_cmd(["pkill", "-f", cdp_proc_pattern()])
    if not wait_until(lambda: not cdp_proc_running(), 15):
        run_cmd(["pkill", "-9", "-f", cdp_proc_pattern()])
        wait_until(lambda: not cdp_proc_running(), 5)
    time.sleep(1)


def cf_passed_once():
    try:
        with urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=2) as r:
            tabs = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return False
    for t in tabs:
        if t.get("type") != "page":
            continue
        if SITE_KEY not in (t.get("url") or ""):
            continue
        title = (t.get("title") or "").strip().lower()
        if not title:
            continue
        if any(w in title for w in CHALLENGE_TITLE_WORDS):
            continue
        return True
    return False


def wait_cloudflare_pass():
    log(f"等待 Cloudflare 验证自动通过（最长 {CF_WAIT_TIMEOUT}s；若卡住请在弹出的窗口里手动勾选）...")
    start, stable, hinted = time.time(), 0, False
    while time.time() - start < CF_WAIT_TIMEOUT:
        stable = stable + 1 if cf_passed_once() else 0
        if stable >= CF_STABLE_POLLS:
            log("✅ Cloudflare 验证已通过")
            return True
        if not hinted and time.time() - start > 25:
            log("   ... 25 秒仍未通过，可能需要你手动点一下验证框")
            hinted = True
        time.sleep(CF_POLL_INTERVAL)
    log("⚠️ 等待超时，仍继续启动爬虫（爬虫自身还会再等待验证）")
    return False


def ensure_normal_chrome():
    """启动/激活你平时的 Chrome（带插件、已登录豆瓣），并确认 AppleScript 可控"""
    log("启动日常 Chrome ...")
    run_cmd(["open", "-a", "Google Chrome"])
    wait_until(chrome_main_running, 20)

    def responsive():
        r = run_cmd(["osascript", "-e", 'tell application "Google Chrome" to count of windows'], 10)
        return r.returncode == 0 and r.stdout.strip().isdigit()

    wait_until(responsive, 25, 1.0)
    r = run_cmd(["osascript", "-e", 'tell application "Google Chrome" to count of windows'], 10)
    if r.returncode == 0 and r.stdout.strip() == "0":
        run_cmd(["osascript", "-e", 'tell application "Google Chrome" to make new window'])
    time.sleep(3)


# ---------------- 阶段1：爬取 ----------------
def phase_crawl():
    banner("阶段 1/2：爬取 shangxidq（Cloudflare + CDP + fast）")
    try:
        if cdp_alive():
            log("检测到调试端口已在监听，直接复用")
        else:
            if QUIT_CHROME_FIRST:
                quit_chrome()
            log("启动爬虫专用 Chrome（open）...")
            subprocess.run([PYTHON, CRAWLER_PY, "open"])
            if not wait_until(cdp_alive, 45, 1.0):
                log("❌ 调试端口未就绪，放弃爬取。")
                return False
        wait_cloudflare_pass()
        log("开始爬取（cdp fast）...")
        rc = subprocess.run([PYTHON, CRAWLER_PY, "cdp", "fast"]).returncode
        log(f"爬取脚本结束，退出码 {rc}")
        return rc == 0
    finally:
        stop_cdp_chrome()

def run_direct_crawler(title, script, args, timeout):
    banner(f"站点爬取：{title}（直连，被拦截时自动弹出 Chrome）")
    if not os.path.exists(script):
        log(f"❌ 找不到爬虫脚本: {script}")
        return False
    cmd = [PYTHON, script] + list(args)
    log(f"开始爬取 {title}: " + " ".join(cmd))
    try:
        rc = subprocess.run(cmd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        log(f"⏱ {title} 爬取超过 {timeout}s，已终止")
        return False
    log(f"{title} 爬取脚本结束，退出码 {rc}")
    return rc == 0

def phase_crawl_shangxidq():
    return run_direct_crawler("shangxidq", SHANGXIDQ_CRAWLER_PY, SHANGXIDQ_ARGS, SHANGXIDQ_TIMEOUT)

def phase_crawl_jjztq():
    return run_direct_crawler("jjztq", JJZTQ_CRAWLER_PY, JJZTQ_ARGS, JJZTQ_TIMEOUT)

def phase_crawl_312f():
    return run_direct_crawler("312f", F312_CRAWLER_PY, F312_ARGS, F312_TIMEOUT)

def phase_crawl_sxkljc():
    return run_direct_crawler("sxkljc", SXKLJC_CRAWLER_PY, SXKLJC_ARGS, SXKLJC_TIMEOUT)

def phase_crawl_xb6v():
    return run_direct_crawler("xb6v", XB6V_CRAWLER_PY, XB6V_ARGS, XB6V_TIMEOUT)

# ---------------- 阶段2：补全 ----------------
def run_detail_once(name, year):
    y = int(year)
    years = [str(v) for v in range(y - YEAR_TOLERANCE, y + YEAR_TOLERANCE + 1)]
    search = strip_year_suffix(name, year)          # 新增：检索用名（不含年份）
    cmd = [PYTHON, DETAIL_PY,
           "--name", name,                          # JSON 定位仍用原名
           "--search", search,                      # 新增：豆瓣/IMDb 搜索用名
           "--years", ",".join(years)]
    try:
        return subprocess.run(cmd, timeout=ITEM_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        log(f"⏱ 单项超时（{ITEM_TIMEOUT}s），已终止")
        return -9


def phase_detail(site=""):
    banner(f"豆瓣 / IMDb 补全待定项目{'（' + site + ' 之后）' if site else ''}")
    res = {"ok": [], "fallback": [], "failed": [], "skipped": []}
    try:
        pend0 = scan_pending(load_json())
    except Exception as e:
        log(f"❌ 读取 OVideos.json 失败: {e}")
        return None
    log(f"当前待补全项目 {len(pend0)} 个: " + "、".join(p["name"] for p in pend0[:15])
        + (" ..." if len(pend0) > 15 else ""))
    if not pend0:
        log("没有需要补全的项目 ✅")
        return res

    ensure_normal_chrome()
    state, done = load_state(), set()
    consecutive_fail, n = 0, 0

    while True:
        try:
            data = load_json()
        except Exception as e:
            log(f"❌ 读取 OVideos.json 失败: {e}")
            break
        cands = []
        for p in scan_pending(data):
            if p["name"] in done:
                continue
            if in_cooldown(state, p["name"]):
                done.add(p["name"])
                res["skipped"].append(p["name"])
                log(f"⏭ 「{p['name']}」近期失败过，冷却中（{COOLDOWN_HOURS}h），本次跳过")
                continue
            cands.append(p)
        if not cands:
            break
        if MAX_ITEMS_PER_RUN and n >= MAX_ITEMS_PER_RUN:
            log(f"已达到单次上限 {MAX_ITEMS_PER_RUN} 个，停止（剩余下次继续）")
            break

        p = cands[0]
        name, year = p["name"], p["year"]
        done.add(name)
        n += 1
        log(f"\n━━━ [{n}] {name}  (待定年份 {year}，剩余约 {len(cands)} 个) ━━━")

        rc = -1
        for attempt in range(1, MAX_ATTEMPTS + 1):
            rc = run_detail_once(name, year)
            if rc in (0, 2):          # 0=全完成  2=豆瓣成功但 IMDb 失败（豆瓣数据已写回）
                break
            log(f"⚠️ 第 {attempt}/{MAX_ATTEMPTS} 次失败（退出码 {rc}）")
            if attempt < MAX_ATTEMPTS:
                time.sleep(5)

        if rc in (0, 2):
            consecutive_fail = 0
            state.pop(name, None)
            try:
                still = any(q["name"] == name for q in scan_pending(load_json()))
            except Exception:
                still = False
            if still:
                changes = apply_fallback(name)
                log("🛟 补全后日期仍是待定（评分偏低/页面无具体日期），已兜底写入:")
                for c in changes:
                    log("     " + c)
                res["fallback"].append(name)
            else:
                res["ok"].append(name)
                log(f"✅ 「{name}」补全完成" + ("（IMDb 未取到）" if rc == 2 else ""))
        else:
            consecutive_fail += 1
            e = state.setdefault(name, {"fails": 0})
            e["fails"] = e.get("fails", 0) + 1
            e["last"] = datetime.now().isoformat(timespec="seconds")
            res["failed"].append(name)
            log(f"❌ 「{name}」补全失败，已记录（不再本次重试）")
            if consecutive_fail >= CONSECUTIVE_FAIL_ABORT:
                log(f"🛑 连续失败 {consecutive_fail} 个，疑似豆瓣风控/Chrome 异常，中止阶段2")
                break

        save_state(state)
        time.sleep(random.uniform(*ITEM_INTERVAL))

    save_state(state)
    return res


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出待补全项目")
    ap.add_argument("--skip-crawl", action="store_true", help="跳过所有站点爬取")
    ap.add_argument("--skip-detail", action="store_true", help="跳过所有补全")
    ap.add_argument("--skip-jjztq", action="store_true", help="本次不跑 jjztq")
    ap.add_argument("--skip-312f", action="store_true", help="本次不跑 312f")
    ap.add_argument("--skip-shangxidq", action="store_true", help="本次跳过 shangxidq（爬取+补全）")
    ap.add_argument("--skip-sxkljc", action="store_true", help="本次不跑 sxkljc")
    ap.add_argument("--skip-xb6v", action="store_true", help="本次不跑 xb6v")
    ap.add_argument("--force-crawl", action="store_true",
                    help="忽略今日标记，强制重新爬取所有站点")
    args = ap.parse_args()

    if args.list:
        for p in scan_pending(load_json()):
            print(f"[{p['group']}] {p['name']}  ({p['year']})")
        return 0

    setup_logging()
    acquire_single_instance()
    start_caffeinate()
    t0 = time.time()

    # 站点按顺序执行：每个站点 = 爬取 → 补全
    sites = [
    ("shangxidq", phase_crawl_shangxidq, not args.skip_shangxidq),
    ("jjztq", phase_crawl_jjztq, JJZTQ_ENABLED and not args.skip_jjztq),
    ("312f", phase_crawl_312f, PHASE312F_ENABLED and not args.skip_312f),
    ("sxkljc", phase_crawl_sxkljc, PHASESXKLJC_ENABLED and not args.skip_sxkljc),
    ("xb6v", phase_crawl_xb6v, PHASEXB6V_ENABLED and not args.skip_xb6v),
]

    crawl_status, detail_res = {}, {}
    try:
        for site, crawl_fn, enabled in sites:
            if not enabled:
                log(f"[{site}] 已通过参数或配置禁用，跳过（爬取 + 补全）")
                continue
            if not args.skip_crawl:
                if not args.force_crawl and crawl_done_today(site):
                    log(f"[{site}] 今天已成功爬取过，跳过爬取，直接进入补全")
                    crawl_status[site] = "cached"
                else:
                    ok = crawl_fn()
                    crawl_status[site] = ok
                    if ok:
                        mark_crawl_done(site)      # 只有成功才打标记
                    elif not CONTINUE_ON_CRAWL_FAIL:
                        notify("流水线中止", f"{site} 爬取失败")
                        return 1

            if not args.skip_detail:
                detail_res[site] = phase_detail(site)
    except KeyboardInterrupt:
        log("用户中断 (Ctrl+C)")
        return 1

    banner("流水线结束")
    log(f"总耗时 {int((time.time() - t0) // 60)} 分 {int((time.time() - t0) % 60)} 秒")

    code = 0
    for site, ok in crawl_status.items():
        if ok == "cached":
            log(f"[{site}] 爬取: 今日已完成，已跳过")
        else:
            log(f"[{site}] 爬取: {'成功' if ok else '失败/有异常'}")
    for site, res in detail_res.items():
        if res is None:
            code = 1
            continue
        log(f"[{site}] 补全成功 {len(res['ok'])}；兜底日期 {len(res['fallback'])}；"
            f"失败 {len(res['failed'])}；冷却跳过 {len(res['skipped'])}")
        if res["failed"]:
            log(f"[{site}] 失败项目: " + "、".join(res["failed"]))
            code = code or 2

    total_fail = sum(len(r["failed"]) for r in detail_res.values() if r)
    notify("流水线完成" if code == 0 else "流水线完成（有失败）",
           f"站点 {len(detail_res)} 个 / 补全失败 {total_fail}")
    return code


if __name__ == "__main__":
    sys.exit(main())