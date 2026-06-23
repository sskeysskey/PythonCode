#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣信息自动抓取与回写 —— 主控循环
依赖: pyautogui, 以及同目录下你已有的 screenshot.py
"""

import os
import sys
import time
import json
import glob
import subprocess
from pathlib import Path

# 让脚本能 import 你已有的 screenshot.py
PYTHON_CODE_DIR = '/Users/yanzhang/Coding/python_code'
sys.path.insert(0, PYTHON_CODE_DIR)

import pyautogui
from screenshot import ScreenDetector   # 复用你已有的检测/缩放逻辑

# ================= 配置区域 =================
OVIDEOS_JSON     = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
DOWNLOADS_DIR    = Path.home() / 'Downloads'
STOP_FILE        = Path.home() / 'Desktop' / 'stop_scpt.txt'
DOUBAN_INPUT_IMG = 'douban_input.png'        # 位于 Resource 目录里的模板图
DOWNLOAD_GLOB    = 'douban_result*.json'      # 插件下载的文件名模式

# —— 各种等待时间（秒），按你机器/网速调整 ——
WAIT_AFTER_PASTE      = 2     # 粘贴名字后等待联想下拉出现
WAIT_PAGE_LOAD        = 4     # 点击搜索结果后等待页面加载
WAIT_DOWNLOAD_TIMEOUT = 30    # 等待插件下载 json 的最长时间
SECOND_CLICK_Y_OFFSET = 50    # 第二次点击相对图片中心的 Y 偏移（逻辑像素）

TYPE_NAME_INTO_SEARCH = True  # 是否把 name 粘贴进搜索框；不需要可改 False
# ===========================================

pyautogui.FAILSAFE = True


def check_stop_file() -> bool:
    """检测桌面是否有 stop_scpt.txt，有则删除并返回 True。"""
    if STOP_FILE.exists():
        print("检测到桌面 stop_scpt.txt，准备终止程序...")
        try:
            STOP_FILE.unlink()
            print("已删除 stop_scpt.txt。")
        except Exception as e:
            print(f"删除 stop_scpt.txt 失败: {e}")
        return True
    return False


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def find_next_empty_date(data, processed):
    """顺序查找第一个 date 只有年份（4位纯数字）、且本轮未处理过的项目。"""
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if (category, idx) in processed:
                continue
            
            # ============== 这里是修改核心 ==============
            date_val = str(item.get('date', '')).strip()
            
            # 规则：只匹配 4 位纯数字（2025 / 2026 / 2024 等）
            if len(date_val) == 4 and date_val.isdigit():
                return category, idx, item
    return None, None, None


def copy_to_clipboard(text):
    p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
    p.communicate(text.encode('utf-8'))


def clear_old_downloads():
    for f in glob.glob(str(DOWNLOADS_DIR / DOWNLOAD_GLOB)):
        try:
            os.remove(f)
        except Exception:
            pass


def wait_for_download(timeout):
    start = time.time()
    while time.time() - start < timeout:
        files = [f for f in glob.glob(str(DOWNLOADS_DIR / DOWNLOAD_GLOB))
                 if not f.endswith('.crdownload')]
        if files:
            time.sleep(0.5)  # 再等半秒确保写入完成
            return max(files, key=os.path.getmtime)
        time.sleep(0.5)
    return None


def move_to_trash(path):
    script = f'tell application "Finder" to delete (POSIX file "{path}" as alias)'
    subprocess.run(['osascript', '-e', script],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def click_image_center(detector, location, shape, y_offset=0):
    """location/shape 是物理像素，这里换算成逻辑坐标后点击。"""
    phys_cx = location[0] + shape[1] // 2
    phys_cy = location[1] + shape[0] // 2
    logic_x = int(phys_cx / detector.scale_factor)
    logic_y = int(phys_cy / detector.scale_factor) + y_offset
    pyautogui.click(logic_x, logic_y)
    print(f"点击(逻辑坐标): ({logic_x}, {logic_y})  y_offset={y_offset}")


def update_item(item, scraped) -> bool:
    """把抓取到的数据写回 item，返回是否有变化。"""
    changed = False

    date = str(scraped.get('date', '')).strip()
    if date:
        item['date'] = date
        changed = True
        print(f"  -> 写入 date: {date}")
    else:
        print("  -> 页面未找到日期，date 保持为空")

    douban = str(scraped.get('douban_rating', '')).strip()
    if douban:
        rating = item.get('评分')
        if not isinstance(rating, dict):
            rating = {}
            item['评分'] = rating
        old = str(rating.get('豆瓣', '')).strip()
        if old != douban:
            rating['豆瓣'] = douban
            changed = True
            print(f"  -> 更新豆瓣评分: {old or '空'} -> {douban}（IMDB 不动）")
        else:
            print(f"  -> 豆瓣评分未变化 ({douban})")
    return changed


def process_one(detector, name):
    """完成一次：点击搜索框 -> 粘贴名字 -> 点结果 -> 触发插件 -> 拿下载结果。"""
    # 1. 名字复制到剪贴板
    copy_to_clipboard(name)

    # 2. 找到 douban_input.png
    tname, location, shape = detector.find_images_on_screen(threshold=0.9)
    if not location:
        print("未找到 douban_input.png，本项目跳过。")
        return None

    # 3. 第一次点击：聚焦搜索框
    click_image_center(detector, location, shape, y_offset=0)
    time.sleep(0.5)

    # 4. 粘贴名字（触发联想下拉）
    if TYPE_NAME_INTO_SEARCH:
        pyautogui.hotkey('command', 'v')

    # 5. 等待 2 秒，让联想结果出现
    time.sleep(WAIT_AFTER_PASTE)

    # 6. 第二次点击：图片 Y+50（第一个联想结果）
    click_image_center(detector, location, shape, y_offset=SECOND_CLICK_Y_OFFSET)

    # 7. 等待页面加载
    time.sleep(WAIT_PAGE_LOAD)

    # 8. 清掉旧下载文件，再触发插件 Option+N
    clear_old_downloads()
    pyautogui.hotkey('option', 'n')
    print("已触发 Option+N，等待插件下载结果...")

    # 9. 等待下载完成
    downloaded = wait_for_download(WAIT_DOWNLOAD_TIMEOUT)
    if not downloaded:
        print("等待下载超时，未获取到结果。")
        return None

    try:
        scraped = load_json(downloaded)
    except Exception as e:
        print(f"读取下载的 json 失败: {e}")
        scraped = None

    # 10. 删除下载文件到废纸篓
    move_to_trash(downloaded)
    return scraped


def main():
    print("=== 豆瓣自动抓取主控启动 ===")
    detector = ScreenDetector(template_names=DOUBAN_INPUT_IMG, clickValue='left')

    processed = set()  # 本轮已处理（含没抓到日期的），避免死循环

    while True:
        if check_stop_file():
            break

        data = load_json(OVIDEOS_JSON)
        category, idx, item = find_next_empty_date(data, processed)
        if item is None:
            print("没有更多 date 为空的项目，全部处理完毕，程序结束。")
            break

        name = item.get('name', '')
        print(f"\n--- 处理 [{category}][{idx}] {name} ---")
        processed.add((category, idx))   # 标记已处理，即使没抓到日期也不会重复死循环

        scraped = process_one(detector, name)
        if scraped:
            if update_item(item, scraped):
                save_json(OVIDEOS_JSON, data)
                print("已写回 OVideos.json。")
            else:
                print("无变化，无需写回。")

        # 循环结束再查一次停止文件
        if check_stop_file():
            break

        time.sleep(1)

    print("=== 结束 ===")


if __name__ == '__main__':
    main()