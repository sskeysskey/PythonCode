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
    7  网页端「上传/发送失败」（本篇建议交由同品牌 API 兜底，下一篇仍回网页版）
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

# 上传失败判定成立时，保存一张整屏截图便于事后核查误报
SAVE_DEBUG_SHOT = True
DEBUG_SHOT_DIR = "/tmp"

# ================= 退出码 =================
EXIT_OK = 0
EXIT_UNQUALIFIED = 1
EXIT_TIMEOUT = 2
EXIT_TEMPLATE_MISSING = 3
EXIT_HANDOFF = 5
EXIT_UPLOAD_FAIL = 7          # 新增：网页上传/发送失败

UPLOAD_FAIL_KEY = "upload_fail"

# ================= provider 差异配置 =================
# templates: key -> (文件名, 匹配阈值, 是否必需)
PROVIDERS = {
    "qianwen": {
        "label": "千问",
        "templates": {
            "copy":        ("qianwen_copy.png",         0.90, True),
            "forbidden":   ("qianwen_forbidden.png",    0.90, True),
            "forbidden2":  ("qianwen_forbidden2.png",   0.90, True),
            "retry":       ("qianwen_retry.png",        0.90, True),
            "timeout":     ("qianwen_timeout.png",      0.90, True),
            # 可选模板：文件不存在时该检测自动关闭，不会影响主流程
            "upload_fail": ("qianwen_upload_fail.png",  0.92, False),
        },
        "check_refusal_text": True,     # 剪贴板文本命中拒答话术 -> 交接
        "refresh_on_stall": True,       # 见到 retry / timeout 图 -> 等 15s 后 Cmd+R
        "related_gate": False,          # 复制按钮出现后是否等待 related 图再重定位
        "cursor_before_scroll": (709, 749),  # 内容不合格重试前把鼠标移到这里再滚动
        "copy_offset": (0, 0),
        # ---- 上传失败检测参数 ----
        "upload_fail_confirm_delay": 0.8,   # 二次确认间隔；<=0 表示命中即判定
        "upload_fail_transient_ok": True,   # 提示消失但始终没有 Copy -> 仍判定为失败
    },
    "deepseek": {
        "label": "DeepSeek",
        "templates": {
            "copy":       ("deepseek_copy.png",       0.90, True),
            # 如需支持 DeepSeek 上传失败，放一张 deepseek_upload_fail.png 并解注下一行
            # "upload_fail": ("deepseek_upload_fail.png", 0.92, False),
        },
        "check_refusal_text": True,
        "refresh_on_stall": True,
        "related_gate": False,
        "cursor_before_scroll": (709, 749),
        "copy_offset": (-35, 0),        # 靠左 35 像素点击
        "upload_fail_confirm_delay": 0.8,
        "upload_fail_transient_ok": True,
    },
    "doubao": {
        "label": "豆包",
        "templates": {
            "copy":    ("doubao_copy.png",    0.90, True),
            "related": ("doubao_related.png", 0.80, True),
            "wrong":   ("doubao_wrong.png",   0.88, False),   # 可选：回答异常标识
            # "upload_fail": ("doubao_upload_fail.png", 0.92, False),
        },
        "check_refusal_text": True,
        "refresh_on_stall": False,
        "related_gate": True,
        "cursor_before_scroll": None,
        "copy_offset": (0, 0),
        "upload_fail_confirm_delay": 0.8,
        "upload_fail_transient_ok": True,
    },
}

# ================= provider 名称归一化 =================
# News_Engine 现在传的是 qianwen_ui / deepseek_ui / doubao_ui，
# 这里统一剥掉通道后缀，_api 结尾的直接报错（应该走 Modules/API_Client.py）
PROVIDER_ALIASES = {
    "qianwen": "qianwen", "qianwen_ui": "qianwen", "qianwen-ui": "qianwen",
    "qwen": "qianwen", "qwen_ui": "qianwen", "tongyi": "qianwen", "tongyi_ui": "qianwen",
    "deepseek": "deepseek", "deepseek_ui": "deepseek", "deepseek-ui": "deepseek",
    "ds": "deepseek", "ds_ui": "deepseek",
    "doubao": "doubao", "doubao_ui": "doubao", "doubao-ui": "doubao",
}


def normalize_provider(raw: str) -> str:
    p = (raw or "").strip().lower()
    if p.endswith("_api") or p.endswith("-api"):
        print(f"错误：'{raw}' 是 API provider，请调用 Modules/API_Client.py，而不是 News_auto.py")
        sys.exit(EXIT_TEMPLATE_MISSING)
    return PROVIDER_ALIASES.get(p, p)

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
    "你好，这个问题我暂时无法回答",
    "让我们换个话题再聊聊吧",
    "该内容涉嫌违反",
    "若有误判，请长按本条消息",
    "当前模型今日50次免费额度已用完",
    "当前访问人数过多",
    "针对这个问题我无法为你提供相应解答"
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


