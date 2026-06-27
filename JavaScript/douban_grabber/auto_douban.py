#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣信息自动抓取与回写 —— 主控循环
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
# ================= 新增配置 =================
DOUBAN_POPUP_IMG = '/Users/yanzhang/Coding/python_code/Resource/douban_popup.png'  # 弹窗模板图路径
# ============================================
DOWNLOAD_GLOB    = 'douban_result*.json'      # 插件下载的文件名模式

# —— 各种等待时间（秒），按你机器/网速调整 ——
WAIT_AFTER_PASTE      = 2     # 粘贴名字后等待联想下拉出现
WAIT_POPUP_APPEAR     = 20     # 等待弹窗图片出现的时间
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
    """顺序查找第一个 date = 2026、且本轮未处理过的项目。"""
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if (category, idx) in processed:
                continue
            
            # ============== 【修改后：只匹配 date = 2026】 ==============
            date_val = str(item.get('date', '')).strip()
            
            # 规则：严格匹配字符串 "2026"
            if date_val == "2026":
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


def is_valid_2026_date(date_str: str) -> bool:
    """
    校验抓取到的日期是否合格：
    - 必须以 '2026' 开头
    - '2026' 后面必须还有数字（即带月/日，例如 2026-05-20、2026年5月20日）
    只有 '2026'、'2026年'、空字符串等都算不合格。
    """
    s = str(date_str).strip()
    if not s.startswith("2026"):
        return False
    rest = s[4:]                       # 去掉开头的 2026
    return bool(re.search(r'\d', rest))  # 后面还得有数字才算带月日

def update_item(item, scraped) -> bool:
    """
    把抓取到的数据写回 item，返回是否有变化。
    规则：只有 date 是 2026 开头且带月日时才写入；否则整条跳过，不写入。
    """
    date   = str(scraped.get('date', '')).strip()
    douban = str(scraped.get('douban_rating', '')).strip()

    # ============ 日期校验：不合格则整条跳过 ============
    if not is_valid_2026_date(date):
        print("  ┌────────────── ⚠️ 跳过本条，未写入 ──────────────")
        print(f"  │ 原因：抓取到的日期不合格 ->「{date or '空'}」")
        print(f"  │ 要求：必须 2026 开头且带月日（如 2026-05-20）")
        print(f"  │ 一并放弃的豆瓣评分 ->「{douban or '空'}」")
        print("  └──────────────────────────────────────────────")
        return False
    # =================================================

    changed = False

    # —— 写入日期 ——
    item['date'] = date
    changed = True

    # —— 写入豆瓣评分（IMDB 不动）——
    old = ''
    if douban:
        rating = item.get('评分')
        if not isinstance(rating, dict):
            rating = {}
            item['评分'] = rating
        old = str(rating.get('豆瓣', '')).strip()
        rating['豆瓣'] = douban
        changed = True

    # —— 成功写入日志（一眼能看明白）——
    print("  ┌────────────── ✅ 写入成功 ──────────────")
    print(f"  │ 日期 date     : {date}")
    if douban:
        if old and old != douban:
            print(f"  │ 豆瓣评分      : {old} -> {douban}")
        else:
            print(f"  │ 豆瓣评分      : {douban}")
    else:
        print(f"  │ 豆瓣评分      : 页面未抓到，保持原样")
    print("  └─────────────────────────────────────────")

    return changed


