#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣 + IMDb 一次性抓取与回写
流程：
  剪贴板取名字 → 在 OVideos.json 找项目 →
  抓豆瓣(日期/评分/外文标题) → 写回 →
  用外文标题搜 IMDb → 抓 IMDb 评分 → 写回 → 结束
依赖: pyautogui, 以及同目录下你已有的 screenshot.py
"""

import os
import re
import sys
import time
import json
import glob
import subprocess
from pathlib import Path

PYTHON_CODE_DIR = '/Users/yanzhang/Coding/python_code'
sys.path.insert(0, PYTHON_CODE_DIR)

import pyautogui
from screenshot import ScreenDetector

# ================= 配置区域 =================
OVIDEOS_JSON  = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
DOWNLOADS_DIR = Path.home() / 'Downloads'

# —— 模板图 ——（input 用相对文件名，走 ScreenDetector 默认目录；popup 用绝对路径）
DOUBAN_INPUT_IMG = 'douban_input.png'
DOUBAN_POPUP_IMG = '/Users/yanzhang/Coding/python_code/Resource/douban_popup.png'
IMDB_INPUT_IMG   = 'imdb_input.png'
IMDB_POPUP_IMG   = '/Users/yanzhang/Coding/python_code/Resource/imdb_popup.png'

# —— 插件下载文件名模式 ——
DOUBAN_DOWNLOAD_GLOB = 'douban_result*.json'
IMDB_DOWNLOAD_GLOB   = 'imdb_result*.json'

# —— 等待时间（秒）——
WAIT_AFTER_PASTE      = 2
WAIT_POPUP_APPEAR     = 20
WAIT_PAGE_LOAD        = 4
WAIT_DOWNLOAD_TIMEOUT = 30
SECOND_CLICK_Y_OFFSET = 50   # 第二次点击相对图片中心的 Y 偏移（逻辑像素）
# ===========================================

pyautogui.FAILSAFE = True


# ------------------ 基础工具 ------------------
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def read_clipboard() -> str:
    """读取当前剪贴板内容（项目名）。"""
    p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
    out, _ = p.communicate()
    return out.decode('utf-8').strip()


def copy_to_clipboard(text):
    p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
    p.communicate(text.encode('utf-8'))


def clear_old_downloads(pattern):
    for f in glob.glob(str(DOWNLOADS_DIR / pattern)):
        try:
            os.remove(f)
        except Exception:
            pass


def wait_for_download(pattern, timeout):
    start = time.time()
    while time.time() - start < timeout:
        files = [f for f in glob.glob(str(DOWNLOADS_DIR / pattern))
                 if not f.endswith('.crdownload')]
        if files:
            time.sleep(0.5)
            return max(files, key=os.path.getmtime)
        time.sleep(0.5)
    return None


def move_to_trash(path):
    script = f'tell application "Finder" to delete (POSIX file "{path}" as alias)'
    subprocess.run(['osascript', '-e', script],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def click_image_center(detector, location, shape, y_offset=0):
    phys_cx = location[0] + shape[1] // 2
    phys_cy = location[1] + shape[0] // 2
    logic_x = int(phys_cx / detector.scale_factor)
    logic_y = int(phys_cy / detector.scale_factor) + y_offset
    pyautogui.click(logic_x, logic_y)
    print(f"点击(逻辑坐标): ({logic_x}, {logic_y})  y_offset={y_offset}")


# ------------------ 在 json 里按名字找项目 ------------------
def find_item_by_name(data, name):
    target = name.strip()
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if isinstance(item, dict) and str(item.get('name', '')).strip() == target:
                return category, idx, item
    return None, None, None


# ------------------ 写回逻辑 ------------------
def update_douban(item, scraped) -> bool:
    """写回日期 + 豆瓣评分。IMDB 字段不动。"""
    date   = str(scraped.get('date', '')).strip()
    douban = str(scraped.get('douban_rating', '')).strip()
    changed = False

    print("  ┌────────────── 豆瓣写回 ──────────────")
    # 日期：只在抓到完整 YYYY-MM-DD 时写入
    if re.match(r'\d{4}-\d{2}-\d{2}', date):
        item['date'] = date
        changed = True
        print(f"  │ 日期 date : {date}")
    else:
        print(f"  │ 日期未抓到/格式不符，保持原样（抓到：{date or '空'}）")

    # 豆瓣评分
    if douban:
        rating = item.get('评分')
        if not isinstance(rating, dict):
            rating = {}
            item['评分'] = rating
        old = str(rating.get('豆瓣', '')).strip()
        rating['豆瓣'] = douban
        changed = True
        if old and old != douban:
            print(f"  │ 豆瓣评分 : {old} -> {douban}")
        else:
            print(f"  │ 豆瓣评分 : {douban}")
    else:
        print("  │ 豆瓣评分 : 页面未抓到，保持原样")
    print("  └──────────────────────────────────────")
    return changed


def update_imdb(item, scraped) -> bool:
    """写回 IMDb 评分到 评分.IMDB 字段。"""
    imdb = str(scraped.get('imdb_rating', '')).strip()
    print("  ┌────────────── IMDb写回 ──────────────")
    if not imdb:
        print("  │ IMDb评分 : 页面未抓到，跳过写入")
        print("  └──────────────────────────────────────")
        return False

    rating = item.get('评分')
    if not isinstance(rating, dict):
        rating = {}
        item['评分'] = rating
    old = str(rating.get('IMDB', '')).strip()
    rating['IMDB'] = imdb
    if old and old != imdb:
        print(f"  │ IMDb评分 : {old} -> {imdb}")
    else:
        print(f"  │ IMDb评分 : {imdb}")
    print("  └──────────────────────────────────────")
    return True


# ------------------ 激活 Chrome 并切到目标站点 ------------------
def _activate_and_switch(keyword, open_url, label):
    print(f"\n===== 激活Chrome并查找 {label} 标签 =====")
    script = f'''
    set foundTab to missing value
    set targetWin to missing value
    set targetTabIdx to 0

    tell application "Google Chrome"
        activate
        delay 0.3
        repeat with w in every window
            set tabCount to count of tabs of w
            repeat with tIdx from 1 to tabCount
                set t to tab tIdx of w
                set tabUrl to URL of t as string
                if tabUrl contains "{keyword}" and tabUrl is not "" then
                    set foundTab to t
                    set targetWin to w
                    set targetTabIdx to tIdx
                    exit repeat
                end if
            end repeat
            if foundTab is not missing value then exit repeat
        end repeat

        if foundTab is not missing value then
            set index of targetWin to 1
            set active tab index of targetWin to targetTabIdx
            delay 0.2
            return "FOUND"
        else
            tell application "System Events"
                keystroke "t" using command down
                delay 0.5
                keystroke "{open_url}"
                delay 0.5
                key code 36
            end tell
            return "NOT_FOUND_OPENED"
        end if
    end tell
    '''
    proc = subprocess.run(["osascript", "-e", script],
                          capture_output=True, encoding="utf-8")
    result = proc.stdout.strip()
    time.sleep(1.8)
    if result == "FOUND":
        print(f"✅ 成功切换到 {label} 标签页\n")
    elif result == "NOT_FOUND_OPENED":
        print(f"✅ 未找到 {label} 标签，已打开新页面：{open_url}\n")
    else:
        print(f"⚠️ {label} 操作完成，但返回状态异常：{result}\n")


def activate_chrome_and_switch_to_douban():
    _activate_and_switch("douban.com",
                         "https://movie.douban.com/subject/1837856/",
                         "豆瓣")


def activate_chrome_and_switch_to_imdb():
    _activate_and_switch("imdb.com",
                         "https://www.imdb.com/",
                         "IMDb")


# ------------------ 通用抓取流程（豆瓣/IMDb 共用） ------------------
def process_page(input_detector, popup_img_path, download_glob, paste_text, label):
    """
    input_detector : 已经用对应 input 图创建好的 ScreenDetector
    popup_img_path : 弹窗模板图绝对路径
    download_glob  : 插件下载的文件名模式
    paste_text     : 要粘贴进搜索框的内容
    """
    print(f"\n----- 开始处理 {label} 页面 -----")

    # 1. 把要搜索的文字放进剪贴板
    copy_to_clipboard(paste_text)

    # 2. 循环等待 input 搜索框图片出现
    location, shape = None, None
    start = time.time()
    print(f"等待 {label} 输入框图片，最长 {WAIT_POPUP_APPEAR} 秒...")
    while time.time() - start < WAIT_POPUP_APPEAR:
        _, location, shape = input_detector.find_images_on_screen(threshold=0.9)
        if location:
            print(f"✅ 找到 {label} 搜索框")
            break
        time.sleep(0.5)
    if not location:
        print(f"❌ 未找到 {label} 搜索框，跳过。")
        return None

    # 3. 第一次点击：聚焦搜索框
    click_image_center(input_detector, location, shape, y_offset=0)
    time.sleep(0.5)

    # 4. 清空原有内容再粘贴（更稳）
    pyautogui.hotkey('command', 'a')
    time.sleep(0.1)
    pyautogui.hotkey('command', 'v')
    time.sleep(WAIT_AFTER_PASTE)

    # 5. 等待联想弹窗图片出现
    print(f"侦测 {label} 弹窗（联想结果）...")
    popup_detector = ScreenDetector(template_names=popup_img_path, clickValue='left')
    popup_found = False
    start = time.time()
    while time.time() - start < WAIT_POPUP_APPEAR:
        _, ploc, pshape = popup_detector.find_images_on_screen(threshold=0.9)
        if ploc:
            popup_found = True
            print(f"✅ 找到 {label} 弹窗")
            break
        time.sleep(0.3)
    if not popup_found:
        print(f"❌ 未找到 {label} 弹窗，跳过。")
        return None

    # 6. 第二次点击：选第一个联想结果（图片中心 Y+offset）
    click_image_center(input_detector, location, shape, y_offset=SECOND_CLICK_Y_OFFSET)

    # 7. 等待页面加载
    time.sleep(WAIT_PAGE_LOAD)

    # 8. 清旧下载，触发插件 Option+N
    clear_old_downloads(download_glob)
    pyautogui.hotkey('option', 'n')
    print("已触发 Option+N，等待插件下载结果...")

    # 9. 等待下载
    downloaded = wait_for_download(download_glob, WAIT_DOWNLOAD_TIMEOUT)
    if not downloaded:
        print(f"❌ {label} 下载超时，未获取到结果。")
        return None

    try:
        scraped = load_json(downloaded)
    except Exception as e:
        print(f"读取下载 json 失败: {e}")
        scraped = None

    move_to_trash(downloaded)
    return scraped


# ------------------ 主流程 ------------------
def main():
    print("=== 豆瓣 + IMDb 一次性抓取启动 ===")

    # 1. 读取剪贴板（项目名）
    name = read_clipboard()
    if not name:
        print("❌ 剪贴板为空，无法继续。")
        return
    print(f"📋 剪贴板内容（项目名）: {name}")

    # 2. 在 json 里找到对应项目
    data = load_json(OVIDEOS_JSON)
    category, idx, item = find_item_by_name(data, name)
    if item is None:
        print(f"❌ 未在 OVideos.json 中找到名为「{name}」的项目，程序结束。")
        return
    print(f"✅ 已定位项目 [{category}][{idx}]")

    # ========== 第一阶段：豆瓣 ==========
    activate_chrome_and_switch_to_douban()
    douban_detector = ScreenDetector(template_names=DOUBAN_INPUT_IMG, clickValue='left')
    douban_scraped = process_page(
        douban_detector, DOUBAN_POPUP_IMG, DOUBAN_DOWNLOAD_GLOB,
        paste_text=name, label="豆瓣"
    )

    foreign_title = ''
    if douban_scraped:
        foreign_title = str(douban_scraped.get('foreign_title', '')).strip()
        print(f"🎬 抓到外文标题: {foreign_title or '（空）'}")
        if update_douban(item, douban_scraped):
            save_json(OVIDEOS_JSON, data)
            print("💾 豆瓣数据已写回 OVideos.json。")
        else:
            print("豆瓣无有效变化，未写回。")
    else:
        print("⚠️ 豆瓣抓取失败。")

    # ========== 第二阶段：IMDb ==========
    if not foreign_title:
        print("\n❌ 未获得外文标题，无法搜索 IMDb，程序结束。")
        print("=== 结束 ===")
        return

    print(f"\n🔎 用外文标题「{foreign_title}」搜索 IMDb")
    activate_chrome_and_switch_to_imdb()
    imdb_detector = ScreenDetector(template_names=IMDB_INPUT_IMG, clickValue='left')
    imdb_scraped = process_page(
        imdb_detector, IMDB_POPUP_IMG, IMDB_DOWNLOAD_GLOB,
        paste_text=foreign_title, label="IMDb"
    )

    if imdb_scraped:
        print(f"⭐ 抓到 IMDb 评分: {imdb_scraped.get('imdb_rating', '') or '（空）'}")
        if update_imdb(item, imdb_scraped):
            save_json(OVIDEOS_JSON, data)
            print("💾 IMDb 数据已写回 OVideos.json。")
        else:
            print("IMDb 无有效变化，未写回。")
    else:
        print("⚠️ IMDb 抓取失败。")

    print("\n=== 全部完成，结束 ===")


if __name__ == '__main__':
    main()