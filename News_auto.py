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
    3  模板图片缺失 / provider 名称错误 / 未预期的异常
    5  需要交接（AI 拒答 或 回答异常 或 额度用完且无法切换模型）
    6  用户中止（鼠标甩到屏幕角落触发 pyautogui fail-safe）
    7  网页端「上传/发送失败」（本篇建议交由同品牌 API 兜底，下一篇仍回网页版）
    8  当前模型免费额度用完，已在网页上切换到备用模型 -> 请用同一 provider 重跑本篇
    9  AI 没有执行总结(反问/菜单式回复) -> 请用同一 provider 重跑本篇
    10 【v7】滑块验证无法通过 / 验证后无法重新提交（Engine 按 exit 7 同样处理：本篇 API 兜底）

【v7】滑块验证：
    等待 Copy 的每一轮都会在同一帧里优先找 slider_verify.template；
    找到 -> 拟人化拖拽 -> 刷新页面 -> 等输入框 -> 重新粘贴「文章+Prompt」并回车 -> 回到等待 Copy 的循环。
    重新提交用的文本 = 本脚本启动时剪贴板里的内容（由 Engine 放入）。
"""

import os
import re
import sys
import time
import traceback
import subprocess
from time import sleep

import cv2
import numpy as np
import pyautogui
import pyperclip
from PIL import ImageGrab

# ================= 全局配置 =================
USER_HOME = os.path.expanduser("~")
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")
MODULES_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Modules")
BROWSER_APP = "Google Chrome"

SCROLL_AMOUNT = -120        # 滚动幅度
MAX_ATTEMPTS = 3            # 最多点击复制次数
TIMEOUT_DURATION = 120      # 总超时（秒）；处理完滑块验证后重新计时

# 点击复制后等待剪贴板被写入的最长时间（秒）
CLIPBOARD_WAIT = 2.0

# 上传失败 / 切换模型失败时，保存一张整屏截图便于事后核查
SAVE_DEBUG_SHOT = True
DEBUG_SHOT_DIR = "/tmp"

# ================= 通用滑块模块（缺失时自动关闭该功能） =================
if MODULES_DIR not in sys.path:
    sys.path.append(MODULES_DIR)
try:
    from Slider_Verify import SliderConfig, SliderSolver, reload_browser
    HAS_SLIDER_MODULE = True
except Exception as _e:
    HAS_SLIDER_MODULE = False
    print(f"警告：无法加载 Slider_Verify 模块（{_e}），滑块验证处理已关闭。")

# ================= 退出码 =================
EXIT_OK = 0
EXIT_UNQUALIFIED = 1
EXIT_TIMEOUT = 2
EXIT_TEMPLATE_MISSING = 3
EXIT_HANDOFF = 5
EXIT_USER_ABORT = 6
EXIT_UPLOAD_FAIL = 7          # 网页上传/发送失败
EXIT_MODEL_SWITCHED = 8       # 额度用完，已切换模型，请重跑本篇
EXIT_OFFTASK = 9              # AI 未执行总结(反问/给选项),请同 provider 重跑本篇
EXIT_VERIFY_FAIL = 10         # 【v7】滑块验证失败 / 验证后无法重新提交

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
            "forbidden3":  ("qianwen_forbidden3.png",   0.90, True),
            "retry":       ("qianwen_retry.png",        0.90, True),
            "timeout":     ("qianwen_timeout.png",      0.90, True),
            # 可选模板：文件不存在时该检测自动关闭，不会影响主流程
            "upload_fail": ("qianwen_upload_fail.png",  0.92, False),
            # ---- 额度用完时切换模型所需模板（可选；缺任何一张 -> 退回旧的拒答交接逻辑）----
            "switch_open":    ("qianwen_current36.png", 0.90, False),
            "switch_hover":   ("qianwen_select37.png",  0.90, False),
            "switch_confirm": ("qianwen_default.png",   0.90, False),
            # ---- 【v7】滑块验证后重新提交：输入框定位 ----
            "launch":         ("qianwen_launch.png",    0.90, False),
        },
        "check_refusal_text": True,     # 剪贴板文本命中拒答话术 -> 交接
        "check_offtask_text": True,     # 剪贴板是"反问/给选项"而非总结 -> 重跑
        "refresh_on_stall": True,       # 见到 retry / timeout 图 -> 等 15s 后刷新
        "related_gate": False,          # 复制按钮出现后是否等待 related 图再重定位
        "cursor_before_scroll": (709, 749),  # 内容不合格重试前把鼠标移到这里再滚动
        "copy_offset": (0, 0),
        # ---- 上传失败检测参数 ----
        "upload_fail_confirm_delay": 0.8,   # 二次确认间隔；<=0 表示命中即判定
        "upload_fail_transient_ok": True,   # 提示消失但始终没有 Copy -> 仍判定为失败
        # ---- 额度用完 -> 切换模型 ----
        "model_switch_enabled": True,
        "model_switch_steps": [
            ("click", "switch_open"),      # 1) 点击当前模型(3.6)，展开模型菜单
            ("hover", "switch_hover"),     # 2) 鼠标悬停到 3.7 上，展开子菜单
            ("click", "switch_confirm"),   # 3) 点击 default
        ],
        "model_switch_step_timeout": 6.0,  # 每一步等待模板出现的最长秒数
        # ---- 【v7】滑块验证 ----
        "slider_verify": {
            "enabled": True,
            "template": "qianwen_verify.png",
            "threshold": 0.85,
            "distance": 257,              # 实测 768 -> 1025
            "overshoot": 45,              # 多拖一点，滑轨到头会卡住，无副作用
            "grab_offset": (0, 0),        # 若截图不是滑块本体，用 --dry-run 标定后调整
            "duration": (1.0, 1.4),       # 拖动耗时（秒）
            "drag_attempts": 2,           # 单次验证内最多拖几遍
            "vanish_timeout": 4.0,        # 拖完后等待滑块消失
            "max_per_run": 3,             # 本次 News_auto 运行最多处理几次验证
            "after": "refresh_resubmit",  # none / refresh / refresh_resubmit
            "pre_refresh_delay": 1.0,
            "post_refresh_delay": 2.5,
            "resubmit": {
                "focus_key": "launch",            # 等这个模板出现 = 页面已就绪
                "focus_offset": (0, -50),         # 与 Engine 的 ShotClickOffset 一致
                "focus_timeout": 15.0,
                "mouse_after": [(862, 839), (852, 806)],  # 与 Engine 的 SubmitPrompt / MoveMouse 一致
                "post_submit_wait": 2.0,
            },
        },
    },
    "deepseek": {
        "label": "DeepSeek",
        "templates": {
            "copy":       ("deepseek_copy.png",       0.90, True),
            # 如需支持 DeepSeek 上传失败，放一张 deepseek_upload_fail.png 并解注下一行
            # "upload_fail": ("deepseek_upload_fail.png", 0.92, False),
        },
        "check_refusal_text": True,
        "check_offtask_text": False,
        "refresh_on_stall": True,
        "related_gate": False,
        "cursor_before_scroll": (709, 749),
        "copy_offset": (-35, 0),        # 靠左 35 像素点击
        "upload_fail_confirm_delay": 0.8,
        "upload_fail_transient_ok": True,
        "model_switch_enabled": False,
        "slider_verify": {"enabled": False},
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
        "check_offtask_text": False,
        "refresh_on_stall": False,
        "related_gate": True,
        "cursor_before_scroll": None,
        "copy_offset": (0, 0),
        "upload_fail_confirm_delay": 0.8,
        "upload_fail_transient_ok": True,
        "model_switch_enabled": False,
        "slider_verify": {"enabled": False},
    },
}

# ================= provider 名称归一化 =================
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


# 「额度用完」话术：全文匹配（通常附在半截翻译的末尾）
QUOTA_PATTERNS = [
    re.compile(r"当前模型今日\d*次?免费额度已用完"),
    re.compile(r"今日免费额度已用完"),
]

# 拒答话术（三家共用）；注意：额度用完已移到 QUOTA_PATTERNS 单独处理
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
    "当前访问人数过多",
    "针对这个问题我无法为你提供相应解答",
    "I'm unable to answer that question",
]

# 拒答检测窗口：短文本全文匹配；长文本只看首尾，避免新闻正文引用到类似句子被误判
REFUSAL_FULLTEXT_MAX = 400
REFUSAL_EDGE_WINDOW = 200


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


def template_available(templates, key) -> bool:
    return key in templates and templates[key][0] is not None


def find(templates, key, screen=None):
    if key not in templates:
        return None, None
    img, threshold = templates[key]
    return match_template(img, threshold, screen=screen)


def wait_for(templates, key, timeout, interval=0.4):
    """在 timeout 秒内轮询模板，返回 (loc, shape) 或 (None, None)"""
    deadline = time.time() + timeout
    while True:
        loc, shape = find(templates, key)
        if loc:
            return loc, shape
        if time.time() >= deadline:
            return None, None
        sleep(interval)


def _normalize_text(text: str) -> str:
    return re.sub(r'\s+', '', text or "")


def is_quota_exhausted(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(p.search(normalized) for p in QUOTA_PATTERNS)


def is_refusal_response(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if len(normalized) <= REFUSAL_FULLTEXT_MAX:
        scope = normalized
    else:
        scope = normalized[:REFUSAL_EDGE_WINDOW] + "\n" + normalized[-REFUSAL_EDGE_WINDOW:]
    return any(p in scope for p in REFUSAL_PHRASES)


# 「AI 没做总结,反过来问用户想要什么」的话术(只在短文本全文 / 长文本尾部匹配)
OFFTASK_PHRASES = [
    "你希望执行哪一种",
    "您希望执行哪一种",
    "你希望我执行哪",
    "告诉我后我马上处理",
    "告诉我后我马上",
    "请告诉我你希望",
    "请告诉我您希望",
    "你想让我做什么",
    "你想进一步",
    "您想进一步",
    "您想让我做什么",
    "你希望我如何处理",
    "您希望我如何处理",
    "你需要我做什么",
    "您需要我做什么",
    "你具体希望我",
    "您具体希望我",
    "请问你希望我",
    "请问您希望我",
]

OFFTASK_FULLTEXT_MAX = 800     # 归一化后不超过此长度:全文匹配;超过:只看尾部
OFFTASK_TAIL_WINDOW = 200
# 菜单项特征:「翻译成中文 —— 将这篇……」「1. 改写 / 润色 —— ……」
OFFTASK_MENU_LINE = re.compile(r'^\s*(?:[-*•·]|\d+[.、)])?\s*[^\s—–\-]{2,20}[^\n—–]{0,20}\s*(?:——|—|–|--)\s*\S')


def is_offtask_response(text: str) -> bool:
    """判断剪贴板内容是否为「AI 没有总结,而是反问用户/列出可选操作」"""
    normalized = _normalize_text(text)
    if not normalized:
        return False

    if len(normalized) <= OFFTASK_FULLTEXT_MAX:
        scope = normalized
    else:
        scope = normalized[-OFFTASK_TAIL_WINDOW:]
    if any(p in scope for p in OFFTASK_PHRASES):
        return True

    # 结构特征兜底:短文本 + 至少 3 行「选项 —— 说明」 + 结尾带询问/等待指示的语气
    if len(normalized) <= OFFTASK_FULLTEXT_MAX:
        menu_lines = [ln for ln in text.splitlines() if OFFTASK_MENU_LINE.match(ln)]
        tail = normalized[-OFFTASK_TAIL_WINDOW:]
        if len(menu_lines) >= 3 and re.search(r'[?？]|告诉我|希望|需要|选择', tail):
            return True
    return False


def is_content_qualified(text, min_chinese=50) -> bool:
    if not text:
        return False
    return len(re.findall(r'[\u4e00-\u9fff]', text)) > min_chinese


def to_logical_center(location, shape, offset=(0, 0)):
    phys_x = location[0] + shape[1] // 2
    phys_y = location[1] + shape[0] // 2
    lx = int(phys_x / SCALE_FACTOR)
    ly = int(phys_y / SCALE_FACTOR)
    if offset:
        lx += offset[0]
        ly += offset[1]
    return lx, ly


def perform_click(location, shape, offset=(0, 0)):
    lx, ly = to_logical_center(location, shape, offset)
    pyautogui.click(lx, ly)
    return lx, ly


def clear_clipboard():
    try:
        pyperclip.copy("")
    except Exception as e:
        print(f"清空剪贴板失败（忽略）: {e}")


def snapshot_clipboard() -> str:
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""


def read_clipboard_after_copy(timeout=CLIPBOARD_WAIT) -> str:
    """点击复制后轮询剪贴板，直到出现非空内容或超时"""
    deadline = time.time() + timeout
    content = ""
    while True:
        try:
            content = pyperclip.paste() or ""
        except Exception:
            content = ""
        if content.strip():
            return content
        if time.time() >= deadline:
            return ""
        sleep(0.2)


def _osascript(script: str) -> bool:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"osascript 失败: {(r.stderr or '').strip()}")
        return r.returncode == 0
    except Exception as e:
        print(f"osascript 异常: {e}")
        return False


def activate_browser():
    _osascript(f'tell application "{BROWSER_APP}" to activate')
    sleep(0.3)


def paste_and_enter():
    """与 Engine 的 SubmitPrompt 一致：Cmd+V → 0.8s → 回车"""
    _osascript('tell application "System Events" to keystroke "v" using {command down}')
    sleep(0.8)
    _osascript('tell application "System Events" to key code 36')


def refresh_page_mac():
    if HAS_SLIDER_MODULE:
        reload_browser(BROWSER_APP)
    else:
        _osascript('tell application "System Events" to key code 15 using command down')


def scroll_down(cfg, move_cursor=False):
    pos = cfg.get("cursor_before_scroll")
    if move_cursor and pos:
        print(f"移动光标到 {pos} 并向下滚屏...")
        pyautogui.moveTo(pos[0], pos[1])
    pyautogui.scroll(SCROLL_AMOUNT)
    sleep(1)


# ================= 【v7】滑块验证 =================
def build_slider_solver(cfg):
    sv = cfg.get("slider_verify") or {}
    if not sv.get("enabled"):
        return None
    if not HAS_SLIDER_MODULE:
        print("滑块模块不可用，跳过滑块检测。")
        return None
    conf = SliderConfig(
        template=sv.get("template", ""),
        threshold=float(sv.get("threshold", 0.85)),
        distance=int(sv.get("distance", 257)),
        overshoot=int(sv.get("overshoot", 45)),
        grab_offset=tuple(sv.get("grab_offset", (0, 0))),
        duration=tuple(sv.get("duration", (1.0, 1.4))),
        max_attempts=int(sv.get("drag_attempts", 2)),
        vanish_timeout=float(sv.get("vanish_timeout", 4.0)),
        debug_dir=DEBUG_SHOT_DIR if SAVE_DEBUG_SHOT else None,
    )
    solver = SliderSolver(conf, scale_factor=SCALE_FACTOR)
    if not solver.available:
        print(f"警告：滑块模板不可用（{conf.template}），滑块检测自动关闭。")
        return None
    return solver


def resubmit_prompt(cfg, templates, prompt_text) -> bool:
    rs = (cfg.get("slider_verify") or {}).get("resubmit") or {}
    key = rs.get("focus_key", "launch")

    if not prompt_text or len(prompt_text.strip()) < 10:
        print("启动时未保存到有效的「文章+Prompt」，无法重新提交。")
        return False
    if not template_available(templates, key):
        print(f"重新提交所需模板 {key} 不可用。")
        return False

    loc, shape = wait_for(templates, key, float(rs.get("focus_timeout", 15.0)))
    if not loc:
        print(f"刷新后 {rs.get('focus_timeout', 15.0)}s 内未出现输入框（{key}）。")
        save_debug_shot("resubmit_no_input")
        return False
    sleep(0.5)

    try:
        pyperclip.copy(prompt_text)
    except Exception as e:
        print(f"写回剪贴板失败：{e}")
        return False
    sleep(0.3)
    if snapshot_clipboard() != prompt_text:
        print("警告：剪贴板写回校验不一致，仍继续尝试提交。")

    activate_browser()
    x, y = perform_click(loc, shape, offset=tuple(rs.get("focus_offset", (0, 0))))
    print(f"已点击输入框 ({x}, {y})，重新粘贴并提交...")
    sleep(0.4)
    paste_and_enter()
    for pos in rs.get("mouse_after", []):
        try:
            pyautogui.moveTo(pos[0], pos[1])
        except Exception:
            pass
        sleep(0.1)
    sleep(float(rs.get("post_submit_wait", 2.0)))
    return True


def handle_slider_verify(cfg, templates, solver, hit, prompt_text, state) -> bool:
    """返回 True = 已处理完毕（需要回到等待 Copy 的循环）；False = 失败，应退出码 10"""
    sv = cfg["slider_verify"]
    state["count"] += 1
    max_per_run = int(sv.get("max_per_run", 3))
    print(f"检测到滑块验证（本次运行第 {state['count']}/{max_per_run} 次）。")
    if state["count"] > max_per_run:
        print("滑块验证出现次数超过上限，放弃网页端。")
        save_debug_shot("verify_too_many")
        return False

    result = solver.solve(hit)
    if not result.solved:
        print(f"滑块验证未通过：{result.message}")
        return False

    after = sv.get("after", "refresh_resubmit")
    if after in ("refresh", "refresh_resubmit"):
        sleep(float(sv.get("pre_refresh_delay", 1.0)))
        refresh_page_mac()
        sleep(float(sv.get("post_refresh_delay", 2.5)))
    if after == "refresh_resubmit":
        if not resubmit_prompt(cfg, templates, prompt_text):
            return False
        print("滑块验证处理完毕，已重新提交，回到等待 Copy 的循环。")
    return True


# ================= 额度用完 -> 切换模型 =================
def try_switch_model(cfg, templates) -> bool:
    """
    按 cfg["model_switch_steps"] 依次执行：
        click : 找到模板并点击（瞬移点击，避免划过其它菜单项导致子菜单收起）
        hover : 找到模板并平滑移动鼠标到其中心（让网页收到 hover 事件）
    任一步失败：按 Esc 收起菜单、保存截图、返回 False。
    """
    if not cfg.get("model_switch_enabled"):
        print("该 provider 未启用模型切换。")
        return False

    steps = cfg.get("model_switch_steps") or []
    if not steps:
        return False

    missing = [key for _, key in steps if not template_available(templates, key)]
    if missing:
        print(f"模型切换所需模板缺失：{missing}，放弃切换。")
        return False

    step_timeout = float(cfg.get("model_switch_step_timeout", 6.0))

    for i, (action, key) in enumerate(steps, start=1):
        loc, shape = wait_for(templates, key, step_timeout)
        if not loc:
            print(f"模型切换第 {i} 步失败：{step_timeout}s 内未找到 {key}。")
            save_debug_shot(f"model_switch_step{i}_fail")
            try:
                pyautogui.press("esc")
            except Exception:
                pass
            return False

        x, y = to_logical_center(loc, shape)
        if action == "click":
            print(f"模型切换第 {i} 步：点击 {key} @ ({x}, {y})")
            pyautogui.click(x, y)
            sleep(0.8)
        elif action == "hover":
            print(f"模型切换第 {i} 步：悬停到 {key} @ ({x}, {y})")
            pyautogui.moveTo(x, y, duration=0.3)
            sleep(0.2)
            pyautogui.moveRel(2, 0, duration=0.1)
            sleep(0.8)
        else:
            print(f"未知切换动作：{action}")
            return False

    sleep(1.0)
    print("模型切换流程执行完毕。")
    return True


# ================= 上传/发送失败检测 =================
def check_upload_fail_confirmed(cfg, templates, screen=None):
    """
    返回 (confirmed, delayed)
        confirmed : True 表示确认为「上传失败」
        delayed   : True 表示本函数消耗了等待时间（当前 screen 已过期，调用方应重新取帧）
    """
    if not template_available(templates, UPLOAD_FAIL_KEY):
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
    if not template_available(templates, "wrong"):
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

    # 【v7】必须最先保存：后面点击复制前会清空剪贴板
    prompt_snapshot = snapshot_clipboard()

    templates = load_templates(cfg)
    slider = build_slider_solver(cfg)
    verify_state = {"count": 0}

    print(f"[{cfg['label']}] 缩放因子={SCALE_FACTOR}，最多 {MAX_ATTEMPTS} 次，汉字阈值={target_threshold}，"
          f"滑块检测={'开' if slider else '关'}")

    attempt = 1
    start_time = time.time()

    while attempt <= MAX_ATTEMPTS:
        if time.time() - start_time > TIMEOUT_DURATION:
            print("寻找超时：未能在规定时间内完成任务")
            sys.exit(EXIT_TIMEOUT)

        screen = capture_screen()

        # ---- -1. 【v7】滑块验证：遮罩出现时其它检测都无意义，最优先 ----
        if slider is not None:
            hit = slider.locate(screen)
            if hit:
                if not handle_slider_verify(cfg, templates, slider, hit, prompt_snapshot, verify_state):
                    print("滑块验证处理失败 -> 请求 Engine 本篇改用 API 兜底（退出码 10）。")
                    sys.exit(EXIT_VERIFY_FAIL)
                attempt = 1
                start_time = time.time()
                continue

        # ---- 0. 同帧先看 Copy：已出答案时压制所有异常检测 ----
        copy_loc, copy_shape = find(templates, "copy", screen=screen)

        # ---- 1. 上传/发送失败 ----
        if not copy_loc:
            up_confirmed, up_delayed = check_upload_fail_confirmed(cfg, templates, screen=screen)
            if up_confirmed:
                save_debug_shot("upload_fail")
                print("检测到网页上传失败 -> 请求 API 兜底（退出码 7）。")
                sys.exit(EXIT_UPLOAD_FAIL)
            if up_delayed:
                sleep(0.3)
                continue

        # ---- 2. 拒答图标 ----
        forbidden_hit = None
        for key in ("forbidden", "forbidden2", "forbidden3"):
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
                continue

        # ---- 4. Copy 按钮 ----
        location, shape = copy_loc, copy_shape

        if not location:
            if check_wrong_confirmed(templates):
                sys.exit(EXIT_HANDOFF)
            scroll_down(cfg)
            continue

        # ---- 4.1 豆包：等 related 标识后重新定位 copy ----
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
                continue

        # ---- 5. 点击复制并校验 ----
        # 先清空剪贴板：否则复制未生效时会读到 Engine 放进去的「文章+Prompt」，
        # 其中 Prompt 自带 50+ 汉字，会被误判为合格
        clear_clipboard()
        copy_offset = cfg.get("copy_offset", (0, 0))
        lx, ly = perform_click(location, shape, offset=copy_offset)
        print(f"第 {attempt} 次尝试 - 点击复制按钮: {lx}, {ly}")
        sleep(0.3)
        content = read_clipboard_after_copy()

        if not content:
            print(f"第 {attempt} 次尝试：剪贴板为空（复制未生效）。")
        else:
            # 5.1 额度用完：优先于拒答 / 合格校验（半截翻译可能已经超过汉字阈值）
            if is_quota_exhausted(content):
                print("剪贴板命中「免费额度已用完」-> 本篇翻译未完成，尝试切换模型...")
                if try_switch_model(cfg, templates):
                    print("模型已切换 -> 请求 Engine 用同一 provider 重跑本篇（退出码 8）。")
                    sys.exit(EXIT_MODEL_SWITCHED)
                print("无法切换模型 -> 按拒答交接（退出码 5）。")
                sys.exit(EXIT_HANDOFF)

            # 5.2 拒答话术
            if cfg["check_refusal_text"] and is_refusal_response(content):
                print("剪贴板命中拒答话术 -> 请求交接。")
                sys.exit(EXIT_HANDOFF)

            # 5.2b 反问/给选项而没有总结(汉字数可能很多,必须在合格校验之前拦截)
            if cfg.get("check_offtask_text") and is_offtask_response(content):
                print("剪贴板内容是反问/选项菜单而非总结 -> 请求同 provider 重跑本篇(退出码 9)。")
                print("内容预览:", content[:80].replace("\n", " | "))
                save_debug_shot("offtask")
                sys.exit(EXIT_OFFTASK)

            # 5.3 合格校验
            if is_content_qualified(content, min_chinese=target_threshold):
                print(f"第 {attempt} 次尝试成功：内容校验通过。")
                sys.exit(EXIT_OK)

            print(f"第 {attempt} 次尝试失败：内容不合格。")

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
    try:
        main()
    except SystemExit:
        raise
    except pyautogui.FailSafeException:
        print("检测到鼠标甩到屏幕角落（pyautogui fail-safe），视为用户中止。")
        sys.exit(EXIT_USER_ABORT)
    except Exception as e:
        # 原来未捕获异常会以 1 退出，被 Engine 误报为「内容不合格」
        traceback.print_exc()
        print(f"News_auto 未预期异常：{e}")
        sys.exit(EXIT_TEMPLATE_MISSING)