# -*- coding: utf-8 -*-
"""
jjztq.cn 单个详情页抓取工具（规则与 Crawl_jjztq.py 完全一致，直接复用其代码）

用法：
    python Crawl_jjztq_single.py                         # 交互：输入 URL → 选分类 → 抓取，可连续多条
    python Crawl_jjztq_single.py <URL> <分类>            # 直接抓一条后退出；分类: movie/drama/anime/show 或 1-4
附加参数（可组合）：
    force    命中过滤规则（年份/地区/黑名单/集数等）时不询问，直接强制抓取
    strict   命中过滤规则时不询问，直接跳过
    cdp / browser / nobrowser / headless   同 Crawl_jjztq.py
默认：命中过滤规则时询问是否强制抓取；白名单影片自动放行。
"""

import os
import sys
import json
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Crawl_jjztq as core

GROUP_CHOICES = [("1", "Movie", "电影"), ("2", "Drama", "电视剧"),
                 ("3", "Anime", "动漫"), ("4", "Show", "综艺")]
GROUP_ALIASES = {}
for _k, _g, _cn in GROUP_CHOICES:
    GROUP_ALIASES[_k] = _g
    GROUP_ALIASES[_g.lower()] = _g
    GROUP_ALIASES[_cn] = _g
GROUP_ALIASES.update({"剧集": "Drama", "电视": "Drama", "动画": "Anime", "番剧": "Anime", "综": "Show"})

QUIT_WORDS = ("q", "quit", "exit", "退出")
_snapshotted = False


def _log_only(text):
    """把用户输入写进日志文件（终端已回显，不重复打印）"""
    if isinstance(sys.stdout, core.DualLogger):
        try:
            sys.stdout.log_file.write(text + "\n")
            sys.stdout.log_file.flush()
        except Exception:
            pass

def ask(prompt):
    try:
        ans = input(prompt)
    except EOFError:
        print()
        return None
    _log_only(ans)
    return ans

def confirm(prompt):
    ans = ask(prompt)
    return bool(ans) and ans.strip().lower() in ("y", "yes", "是", "确定")

def looks_like_url(s):
    s = (s or "").strip().lower()
    return s.startswith(("http://", "https://", "//")) or core.SITE_HOST in s or "/zt/" in s

def normalize_input_url(raw):
    """返回 (url, 错误信息)；统一成 DOMAIN + path，保证与列表爬虫的 URL 去重一致"""
    u = (raw or "").strip().strip("'\"<>“”‘’ ")
    if not u:
        return "", "URL 为空"
    if u.startswith("//"):
        u = "http:" + u
    elif u.startswith("/"):
        u = core.DOMAIN + u
    elif not u.lower().startswith(("http://", "https://")):
        u = "http://" + u
    p = urlparse(u)
    if not core._is_site_url(u):
        return "", f"不是 {core.SITE_HOST} 的链接：{p.netloc or u}"
    if not p.path or p.path == "/":
        return "", "这是首页，不是详情页"
    url = core.DOMAIN + p.path + (f"?{p.query}" if p.query else "")
    return url, ""

def lookup_hint(url):
    """只读查看该 URL 是否已收录，用于提示默认分类"""
    try:
        data = core._read_json_strict(core.JSON_PATH)
    except Exception:
        return None
    target = core.normalize_url(url)
    for g in core.ALL_GROUPS:
        for item in data.get(g, []) or []:
            for k in core._url_keys_sorted(item):
                if core.normalize_url(item.get(k, "")) == target:
                    print(f"  ℹ️ 该链接已收录：「{item.get('name')}」（{g}），本次将执行更新逻辑")
                    return g
    return None

def choose_group(hint=None):
    print("  请选择分类：")
    for k, g, cn in GROUP_CHOICES:
        mark = "   ← 库中已在此分类（回车默认）" if g == hint else ""
        print(f"    {k}) {g:<6} {cn}{mark}")
    while True:
        tip = f"（回车 = {hint}）" if hint else ""
        raw = ask(f"  输入编号或名称{tip}，q 取消: ")
        if raw is None:
            return None
        s = raw.strip().lower()
        if not s and hint:
            return hint
        if s in QUIT_WORDS:
            return None
        if s in GROUP_ALIASES:
            return GROUP_ALIASES[s]
        print("  ✗ 无效输入，请输入 1-4 或 Movie/Drama/Anime/Show")

def make_on_block(mode):
    if mode == "force":
        return lambda reason: True
    if mode == "strict":
        return None
    def _ask(reason):
        return confirm(f"    ❓ 命中规则「{reason}」，是否仍强制抓取？[y/N]: ")
    return _ask

def check_detail_pattern(url, mode):
    if core.DETAIL_URL_PATTERN.search(urlparse(url).path):
        return True
    print(f"  ⚠️ 该链接不像详情页（通常形如 {core.DOMAIN}/zt/12345.html）")
    if mode == "force":
        return True
    if mode == "strict":
        return False
    return confirm("  仍要继续抓取吗？[y/N]: ")

def run_one(url, group, on_block):
    """每条单独加锁 → 读取最新数据 → 处理 → 释放锁，空闲等待输入时不阻塞其他爬虫"""
    global _snapshotted
    result = "failed"
    core.acquire_run_lock()
    try:
        data = core.load_existing(core.JSON_PATH)
        if not _snapshotted:
            core.snapshot_backup(core.JSON_PATH)
            _snapshotted = True
        print(f"\n[单页抓取] 分类: {group}  <- {url}")
        result = core.process_detail(data, url, group, header=f"  {url}", on_block=on_block)
    except core.ConcurrentWriteError as e:
        print(f"\n⛔ {e}")
    finally:
        core.release_run_lock()
    print(f"\n>>> 结果：{core.RESULT_LABELS.get(result, result)}")
    return result

def main():
    core.setup_logging(tag="single")
    core.parse_cli()                         # 处理 open / cdp / browser / headless / nobrowser
    raw_args = sys.argv[1:]
    flags = {a.lower().lstrip("-") for a in raw_args}
    mode = "force" if "force" in flags else ("strict" if "strict" in flags else "ask")
    on_block = make_on_block(mode)
    cli_url = next((a for a in raw_args if looks_like_url(a)), None)
    cli_group = next((GROUP_ALIASES[a.lower()] for a in raw_args if a.lower() in GROUP_ALIASES), None)

    os.makedirs(core.IMG_DIR, exist_ok=True)
    print(f">>> [单页模式] 规则处理方式：{ {'ask': '命中过滤规则时询问', 'force': '全部强制抓取', 'strict': '命中即跳过'}[mode] }")

    try:
        if cli_url:
            url, err = normalize_input_url(cli_url)
            if err:
                print(f"  ✗ {err}")
                return
            if not check_detail_pattern(url, mode):
                return
            group = cli_group or choose_group(lookup_hint(url))
            if group:
                run_one(url, group, on_block)
            return

        while True:
            raw = ask("\n请输入详情页 URL（直接回车或 q 退出）: ")
            if raw is None or raw.strip().lower() in ("",) + QUIT_WORDS:
                break
            url, err = normalize_input_url(raw)
            if err:
                print(f"  ✗ {err}")
                continue
            if not check_detail_pattern(url, mode):
                continue
            group = choose_group(lookup_hint(url))
            if not group:
                print("  已取消")
                continue
            run_one(url, group, on_block)
    except KeyboardInterrupt:
        print("\n>>> 用户中断（已处理的条目均已实时保存）")
    finally:
        core._fetcher.close()
        core.release_run_lock()
        print(">>> 已退出单页抓取工具")

if __name__ == "__main__":
    main()