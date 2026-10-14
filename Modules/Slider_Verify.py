#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slider_Verify.py —— 通用「拖拽滑块验证」模块（macOS）

两种用法：
1) Python 内 import：
    from Slider_Verify import SliderConfig, SliderSolver, reload_browser
    solver = SliderSolver(SliderConfig(template="qianwen_verify.png", distance=257))
    hit = solver.locate()              # 或 solver.locate(screen_bgr) 复用已有截图
    if hit:
        res = solver.solve(hit)
        if res.solved:
            reload_browser("Google Chrome")

2) 命令行（AppleScript / Shell 都可调用）：
    python3 Slider_Verify.py qianwen_verify.png [--distance 257] [--overshoot 45]
                             [--wait 0] [--attempts 2] [--after none|reload|cmdr]
                             [--dry-run]
    退出码：0 已通过 / 1 未出现 / 3 依赖或参数错误 / 10 拖拽后仍未通过
    最后一行输出：SLIDER_SOLVED / SLIDER_NOT_FOUND / SLIDER_FAILED / SLIDER_ERROR

    --dry-run：只识别并打印滑块中心坐标、分数，不拖拽（用于标定 grab offset）
"""

import argparse
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from time import sleep
from typing import List, Optional, Tuple

import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab

try:
    import Quartz  # pyobjc-framework-Quartz（pyautogui 在 mac 上本身就依赖它）
    _HAS_QUARTZ = True
except Exception:
    Quartz = None
    _HAS_QUARTZ = False

USER_HOME = os.path.expanduser("~")
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")

EXIT_SOLVED = 0
EXIT_NOT_FOUND = 1
EXIT_DEPENDENCY = 3
EXIT_FAILED = 10

STATUS_SOLVED = "solved"
STATUS_NOT_FOUND = "not_found"
STATUS_FAILED = "failed"


def _log(msg: str):
    print(f"[Slider] {msg}", flush=True)


# ================= 基础工具 =================
def resolve_template_path(name: str) -> str:
    if os.path.isabs(name):
        return name
    return os.path.join(BASE_RESOURCE_DIR, name)


def get_scale_factor() -> float:
    """ImageGrab(物理像素) / pyautogui(逻辑坐标)，Retina 通常为 2.0"""
    try:
        with ImageGrab.grab() as sc:
            img_width = sc.size[0]
        screen_width, _ = pyautogui.size()
        return img_width / screen_width
    except Exception:
        return 1.0


def capture_screen() -> np.ndarray:
    with ImageGrab.grab() as screenshot:
        img_np = np.array(screenshot)
    if img_np.ndim == 3 and img_np.shape[2] == 4:
        return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
    return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)


def _osascript(script: str, timeout: float = 10.0) -> Tuple[bool, str]:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()
    except Exception as e:
        return False, str(e)


def reload_browser(app: str = "Google Chrome", use_applescript: bool = True) -> bool:
    """
    刷新当前浏览器标签页。
    优先用 AppleScript 的 reload（Chrome / Edge / Brave 等 Chromium 系均支持，不依赖键盘焦点），
    失败时退回 Cmd+R。
    """
    if use_applescript:
        ok, msg = _osascript(
            f'tell application "{app}"\n'
            f'  if (count of windows) > 0 then reload active tab of front window\n'
            f'end tell'
        )
        if ok:
            _log(f"已通过 AppleScript 刷新 {app} 当前标签页")
            return True
        _log(f"AppleScript 刷新失败（{msg}），改用 Cmd+R")

    _osascript(f'tell application "{app}" to activate')
    sleep(0.3)
    ok, msg = _osascript('tell application "System Events" to key code 15 using command down')
    if ok:
        _log("已发送 Cmd+R")
    else:
        _log(f"Cmd+R 发送失败：{msg}")
    return ok


# ================= 配置 / 结果 =================
@dataclass
class SliderConfig:
    template: str                                   # 文件名（Resource 下）或绝对路径
    threshold: float = 0.85                         # 模板匹配阈值
    distance: int = 257                             # 必须拖过的最小距离（逻辑像素）
    overshoot: int = 45                             # 额外多拖（滑轨到头会被卡住，多拖无害）
    overshoot_jitter: int = 10                      # 多拖量的随机浮动
    settle_back: Tuple[int, int] = (3, 8)           # 到达后回退几个像素（更像人手）
    grab_offset: Tuple[int, int] = (0, 0)           # 按住点相对模板中心的偏移
    duration: Tuple[float, float] = (1.0, 1.4)      # 拖动耗时区间（秒）
    press_hold: Tuple[float, float] = (0.15, 0.30)  # 按下后停顿再拖
    release_hold: Tuple[float, float] = (0.15, 0.35)  # 到位后停顿再松开
    approach_duration: Tuple[float, float] = (0.20, 0.40)  # 移动到滑块上的耗时
    y_jitter: float = 1.5                           # 纵向抖动幅度
    step_interval: float = 0.012                    # 轨迹步长（秒）
    max_attempts: int = 2                           # 单次 solve 内最多拖几遍
    vanish_timeout: float = 4.0                     # 拖完后等滑块消失的时长
    retry_gap: float = 1.5                          # 两遍拖拽之间的间隔
    debug_dir: Optional[str] = "/tmp"               # 失败截图目录；None 关闭


@dataclass
class SolveResult:
    status: str
    attempts: int = 0
    message: str = ""

    @property
    def solved(self) -> bool:
        return self.status == STATUS_SOLVED


# ================= 轨迹与拖拽 =================
def _build_track(x0: float, y0: float, total: float, duration: float,
                 cfg: SliderConfig) -> List[Tuple[float, float, float]]:
    """生成 [(x, y, dt), ...]：慢起步 → 快加速 → 平滑减速，附带轻微纵向抖动"""
    n = max(20, int(duration / max(0.005, cfg.step_interval)))
    phase = random.uniform(0, math.pi)
    pts = []
    for i in range(1, n + 1):
        t = i / n
        smooth = t * t * (3 - 2 * t)          # smoothstep：慢起步
        ease_out = 1 - (1 - t) ** 3           # easeOutCubic：减速收尾
        p = 0.2 * smooth + 0.8 * ease_out
        x = x0 + total * p
        y = y0 + cfg.y_jitter * math.sin(phase + t * math.pi * 1.5) + random.uniform(-0.4, 0.4)
        dt = (duration / n) * random.uniform(0.75, 1.25)
        pts.append((x, y, dt))

    lo, hi = cfg.settle_back
    back = random.randint(lo, hi) if hi > 0 else 0
    if back > 0:
        ex, ey, _ = pts[-1]
        steps = random.randint(4, 7)
        for i in range(1, steps + 1):
            pts.append((ex - back * i / steps, ey + random.uniform(-0.3, 0.3), random.uniform(0.012, 0.025)))
    return pts


def _q_post(kind, x: float, y: float, click_state: Optional[int] = None):
    ev = Quartz.CGEventCreateMouseEvent(None, kind, (float(x), float(y)), Quartz.kCGMouseButtonLeft)
    if click_state is not None:
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, click_state)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def human_drag(x0: int, y0: int, total: int, cfg: SliderConfig) -> Tuple[float, float]:
    """从 (x0, y0) 按住，拟人化地向右拖 total 像素后松开；保证异常时也会松开鼠标"""
    duration = random.uniform(*cfg.duration)
    track = _build_track(x0, y0, total, duration, cfg)

    pyautogui.moveTo(x0, y0, duration=random.uniform(*cfg.approach_duration))
    sleep(random.uniform(0.05, 0.12))

    last_x, last_y = float(x0), float(y0)
    if _HAS_QUARTZ:
        _q_post(Quartz.kCGEventLeftMouseDown, x0, y0, click_state=1)
        try:
            sleep(random.uniform(*cfg.press_hold))
            for x, y, dt in track:
                _q_post(Quartz.kCGEventLeftMouseDragged, x, y)
                last_x, last_y = x, y
                sleep(dt)
            sleep(random.uniform(*cfg.release_hold))
        finally:
            _q_post(Quartz.kCGEventLeftMouseUp, last_x, last_y, click_state=1)
    else:
        # 退化方案：pyautogui 的私有 _dragTo 会发送真正的 drag 事件
        plat = getattr(pyautogui, "platformModule", None)
        drag_fn = getattr(plat, "_dragTo", None)
        pyautogui.mouseDown(x0, y0, button="left")
        try:
            sleep(random.uniform(*cfg.press_hold))
            for x, y, dt in track:
                if drag_fn:
                    drag_fn(int(round(x)), int(round(y)), "left")
                else:
                    pyautogui.moveTo(int(round(x)), int(round(y)), _pause=False)
                last_x, last_y = x, y
                sleep(dt)
            sleep(random.uniform(*cfg.release_hold))
        finally:
            pyautogui.mouseUp(button="left")
    return last_x, last_y


# ================= 求解器 =================
class SliderSolver:
    def __init__(self, config: SliderConfig, scale_factor: Optional[float] = None):
        self.cfg = config
        self.template_path = resolve_template_path(config.template)
        self.template = None
        if os.path.exists(self.template_path):
            self.template = cv2.imread(self.template_path, cv2.IMREAD_COLOR)
        if self.template is None:
            _log(f"模板不可用：{self.template_path}")
        self.scale = scale_factor or get_scale_factor()

    @property
    def available(self) -> bool:
        return self.template is not None

    def locate(self, screen: Optional[np.ndarray] = None) -> Optional[Tuple[int, int, float]]:
        """返回 (逻辑中心x, 逻辑中心y, 分数) 或 None；screen 为 BGR 物理像素截图"""
        if not self.available:
            return None
        if screen is None:
            screen = capture_screen()
        th, tw = self.template.shape[:2]
        if th > screen.shape[0] or tw > screen.shape[1]:
            return None
        res = cv2.matchTemplate(screen, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < self.cfg.threshold:
            return None
        cx = (max_loc[0] + tw / 2) / self.scale
        cy = (max_loc[1] + th / 2) / self.scale
        return int(round(cx)), int(round(cy)), float(max_val)

    def wait_appear(self, timeout: float, interval: float = 0.5) -> Optional[Tuple[int, int, float]]:
        deadline = time.time() + max(0.0, timeout)
        while True:
            hit = self.locate()
            if hit or time.time() >= deadline:
                return hit
            sleep(interval)

    def wait_vanish(self, timeout: float, interval: float = 0.3) -> bool:
        deadline = time.time() + max(0.0, timeout)
        while True:
            if self.locate() is None:
                return True
            if time.time() >= deadline:
                return False
            sleep(interval)

    def _save_debug(self, tag: str):
        if not self.cfg.debug_dir:
            return
        try:
            path = os.path.join(self.cfg.debug_dir, f"slider_{tag}_{time.strftime('%Y%m%d_%H%M%S')}.png")
            cv2.imwrite(path, capture_screen())
            _log(f"已保存调试截图：{path}")
        except Exception as e:
            _log(f"保存调试截图失败：{e}")

    def solve(self, hit: Optional[Tuple[int, int, float]] = None) -> SolveResult:
        if not self.available:
            return SolveResult(STATUS_FAILED, 0, "模板不可用")
        if hit is None:
            hit = self.locate()
        if hit is None:
            return SolveResult(STATUS_NOT_FOUND, 0, "未发现滑块")

        attempts = max(1, self.cfg.max_attempts)
        for i in range(1, attempts + 1):
            gx = hit[0] + self.cfg.grab_offset[0]
            gy = hit[1] + self.cfg.grab_offset[1]
            total = self.cfg.distance + self.cfg.overshoot + random.randint(0, max(0, self.cfg.overshoot_jitter))
            _log(f"第 {i}/{attempts} 次拖拽：模板中心({hit[0]},{hit[1]}) 分数 {hit[2]:.3f} "
                 f"→ 按住({gx},{gy}) 向右拖 {total}px（终点约 x={gx + total}）")
            try:
                human_drag(gx, gy, total, self.cfg)
            except pyautogui.FailSafeException:
                raise
            except Exception as e:
                _log(f"拖拽异常：{e}")

            if self.wait_vanish(self.cfg.vanish_timeout):
                _log("滑块已消失，判定验证通过。")
                return SolveResult(STATUS_SOLVED, i, "ok")

            _log("拖拽后滑块仍在。")
            if i < attempts:
                sleep(self.cfg.retry_gap)
                new_hit = self.locate()
                if new_hit is None:
                    _log("间隔期间滑块已消失，判定验证通过。")
                    return SolveResult(STATUS_SOLVED, i, "ok")
                hit = new_hit

        self._save_debug("fail")
        return SolveResult(STATUS_FAILED, attempts, "多次拖拽后仍未通过")


# ================= 命令行 =================
class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"参数错误：{message}")
        print("SLIDER_ERROR")
        sys.exit(EXIT_DEPENDENCY)


def _range(text: str) -> Tuple[float, float]:
    parts = str(text).replace("~", "-").split("-")
    if len(parts) == 1:
        v = float(parts[0])
        return v, v
    a, b = float(parts[0]), float(parts[1])
    return min(a, b), max(a, b)


def main(argv=None) -> int:
    ap = _Parser(description="通用拖拽滑块验证")
    ap.add_argument("template")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--distance", type=int, default=257)
    ap.add_argument("--overshoot", type=int, default=45)
    ap.add_argument("--grab-dx", type=int, default=0)
    ap.add_argument("--grab-dy", type=int, default=0)
    ap.add_argument("--duration", type=_range, default=(1.0, 1.4), help="如 1.0-1.4")
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--vanish-timeout", type=float, default=4.0)
    ap.add_argument("--wait", type=float, default=0.0, help="等待滑块出现的秒数；0=只看一眼")
    ap.add_argument("--after", choices=["none", "reload", "cmdr"], default="none")
    ap.add_argument("--app", default="Google Chrome")
    ap.add_argument("--pre-after-delay", type=float, default=1.0)
    ap.add_argument("--after-delay", type=float, default=2.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = SliderConfig(
        template=args.template, threshold=args.threshold, distance=args.distance,
        overshoot=args.overshoot, grab_offset=(args.grab_dx, args.grab_dy),
        duration=args.duration, max_attempts=args.attempts, vanish_timeout=args.vanish_timeout,
    )
    solver = SliderSolver(cfg)
    if not solver.available:
        print("SLIDER_ERROR")
        return EXIT_DEPENDENCY

    hit = solver.wait_appear(args.wait) if args.wait > 0 else solver.locate()
    if hit is None:
        print("SLIDER_NOT_FOUND")
        return EXIT_NOT_FOUND

    if args.dry_run:
        _log(f"[dry-run] 滑块中心=({hit[0]},{hit[1]}) 分数={hit[2]:.3f} 缩放={solver.scale}")
        print("SLIDER_FOUND")
        return EXIT_SOLVED

    res = solver.solve(hit)
    if not res.solved:
        print("SLIDER_FAILED")
        return EXIT_FAILED

    if args.after in ("reload", "cmdr"):
        sleep(args.pre_after_delay)
        reload_browser(args.app, use_applescript=(args.after == "reload"))
        sleep(args.after_delay)

    print("SLIDER_SOLVED")
    return EXIT_SOLVED


if __name__ == "__main__":
    try:
        sys.exit(main())
    except pyautogui.FailSafeException:
        print("用户将鼠标甩到屏幕角落，已中止。")
        print("SLIDER_ERROR")
        sys.exit(6)