# ====================== 【新增：自动激活Chrome + 切换到豆瓣标签页】 ======================
def activate_chrome_and_switch_to_douban():
    """
    Mac 自动：
    1. 激活 Google Chrome
    2. 遍历所有窗口+所有标签，切换到 url 包含 douban.com 的标签页
    3. 如果找到豆瓣页面则继续，如果未找到则打开新标签并访问指定豆瓣电影页面
    """
    print("\n===== 开始激活Chrome并查找豆瓣标签 =====")

    script = '''
    set foundTab to missing value
    set targetWin to missing value
    set targetTabIdx to 0
    set targetUrl to "https://movie.douban.com/subject/1837856/"

    tell application "Google Chrome"
        activate
        delay 0.3
        -- 遍历所有窗口
        repeat with w in every window
            set tabCount to count of tabs of w
            -- 遍历当前窗口所有标签
            repeat with tIdx from 1 to tabCount
                set t to tab tIdx of w
                set tabUrl to URL of t as string
                if tabUrl contains "douban.com" and tabUrl is not "" then
                    set foundTab to t
                    set targetWin to w
                    set targetTabIdx to tIdx
                    exit repeat
                end if
            end repeat
            if foundTab is not missing value then exit repeat
        end repeat

        -- 如果找到豆瓣标签，切换窗口+标签
        if foundTab is not missing value then
            set index of targetWin to 1
            set active tab index of targetWin to targetTabIdx
            delay 0.2
            return "FOUND"
        else
            tell application "System Events"
                keystroke "t" using command down
                delay 0.5
                keystroke "https://movie.douban.com/subject/1837856/"
                delay 0.5
                key code 36
            end tell
            return "NOT_FOUND_OPENED"
        end if
    end tell
    '''

    # 执行脚本并捕获返回结果
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        encoding="utf-8"
    )
    result = proc.stdout.strip()
    time.sleep(1.8)  # 加长等待，保证页面渲染完成

    if result == "FOUND":
        print("✅ 成功切换到豆瓣标签页，Chrome窗口已置顶\n")
    elif result == "NOT_FOUND_OPENED":
        print("✅ 未找到豆瓣标签页，已打开新的豆瓣电影页面: https://movie.douban.com/subject/1837856/\n")
    else:
        print("⚠️ 操作完成，但返回状态异常\n")


def process_one(detector, name):
    """完成一次：点击搜索框 -> 粘贴名字 -> 点结果 -> 触发插件 -> 拿下载结果。"""
    # 1. 名字复制到剪贴板
    copy_to_clipboard(name)

    # 2. 循环等待查找 douban_input.png，最长等待 WAIT_POPUP_APPEAR 秒（20s）
    tname, location, shape = None, None, None
    start_input_wait = time.time()
    print(f"开始等待 douban_input.png 输入框，最长等待 {WAIT_POPUP_APPEAR} 秒...")
    while time.time() - start_input_wait < WAIT_POPUP_APPEAR:
        tname, location, shape = detector.find_images_on_screen(threshold=0.9)
        if location:
            print("✅ 成功识别 douban_input.png 搜索框")
            break
        time.sleep(0.5)
    # 等待超时仍未找到，直接跳过本条
    if not location:
        print(f"❌ 等待{WAIT_POPUP_APPEAR}秒仍未找到 douban_input.png，本项目跳过。")
        return None

    # 3. 第一次点击：聚焦搜索框
    click_image_center(detector, location, shape, y_offset=0)
    time.sleep(0.5)

    # 4. 粘贴名字（触发联想下拉）
    if TYPE_NAME_INTO_SEARCH:
        pyautogui.hotkey('command', 'v')

    # 5. 等待 2 秒，让联想结果出现
    time.sleep(WAIT_AFTER_PASTE)

    # ====================== 侦测弹窗图片 ======================
    print("开始侦测 douban_popup.png 弹窗...")
    # 临时创建弹窗检测器（用你指定的绝对路径图片）
    popup_detector = ScreenDetector(template_names=DOUBAN_POPUP_IMG, clickValue='left')
    popup_found = False
    # 等待并检测弹窗（最多等 WAIT_POPUP_APPEAR 秒）
    start_wait = time.time()
    while time.time() - start_wait < WAIT_POPUP_APPEAR:
        _, popup_loc, popup_shape = popup_detector.find_images_on_screen(threshold=0.9)
        if popup_loc:
            popup_found = True
            print("✅ 成功找到 douban_popup.png 弹窗，准备点击联想结果")
            break
        time.sleep(0.3)

    if not popup_found:
        print(f"❌ 等待{WAIT_POPUP_APPEAR}秒未找到 douban_popup.png 弹窗，跳过本次点击，直接结束本条处理")
        return None
    # ======================================================================

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

    # ====================== 【关键：程序一开始先执行！】 ======================
    # 第一步：自动激活 Chrome 并切换到豆瓣页面
    activate_chrome_and_switch_to_douban()

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