def save_debug_shot(tag: str):
    if not SAVE_DEBUG_SHOT:
        return
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(DEBUG_SHOT_DIR, f"news_auto_{tag}_{ts}.png")
        cv2.imwrite(path, capture_screen())
        print(f"已保存调试截图: {path}")
    except Exception as e:
        print(f"保存调试截图失败: {e}")


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


# ================= 上传/发送失败检测 =================
def check_upload_fail_confirmed(cfg, templates, screen=None):
    """
    返回 (confirmed, delayed)
        confirmed : True 表示确认为「上传失败」
        delayed   : True 表示本函数消耗了等待时间（当前 screen 已过期，调用方应重新取帧）

    判定策略（对抗 toast 转瞬即逝 + 模板误报）：
        1) 当前帧命中 upload_fail
        2) 等 confirm_delay 后复查：若 Copy 已出现 -> 说明其实已经出答案，忽略
        3) upload_fail 仍在 -> 确认失败
        4) upload_fail 消失但 Copy 仍未出现 -> 再采一次；仍是这个状态时按 toast 处理，
           若 upload_fail_transient_ok 为 True 则判定失败
    """
    if templates.get(UPLOAD_FAIL_KEY, (None, 0))[0] is None:
        return False, False

    loc, _ = find(templates, UPLOAD_FAIL_KEY, screen=screen)
    if not loc:
        return False, False

    delay = float(cfg.get("upload_fail_confirm_delay", 0.8))
    if delay <= 0:
        print("命中 upload_fail 标识（未开启二次确认），判定为上传失败。")
        return True, False

    print(f"疑似检测到上传失败标识，{delay} 秒后二次确认...")
    sleep(delay)

    copy_loc, _ = find(templates, "copy")
    if copy_loc:
        print("二次确认时发现 Copy 按钮已出现，忽略 upload_fail 标识。")
        return False, True

    loc2, _ = find(templates, UPLOAD_FAIL_KEY)
    if loc2:
        print("二次确认成立：网页端上传/发送失败。")
        return True, True

    sleep(0.6)
    copy_loc2, _ = find(templates, "copy")
    if copy_loc2:
        print("提示已消失且 Copy 已出现，忽略 upload_fail 标识。")
        return False, True

    loc3, _ = find(templates, UPLOAD_FAIL_KEY)
    if loc3:
        print("第三次采样命中：网页端上传/发送失败。")
        return True, True

    if cfg.get("upload_fail_transient_ok", True):
        print("上传失败提示为瞬时 toast（已消失且始终无 Copy 按钮），判定为上传失败。")
        return True, True

    print("上传失败提示已消失，且未开启瞬时判定，继续正常流程。")
    return False, True


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

    provider = normalize_provider(sys.argv[1])
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

        # ---- 0. 同帧先看 Copy：已出答案时压制所有异常检测 ----
        copy_loc, copy_shape = find(templates, "copy", screen=screen)

        # ---- 1. 上传/发送失败（优先级最高，避免被 retry/timeout 拖进 15s+刷新）----
        if not copy_loc:
            up_confirmed, up_delayed = check_upload_fail_confirmed(cfg, templates, screen=screen)
            if up_confirmed:
                save_debug_shot("upload_fail")
                print("检测到网页上传失败 -> 请求 API 兜底（退出码 7）。")
                sys.exit(EXIT_UPLOAD_FAIL)
            if up_delayed:
                # 确认过程消耗了时间，当前帧已过期，重新取帧（不消耗 attempt）
                sleep(0.3)
                continue

        # ---- 2. 拒答图标（forbidden / forbidden2）----
        forbidden_hit = None
        for key in ("forbidden", "forbidden2"):
            loc, _ = find(templates, key, screen=screen)
            if loc:
                forbidden_hit = key
                break
        if forbidden_hit:
            print(f"检测到 {forbidden_hit} 图片，判定为拒答 -> 请求交接。")
            sys.exit(EXIT_HANDOFF)

        # ---- 3. retry / timeout：等 15 秒后刷新页面 ----
        if cfg["refresh_on_stall"] and not copy_loc:
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

        # ---- 4. Copy 按钮 ----
        location, shape = copy_loc, copy_shape

        if not location:
            # 连复制按钮都没有 -> 检查回答异常（豆包）
            if check_wrong_confirmed(templates):
                sys.exit(EXIT_HANDOFF)
            scroll_down(cfg)
            continue

        # ---- 4.1 豆包：等 related 标识后重新定位 copy（布局会被挤压）----
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

        # ---- 5. 点击复制并校验 ----
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