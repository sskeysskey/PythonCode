#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的「等待 AI 回答 → 点击复制 → 校验剪贴板」自动化脚本
替代 Qianwen_auto.py / Deepseek_auto.py / Doubao_auto.py

用法:
    News_auto.py <provider> [min_chinese]
        provider    : qianwen | deepseek | doubao
        min_chinese : 合格所需最少汉字数，默认 50

退出码:
    0  成功，剪贴板内容合格
    1  连续 3 次点击复制，内容均不合格
    2  超时（TIMEOUT_DURATION 秒内没拿到合格内容）
    3  模板图片缺失 / provider 名称错误
    5  需要交接（AI 拒答 或 回答异常）
"""

import os
import re
import sys
import time
from time import sleep

import cv2
import numpy as np
import pyautogui
import pyperclip
from PIL import ImageGrab

# ================= 全局配置 =================
USER_HOME = os.path.expanduser("~")
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")

SCROLL_AMOUNT = -120        # 滚动幅度
MAX_ATTEMPTS = 3            # 最多点击复制次数
TIMEOUT_DURATION = 120      # 总超时（秒）

# ================= 退出码 =================
EXIT_OK = 0
EXIT_UNQUALIFIED = 1
EXIT_TIMEOUT = 2
EXIT_TEMPLATE_MISSING = 3
EXIT_HANDOFF = 5

# ================= provider 差异配置 =================
# templates: key -> (文件名, 匹配阈值, 是否必需)
PROVIDERS = {
    "qianwen": {
        "label": "千问",
        "templates": {
            "copy":       ("qianwen_copy.png",       0.90, True),
            "forbidden":  ("qianwen_forbidden.png",  0.90, True),
            "forbidden2": ("qianwen_forbidden2.png", 0.90, True),
            "retry":      ("qianwen_retry.png",      0.90, True),
            "timeout":    ("qianwen_timeout.png",    0.90, True),
        },
        "check_refusal_text": True,     # 剪贴板文本命中拒答话术 -> 交接
        "refresh_on_stall": True,       # 见到 retry / timeout 图 -> 等 15s 后 Cmd+R
        "related_gate": False,          # 复制按钮出现后是否等待 related 图再重定位
        "cursor_before_scroll": (709, 749),  # 内容不合格重试前把鼠标移到这里再滚动
        "copy_offset": (0, 0),
    },
    "deepseek": {
        "label": "DeepSeek",
        "templates": {
            "copy":       ("deepseek_copy.png",       0.90, True),
        },
        "check_refusal_text": True,
        "refresh_on_stall": True,
        "related_gate": False,
        "cursor_before_scroll": (709, 749),
        "copy_offset": (-35, 0),        # 靠左 35 像素点击
    },
    "doubao": {
        "label": "豆包",
        "templates": {
            "copy":    ("doubao_copy.png",    0.90, True),
            "related": ("doubao_related.png", 0.80, True),
            "wrong":   ("doubao_wrong.png",   0.88, False),   # 可选：回答异常标识
        },
        "check_refusal_text": True,
        "refresh_on_stall": False,
        "related_gate": True,
        "cursor_before_scroll": None,
        "copy_offset": (0, 0),
    },
}

# 拒答话术（三家共用）
REFUSAL_PHRASES = [
    "抱歉，我无法回答这个问题，我们聊聊别的吧",
    "抱歉，我无法回答这个问题",
    "我们聊聊别的吧",
    "无法回答这个问题",
    "不能回答这个问题",
    "无法协助处理该请求",
    "我无法协助完成该请求",
    "我不能协助完成该请求",
    "该内容无法处理",
    "很抱歉，我不能",
    "很抱歉，我无法",
]


# ================= 基础工具 =================
def get_scale_factor():
    """ImageGrab(物理像素) 与 pyautogui(逻辑坐标) 的比例。Retina 通常 2.0。"""
    try:
        with ImageGrab.grab() as sc:
            img_width = sc.size[0]
        screen_width, _ = pyautogui.size()
        return img_width / screen_width
    except Exception:
        return 1.0


SCALE_FACTOR = get_scale_factor()


def capture_screen():
    with ImageGrab.grab() as screenshot:
        img_np = np.array(screenshot)
        if img_np.ndim == 3 and img_np.shape[2] == 4:
            return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)


def match_template(template, threshold, screen=None):
    """返回 (max_loc, shape) 或 (None, None)"""
    if template is None:
        return None, None
    if screen is None:
        screen = capture_screen()
    if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
        return None, None
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None


def load_templates(cfg):
    """按配置加载模板，返回 {key: (img, threshold)}；缺必需模板则直接退出。"""
    loaded = {}
    for key, (filename, threshold, required) in cfg["templates"].items():
        path = os.path.join(BASE_RESOURCE_DIR, filename)
        img = None
        if os.path.exists(path):
            img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            if required:
                print(f"错误：模板文件缺失或无法读取 -> {path}")
                sys.exit(EXIT_TEMPLATE_MISSING)
            print(f"警告：可选模板不可用 -> {path}，该检测自动关闭。")
            loaded[key] = (None, threshold)
            continue
        loaded[key] = (img, threshold)
    return loaded


def find(templates, key, screen=None):
    if key not in templates:
        return None, None
    img, threshold = templates[key]
    return match_template(img, threshold, screen=screen)


def is_refusal_response(text: str) -> bool:
    if not text:
        return False
    normalized = re.sub(r'\s+', '', text)
    return any(p in normalized for p in REFUSAL_PHRASES)


def is_content_qualified(text, min_chinese=50) -> bool:
    if not text:
        return False
    return len(re.findall(r'[\u4e00-\u9fff]', text)) > min_chinese


def perform_click(location, shape, offset=(0, 0)):
    phys_x = location[0] + shape[1] // 2
    phys_y = location[1] + shape[0] // 2
    lx = int(phys_x / SCALE_FACTOR)
    ly = int(phys_y / SCALE_FACTOR)
    
    if offset:
        lx += offset[0]
        ly += offset[1]
        
    pyautogui.click(lx, ly)
    return lx, ly


def refresh_page_mac():
    os.system("""osascript -e 'tell application "System Events" to key code 15 using command down'""")


def scroll_down(cfg, move_cursor=False):
    pos = cfg.get("cursor_before_scroll")
    if move_cursor and pos:
        print(f"移动光标到 {pos} 并向下滚屏...")
        pyautogui.moveTo(pos[0], pos[1])
    pyautogui.scroll(SCROLL_AMOUNT)
    sleep(1)


# ================= 豆包专用：回答异常二次确认 =================
def check_wrong_confirmed(templates):
    """
    1) 命中 wrong 后等 1.5s
    2) 复查时优先看 copy（复制按钮出现则以 copy 为准）
    3) copy 仍无、wrong 仍在 -> 确认异常
    """
    if templates.get("wrong", (None, 0))[0] is None:
        return False

    loc, _ = find(templates, "wrong")
    if not loc:
        return False

    print("疑似检测到 wrong 标识，1.5 秒后二次确认...")
    sleep(1.5)

    copy_loc, _ = find(templates, "copy")
    if copy_loc:
        print("二次确认时发现 Copy 按钮已出现，忽略 wrong 标识。")
        return False

    loc2, _ = find(templates, "wrong")
    if loc2:
        print("二次确认成立：AI 回答异常。")
        return True

    print("二次确认不成立（wrong 已消失），继续正常流程。")
    return False


# ================= 主流程 =================
def main():
    if len(sys.argv) < 2:
        print("用法: News_auto.py <qianwen|deepseek|doubao> [min_chinese]")
        sys.exit(EXIT_TEMPLATE_MISSING)

    provider = sys.argv[1].strip().lower()
    if provider not in PROVIDERS:
        print(f"错误：未知 provider '{provider}'，可选：{list(PROVIDERS.keys())}")
        sys.exit(EXIT_TEMPLATE_MISSING)

    cfg = PROVIDERS[provider]

    target_threshold = 50
    if len(sys.argv) > 2:
        try:
            target_threshold = int(sys.argv[2])
        except ValueError:
            print("汉字阈值参数格式错误，使用默认 50")

    templates = load_templates(cfg)

    print(f"[{cfg['label']}] 缩放因子={SCALE_FACTOR}，最多 {MAX_ATTEMPTS} 次，汉字阈值={target_threshold}")

    attempt = 1
    start_time = time.time()

    while attempt <= MAX_ATTEMPTS:
        if time.time() - start_time > TIMEOUT_DURATION:
            print("寻找超时：未能在规定时间内完成任务")
            sys.exit(EXIT_TIMEOUT)

        screen = capture_screen()

        # ---- 1. 拒答图标（forbidden / forbidden2）优先 ----
        forbidden_hit = None
        for key in ("forbidden", "forbidden2"):
            loc, _ = find(templates, key, screen=screen)
            if loc:
                forbidden_hit = key
                break
        if forbidden_hit:
            print(f"检测到 {forbidden_hit} 图片，判定为拒答 -> 请求交接。")
            sys.exit(EXIT_HANDOFF)

        # ---- 2. retry / timeout：等 15 秒后刷新页面 ----
        if cfg["refresh_on_stall"]:
            stall_hit = None
            for key in ("retry", "timeout"):
                loc, _ = find(templates, key, screen=screen)
                if loc:
                    stall_hit = key
                    break
            if stall_hit:
                print(f"检测到 {stall_hit} 图片，等待 15 秒后刷新页面...")
                sleep(15)
                refresh_page_mac()
                sleep(5)
                continue        # 刷新不消耗 attempt

        # ---- 3. Copy 按钮 ----
        location, shape = find(templates, "copy", screen=screen)

        if not location:
            # 连复制按钮都没有 -> 检查回答异常（豆包）
            if check_wrong_confirmed(templates):
                sys.exit(EXIT_HANDOFF)
            scroll_down(cfg)
            continue

        # ---- 3.1 豆包：等 related 标识后重新定位 copy（布局会被挤压）----
        if cfg["related_gate"]:
            print("初次定位到 Copy 按钮，开始检测 Related 标识...")
            gate_start = time.time()
            found_related = False
            while time.time() - gate_start < 4:
                rel_loc, _ = find(templates, "related")
                if rel_loc:
                    print("检测到 Related 标识（布局已变化），立即进行下一步。")
                    found_related = True
                    break
                sleep(0.5)
            if not found_related:
                print("4 秒内未检测到 Related 标识，准备重新定位 Copy。")

            location, shape = find(templates, "copy")
            if not location:
                print("等待后无法重新定位 Copy 按钮，检查是否回答异常...")
                if check_wrong_confirmed(templates):
                    sys.exit(EXIT_HANDOFF)
                scroll_down(cfg)
                continue        # 未实际点击，不消耗 attempt

        # ---- 4. 点击复制并校验 ----
        copy_offset = cfg.get("copy_offset", (0, 0))
        lx, ly = perform_click(location, shape, offset=copy_offset)
        print(f"第 {attempt} 次尝试 - 点击复制按钮: {lx}, {ly}")
        sleep(0.5)
        content = pyperclip.paste()

        if cfg["check_refusal_text"] and is_refusal_response(content):
            print("剪贴板命中拒答话术 -> 请求交接。")
            sys.exit(EXIT_HANDOFF)

        if is_content_qualified(content, min_chinese=target_threshold):
            print(f"第 {attempt} 次尝试成功：内容校验通过。")
            sys.exit(EXIT_OK)

        print(f"第 {attempt} 次尝试失败：内容不合格。")

        # 内容不合格时顺手检查回答异常（豆包）
        if check_wrong_confirmed(templates):
            sys.exit(EXIT_HANDOFF)

        attempt += 1
        if attempt <= MAX_ATTEMPTS:
            scroll_down(cfg, move_cursor=True)
        else:
            print("已达到最大尝试次数，内容均不合格。")
            sys.exit(EXIT_UNQUALIFIED)

    sys.exit(EXIT_UNQUALIFIED)


if __name__ == '__main__':
    main()