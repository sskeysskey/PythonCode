# -*- coding: utf-8 -*-
"""
单链接抓取：输入 dzfwjd 详情页 -> 选择 1=电影 / 2=电视剧 -> 抓取并写入 OVideos.json
依赖：与 Crawl_dzfwjd.py 放在同一目录
用法：python Crawl_dzfwjd_single.py
"""
import re
import os

import Crawl_dzfwjd as dz     # 复用原脚本的全部抓取/解析/合并逻辑

TYPE_MAP = {"1": "Movie", "2": "Drama"}
RESULT_TEXT = {
    "new":      "✅ 新增成功",
    "updated":  "✅ 已更新",
    "moved":    "↔ 线路位置已调整",
    "nochange": "- 无变更（库中已是最新）",
    "skip":     "- 已跳过",
    "fail":     "✗ 抓取失败",
}


def ask_url():
    while True:
        raw = input("请输入详情页地址（如 https://www.dzfwjd.com/movie/336701.html）: ").strip()
        if not raw:
            continue
        m = re.search(r"/movie/(\d+)\.html", raw)
        if not m or not dz.is_site_url(raw):
            print("  ✗ 不是有效的 dzfwjd 详情页地址，请重新输入")
            continue
        return f"{dz.DOMAIN}/movie/{m.group(1)}.html"


def ask_type():
    while True:
        c = input("类型：1 = 电影，2 = 电视剧，请输入数字: ").strip()
        if c in TYPE_MAP:
            return TYPE_MAP[c]
        print("  ✗ 只能输入 1 或 2")


def relax_filters_for_single():
    """单条手动抓取：关闭批量模式专用的过滤，避免手动指定的内容被误拦"""
    dz.BLACKLIST_NAMES = []                              # 名称黑名单
    dz.ALLOWED_YEARS = {str(y) for y in range(1900, 2101)}   # 年份不限（想限制就改这里）
    dz.ALLOWED_YEARS_BY_GROUP = {}
    dz.PREFILTER_BY_LIST_YEAR = False
    dz.MAX_EPISODES_BY_GROUP = {}                        # 集数上限
    dz.region_block_reason = lambda rec, fr: None        # 地区屏蔽


def prepare_single_session():
    """单条模式：全程使用已验证的 Chrome 标签页，不走 curl_cffi 直连，避免 cookie/UA/TLS 不一致导致反复验证。"""
    # 1. 不读取、不写入 cookie 缓存，并删除旧缓存
    dz.USE_COOKIE_CACHE = False
    try:
        os.remove(dz.COOKIE_CACHE_FILE)
        print(">>> 已删除旧的 cookie 缓存")
    except FileNotFoundError:
        pass

    # 2. 直连关闭，所有 HTML 请求都走浏览器（图片仍可直连）
    dz._fetcher.direct_disabled = True

    # 3. 只附着，不自动点击、不自启浏览器（与原程序 cdp 模式一致）
    dz.AUTO_CLICK_TURNSTILE = False
    dz.AUTO_LAUNCH_CDP = False
    dz.USE_CDP = True

    if not dz.cdp_alive():
        print(">>> 未检测到调试 Chrome，正在启动 ...")
        if not dz.launch_chrome_for_cdp(open_url=True, hint=False):
            raise SystemExit("无法启动调试 Chrome，请手动执行 python Crawl_dzfwjd.py open")
        print(">>> 请在弹出的 Chrome 中通过一次验证，然后按回车继续。")
        input()

def main():
    url = ask_url()
    group = ask_type()

    relax_filters_for_single()
    dz.snapshot_backup(dz.JSON_PATH)

    prepare_single_session()

    store = dz.DataStore(dz.JSON_PATH)
    store.initial_load()

    print(f"\n>>> 开始抓取：{url}  -> 分类 {group}\n")
    try:
        # 名称由详情页 h1 解析，这里先占位；列表信息为空、图片由详情页取
        status = dz.process_item(store, "(单条)", ("详情页", "", url, "", ""), group, [])
    finally:
        dz._fetcher.close()

    print(f"\n>>> 结果：{RESULT_TEXT.get(status, status)}")
    if status == "fail":
        print("    提示：若是验证/超时问题，先执行 python Crawl_dzfwjd.py open 过验证后重试")


if __name__ == "__main__":
    main()