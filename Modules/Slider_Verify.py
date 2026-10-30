#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slider_Verify.py v2 —— 通用「拖拽滑块验证」模块（macOS）

v2 变更：
  · 全流程拟人化随机：发现 → 反应延迟(对数正态) → 贝塞尔曲线移近(Fitts 定律时长, 可能轻微越过再回正)
    → 悬停 → 按下停顿 → 非对称 minimum-jerk 速度曲线拖拽(采样间隔漂移/纵向漂移/手抖/随机中途停顿)
    → 越过后回退 → 到位停顿 → 松开 → 松开后手部漂移；抓取点在滑块内随机，拖拽距离随机。
  · handle()：auto / manual 两种模式；auto 失败或被保护器暂停时可退回人工等待。
  · SliderGuard：跨进程持久化的风控保护器（连续失败冷却 / 每小时、每天上限 / 最短间隔）。
  · Quartz 事件补上 fail-safe（鼠标甩到屏幕角落仍可中止）。

两种用法：
1) Python 内 import：
    from Slider_Verify import SliderConfig, SliderSolver, reload_browser, STATUS_SOLVED
    solver = SliderSolver(SliderConfig(template="qianwen_verify.png", distance=257))
    hit = solver.locate()
    if hit:
        res = solver.handle(hit, auto=True, manual_fallback=True, manual_timeout=300)

2) 命令行：
    python3 Slider_Verify.py qianwen_verify.png [--mode auto|manual|detect]
            [--manual-fallback | --no-manual-fallback] [--manual-wait 300]
            [--after none|reload|cmdr] [--wait 0] [--no-guard] [--dry-run] ...
    退出码：0 已通过(自动或人工) / 1 未出现 / 3 依赖或参数错误 / 6 用户中止 / 10 未通过或被暂停
    输出关键字：SLIDER_SOLVED / SLIDER_MANUAL_OK / SLIDER_NOT_FOUND / SLIDER_FOUND
                SLIDER_FAILED / SLIDER_BLOCKED / SLIDER_ERROR
    --after 只在「自动拖拽通过」后执行；人工完成不刷新。
"""

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from time import sleep
from typing import List, NamedTuple, Optional, Tuple

import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab

try:
    import Quartz  # pyobjc-framework-Quartz
    _HAS_QUARTZ = True
except Exception:
    Quartz = None
    _HAS_QUARTZ = False

USER_HOME = os.path.expanduser("~")
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")
MODULES_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_SCRIPT = os.path.join(MODULES_DIR, "notification.py")
GUARD_STATE_PATH = os.path.join(USER_HOME, "Coding", "News", "slider_guard.json")

EXIT_SOLVED = 0
EXIT_NOT_FOUND = 1
EXIT_DEPENDENCY = 3
EXIT_USER_ABORT = 6
EXIT_FAILED = 10

STATUS_SOLVED = "solved"            # 自动拖拽通过
STATUS_MANUAL_OK = "manual_ok"      # 人工完成
STATUS_NOT_FOUND = "not_found"      # 没出现 / 处理前已自行消失
STATUS_FAILED = "failed"            # 自动拖拽未通过
STATUS_BLOCKED = "blocked"          # 被保护器暂停自动且不允许退回人工
STATUS_MANUAL_TIMEOUT = "manual_timeout"

Range = Tuple[float, float]


def _log(msg: str):
    print(f"[Slider] {msg}", flush=True)


class Hit(NamedTuple):
    x: int          # 逻辑坐标中心
    y: int
    score: float
    w: int = 0      # 模板逻辑宽高
    h: int = 0


# ================= 随机工具 =================
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lognormal(median: float, sigma: float, lo: Optional[float] = None, hi: Optional[float] = None) -> float:
    """对数正态：中位数附近最常见、偶尔偏慢（右偏），贴近人类反应时间分布"""
    v = median * math.exp(random.gauss(0.0, sigma))
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def rand_in(r, sigma: float = 0.25) -> float:
    """在 [lo, hi] 内取「中间多、两头少、略右偏」的随机值；传单个数字则原样返回"""
    if isinstance(r, (int, float)):
        return float(r)
    lo, hi = float(r[0]), float(r[1])
    if hi <= lo:
        return lo
    med = math.sqrt(lo * hi) if lo > 0 else (lo + hi) / 2.0
    if med <= 0:
        return random.uniform(lo, hi)
    return lognormal(med, sigma, lo, hi)


def _min_jerk(t: float) -> float:
    return t * t * t * (10 - 15 * t + 6 * t * t)


# ================= 基础工具 =================
def resolve_template_path(name: str) -> str:
    if os.path.isabs(name):
        return name
    return os.path.join(BASE_RESOURCE_DIR, name)


def get_scale_factor() -> float:
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


_SCREEN_SIZE = None


def _screen_size():
    global _SCREEN_SIZE
    if _SCREEN_SIZE is None:
        try:
            w, h = pyautogui.size()
            _SCREEN_SIZE = (int(w), int(h))
        except Exception:
            _SCREEN_SIZE = (1920, 1080)
    return _SCREEN_SIZE


def _clamp_pt(x: float, y: float) -> Tuple[float, float]:
    """限制在屏幕内且避开四角（四角是 fail-safe 触发点）"""
    w, h = _screen_size()
    return _clamp(float(x), 2.0, w - 3.0), _clamp(float(y), 2.0, h - 3.0)


def check_failsafe():
    """Quartz 事件不经过 pyautogui，需要手动做 fail-safe 检查"""
    if not getattr(pyautogui, "FAILSAFE", True):
        return
    try:
        pos = pyautogui.position()
    except Exception:
        return
    pts = getattr(pyautogui, "FAILSAFE_POINTS", None) or [(0, 0)]
    corners = {(int(p[0]), int(p[1])) for p in pts}
    if (int(pos[0]), int(pos[1])) in corners:
        raise pyautogui.FailSafeException("鼠标位于屏幕角落，触发 fail-safe")


def interruptible_sleep(sec: float, step: float = 0.1):
    end = time.perf_counter() + max(0.0, sec)
    while True:
        check_failsafe()
        rem = end - time.perf_counter()
        if rem <= 0:
            return
        sleep(min(step, rem))


def notify(msg: str, color: str = "orange", duration_ms: int = 6000):
    """优先用 Modules/notification.py（与 Engine 同款，非阻塞），否则系统通知"""
    try:
        if os.path.exists(NOTIFY_SCRIPT):
            subprocess.Popen(
                [sys.executable, NOTIFY_SCRIPT, msg, "-d", str(duration_ms), "--bg", color, "--fg", "white"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
    except Exception:
        pass
    try:
        safe = msg.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "滑块验证"'], timeout=5)
    except Exception:
        pass


def _osascript(script: str, timeout: float = 10.0) -> Tuple[bool, str]:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()
    except Exception as e:
        return False, str(e)


def reload_browser(app: str = "Google Chrome", use_applescript: bool = True) -> bool:
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
    _log("已发送 Cmd+R" if ok else f"Cmd+R 发送失败：{msg}")
    return ok


# ================= 配置 / 结果 =================
@dataclass
class GuardPolicy:
    enabled: bool = True
    max_consecutive_failures: int = 2     # 连续失败几次 -> 冷却
    cooldown_minutes: float = 30.0        # 冷却期内只走人工
    max_per_hour: int = 6                 # 每小时最多自动拖几次
    max_per_day: int = 30                 # 24 小时最多自动拖几次
    min_interval_seconds: float = 20.0    # 距上次自动拖拽太近 = 滑块反复出现，疑似被风控
    state_path: str = GUARD_STATE_PATH


@dataclass
class SliderConfig:
    template: str
    threshold: float = 0.85
    distance: int = 257                    # 必须拖过的最小距离（逻辑像素）
    overshoot: int = 45                    # 多拖（滑轨到头会卡住，无害）
    overshoot_jitter: int = 12             # 多拖量浮动：[-jitter/3, +jitter]
    grab_offset: Tuple[int, int] = (0, 0)  # 按住点相对模板中心的固定偏移
    grab_jitter: Tuple[float, float] = (6.0, 4.0)  # 按住点随机偏移上限 (x, y)
    # ---- 时间（全部随机）----
    reaction: Tuple[float, float, float, float] = (0.9, 0.40, 0.35, 3.0)  # 中位数, sigma, 下限, 上限
    hover_before_press: Range = (0.08, 0.45)
    press_hold: Range = (0.10, 0.35)
    duration: Range = (0.8, 1.6)           # 拖动耗时
    release_hold: Range = (0.06, 0.40)
    retry_gap: Range = (1.2, 3.0)
    approach_base: float = 0.12            # Fitts: T = a + b*log2(1 + D/W)
    approach_slope: float = 0.09
    approach_bounds: Range = (0.15, 1.3)
    approach_overshoot_prob: float = 0.30
    # ---- 轨迹形态 ----
    step_interval: Range = (0.008, 0.016)  # 采样间隔（≈60~125Hz 鼠标回报率）
    velocity_skew: Range = (0.70, 0.95)    # <1：速度峰值靠前（人手特征）
    y_jitter: float = 1.2
    y_drift: float = 2.5
    # mid_pause_prob: float = 0.25
    # mid_pause: Range = (0.04, 0.16)
    mid_pause_prob: float = 0.55
    mid_pause: Range = (0.12, 0.35)
    settle_back: Tuple[int, int] = (2, 8)
    settle_back_prob: float = 0.70
    post_release_drift_prob: float = 0.60
    post_release_drift: Range = (6.0, 40.0)
    # ---- 流程 ----
    max_attempts: int = 2
    vanish_timeout: float = 4.0
    debug_dir: Optional[str] = "/tmp"
    guard: Optional[GuardPolicy] = field(default_factory=GuardPolicy)


@dataclass
class SolveResult:
    status: str
    attempts: int = 0
    message: str = ""

    @property
    def solved(self) -> bool:
        return self.status == STATUS_SOLVED

    @property
    def passed(self) -> bool:
        return self.status in (STATUS_SOLVED, STATUS_MANUAL_OK)


# ================= 风控保护器 =================
class SliderGuard:
    def __init__(self, policy: GuardPolicy):
        self.p = policy

    def _load(self) -> dict:
        st = {}
        try:
            with open(self.p.state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if not isinstance(st, dict):
                st = {}
        except Exception:
            st = {}
        hist = []
        for t in st.get("history", []) or []:
            try:
                hist.append(float(t))
            except Exception:
                pass
        st["history"] = hist
        st["consecutive_failures"] = int(st.get("consecutive_failures", 0) or 0)
        st["cooldown_until"] = float(st.get("cooldown_until", 0) or 0)
        return st

    def _save(self, st: dict):
        try:
            os.makedirs(os.path.dirname(self.p.state_path), exist_ok=True)
            tmp = self.p.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, self.p.state_path)
        except Exception as e:
            _log(f"保存保护器状态失败（忽略）：{e}")

    def allow(self) -> Tuple[bool, str]:
        if not self.p.enabled:
            return True, ""
        now = time.time()
        st = self._load()
        if now < st["cooldown_until"]:
            return False, f"连续失败冷却中（约剩 {math.ceil((st['cooldown_until'] - now) / 60)} 分钟）"
        hist = [t for t in st["history"] if now - t < 86400]
        if self.p.max_per_day > 0 and len(hist) >= self.p.max_per_day:
            return False, f"24 小时内已自动 {len(hist)} 次（上限 {self.p.max_per_day}）"
        hour = [t for t in hist if now - t < 3600]
        if self.p.max_per_hour > 0 and len(hour) >= self.p.max_per_hour:
            return False, f"1 小时内已自动 {len(hour)} 次（上限 {self.p.max_per_hour}）"
        if hist and self.p.min_interval_seconds > 0:
            gap = now - max(hist)
            if gap < self.p.min_interval_seconds:
                return False, f"距上次自动拖拽仅 {gap:.0f} 秒，滑块反复出现，疑似被风控"
        return True, ""

    def record(self, solved: bool):
        if not self.p.enabled:
            return
        now = time.time()
        st = self._load()
        hist = [t for t in st["history"] if now - t < 86400]
        hist.append(now)
        st["history"] = hist[-200:]
        if solved:
            st["consecutive_failures"] = 0
        else:
            c = st["consecutive_failures"] + 1
            if c >= max(1, self.p.max_consecutive_failures):
                st["cooldown_until"] = now + self.p.cooldown_minutes * 60
                _log(f"自动拖拽连续失败 {c} 次 -> 冷却 {self.p.cooldown_minutes:.0f} 分钟（期间只走人工）")
                c = 0
            st["consecutive_failures"] = c
        st["last_result"] = "solved" if solved else "failed"
        st["last_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save(st)


# ================= 鼠标事件 =================
def _q_post(kind, x: float, y: float, click_state: Optional[int] = None):
    x, y = _clamp_pt(x, y)
    ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
    if click_state is not None:
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, click_state)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _post_move(x: float, y: float):
    if _HAS_QUARTZ:
        _q_post(Quartz.kCGEventMouseMoved, x, y)
    else:
        x, y = _clamp_pt(x, y)
        pyautogui.moveTo(int(round(x)), int(round(y)), _pause=False)


def _play_track(track, post):
    """按绝对时间轴回放，避免 sleep 误差累积导致总时长失真"""
    t_next = time.perf_counter()
    for x, y, dt in track:
        post(x, y)
        t_next += dt
        rem = t_next - time.perf_counter()
        if rem > 0:
            sleep(rem)


# ================= 轨迹 =================
def _build_approach_path(x0, y0, x1, y1, target_w, cfg: SliderConfig):
    """当前位置 -> 目标：随机弯曲的三次贝塞尔 + minimum-jerk 速度；可能轻微越过再回正"""
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)
    if dist < 3:
        return [(x1, y1, random.uniform(0.02, 0.05))]

    fitts = cfg.approach_base + cfg.approach_slope * math.log2(1 + dist / max(8.0, float(target_w)))
    duration = _clamp(fitts * lognormal(1.0, 0.22), *cfg.approach_bounds)

    ux, uy = dx / dist, dy / dist
    px, py = -uy, ux
    bend = dist * random.uniform(0.04, 0.18) * random.choice((-1, 1))
    a1, a2 = random.uniform(0.2, 0.4), random.uniform(0.6, 0.85)
    k1, k2 = random.uniform(0.7, 1.2), random.uniform(0.2, 0.8)
    c1 = (x0 + dx * a1 + px * bend * k1, y0 + dy * a1 + py * bend * k1)
    c2 = (x0 + dx * a2 + px * bend * k2, y0 + dy * a2 + py * bend * k2)

    n = max(8, int(duration / random.uniform(*cfg.step_interval)))
    skew = random.uniform(0.75, 1.0)
    pts = []
    for i in range(1, n + 1):
        s = _min_jerk((i / n) ** skew)
        u = 1 - s
        bx = u ** 3 * x0 + 3 * u * u * s * c1[0] + 3 * u * s * s * c2[0] + s ** 3 * x1
        by = u ** 3 * y0 + 3 * u * u * s * c1[1] + 3 * u * s * s * c2[1] + s ** 3 * y1
        if i < n:
            bx += random.uniform(-0.4, 0.4)
            by += random.uniform(-0.4, 0.4)
        pts.append((bx, by, duration / n * random.uniform(0.8, 1.2)))

    if random.random() < cfg.approach_overshoot_prob:
        ov = random.uniform(2.0, 6.0)
        ox = x1 + ux * ov + random.uniform(-1, 1)
        oy = y1 + uy * ov + random.uniform(-1, 1)
        pts[-1] = (ox, oy, pts[-1][2])
        k = random.randint(3, 5)
        for j in range(1, k + 1):
            f = j / k
            pts.append((ox + (x1 - ox) * f, oy + (y1 - oy) * f, random.uniform(0.015, 0.03)))
    return pts


def _build_drag_track(x0, y0, total, duration, cfg: SliderConfig):
    """按住后的拖拽轨迹：非对称 minimum-jerk + 纵向漂移 + 手抖 + 采样间隔随机游走 + 可选中途停顿"""
    n = max(25, int(duration / random.uniform(*cfg.step_interval)))
    skew = random.uniform(*cfg.velocity_skew)
    drift = random.gauss(0.0, cfg.y_drift)
    phase = random.uniform(0, 2 * math.pi)
    freq = random.uniform(0.8, 1.8)
    pause_at = random.uniform(0.35, 0.75) if random.random() < cfg.mid_pause_prob else None
    pause_len = rand_in(cfg.mid_pause)
    base_dt = duration / n
    rate = 1.0
    last_x = float(x0)
    paused = False
    pts = []
    for i in range(1, n + 1):
        t = i / n
        p = _min_jerk(t ** skew)
        x = x0 + total * p + random.uniform(-0.3, 0.3)
        x = max(x, last_x - 0.5)  # 基本单调，只允许极小回抖
        tremor = cfg.y_jitter * (math.sin(phase + freq * math.pi * t) - math.sin(phase))
        y = y0 + drift * p + tremor + random.uniform(-0.3, 0.3)
        rate = _clamp(rate + random.gauss(0, 0.08), 0.7, 1.35)
        dt = base_dt * rate
        if pause_at is not None and not paused and t >= pause_at:
            dt += pause_len
            paused = True
        pts.append((x, y, dt))
        last_x = x

    lo, hi = cfg.settle_back
    if hi > 0 and random.random() < cfg.settle_back_prob:
        back = random.uniform(max(0, lo), hi)
        ex, ey, _ = pts[-1]
        k = random.randint(4, 8)
        for j in range(1, k + 1):
            pts.append((ex - back * j / k, ey + random.uniform(-0.3, 0.3), random.uniform(0.012, 0.03)))
    return pts


def human_drag(x0: float, y0: float, total: float, cfg: SliderConfig, target_w: float = 40.0):
    """曲线移近 → 悬停 → 按下 → 拟人拖拽 → 停顿 → 松开 → 手部漂移；异常时保证松开鼠标"""
    check_failsafe()
    try:
        cur = pyautogui.position()
        cx, cy = float(cur[0]), float(cur[1])
    except Exception:
        cx, cy = x0 - random.uniform(80, 200), y0 + random.uniform(40, 120)

    _play_track(_build_approach_path(cx, cy, x0, y0, target_w, cfg), _post_move)
    interruptible_sleep(rand_in(cfg.hover_before_press))
    check_failsafe()

    duration = rand_in(cfg.duration, sigma=0.2)
    track = _build_drag_track(x0, y0, total, duration, cfg)
    last = [float(x0), float(y0)]
    _log(f"拖拽：耗时≈{duration:.2f}s，{len(track)} 个采样点")

    if _HAS_QUARTZ:
        _q_post(Quartz.kCGEventLeftMouseDown, x0, y0, click_state=1)
        try:
            sleep(rand_in(cfg.press_hold))

            def _post(x, y):
                _q_post(Quartz.kCGEventLeftMouseDragged, x, y)
                last[0], last[1] = x, y

            _play_track(track, _post)
            sleep(rand_in(cfg.release_hold))
        finally:
            _q_post(Quartz.kCGEventLeftMouseUp, last[0], last[1], click_state=1)
    else:
        plat = getattr(pyautogui, "platformModule", None)
        drag_fn = getattr(plat, "_dragTo", None)
        pyautogui.mouseDown(int(round(x0)), int(round(y0)), button="left", _pause=False)
        try:
            sleep(rand_in(cfg.press_hold))

            def _post(x, y):
                x, y = _clamp_pt(x, y)
                if drag_fn:
                    drag_fn(int(round(x)), int(round(y)), "left")
                else:
                    pyautogui.moveTo(int(round(x)), int(round(y)), _pause=False)
                last[0], last[1] = x, y

            _play_track(track, _post)
            sleep(rand_in(cfg.release_hold))
        finally:
            pyautogui.mouseUp(button="left", _pause=False)

    if random.random() < cfg.post_release_drift_prob:
        try:
            ang = random.uniform(0, 2 * math.pi)
            d = rand_in(cfg.post_release_drift)
            ex, ey = last[0] + math.cos(ang) * d, last[1] + math.sin(ang) * d
            _play_track(_build_approach_path(last[0], last[1], ex, ey, 30.0, cfg), _post_move)
        except pyautogui.FailSafeException:
            raise
        except Exception:
            pass
    return last[0], last[1]


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
        g = config.guard
        self.guard = SliderGuard(g) if (g is not None and g.enabled) else None

    @property
    def available(self) -> bool:
        return self.template is not None

    def locate(self, screen: Optional[np.ndarray] = None) -> Optional[Hit]:
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
        return Hit(int(round(cx)), int(round(cy)), float(max_val),
                   int(round(tw / self.scale)), int(round(th / self.scale)))

    def wait_appear(self, timeout: float, interval: float = 0.5) -> Optional[Hit]:
        deadline = time.time() + max(0.0, timeout)
        while True:
            hit = self.locate()
            if hit or time.time() >= deadline:
                return hit
            sleep(interval)

    def wait_vanish(self, timeout: float, interval: float = 0.3) -> bool:
        """连续 2 帧找不到才算消失，防止动画闪烁误判"""
        deadline = time.time() + max(0.0, timeout)
        miss = 0
        while True:
            if self.locate() is None:
                miss += 1
                if miss >= 2:
                    return True
            else:
                miss = 0
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

    def _record(self, solved: bool):
        if self.guard:
            self.guard.record(solved)

    def _pick_grab_point(self, hit: Hit) -> Tuple[float, float]:
        jx, jy = self.cfg.grab_jitter
        if hit.w:
            jx = min(jx, hit.w * 0.3)
        if hit.h:
            jy = min(jy, hit.h * 0.3)
        dx = _clamp(random.gauss(0, jx / 2.0), -jx, jx) if jx > 0 else 0.0
        dy = _clamp(random.gauss(0, jy / 2.0), -jy, jy) if jy > 0 else 0.0
        return hit.x + self.cfg.grab_offset[0] + dx, hit.y + self.cfg.grab_offset[1] + dy

    def solve(self, hit: Optional[Hit] = None) -> SolveResult:
        """只做自动拖拽（不检查保护器；保护器在 handle() 里检查）"""
        if not self.available:
            return SolveResult(STATUS_FAILED, 0, "模板不可用")
        if hit is None:
            hit = self.locate()
        if hit is None:
            return SolveResult(STATUS_NOT_FOUND, 0, "未发现滑块")

        attempts = max(1, int(self.cfg.max_attempts))
        for i in range(1, attempts + 1):
            if i == 1:
                wait = lognormal(*self.cfg.reaction)
                _log(f"发现滑块，模拟人类反应 {wait:.2f}s 后开始操作")
            else:
                wait = rand_in(self.cfg.retry_gap)
                _log(f"{wait:.2f}s 后进行第 {i} 次拖拽")
            interruptible_sleep(wait)

            fresh = self.locate()  # 等待期间页面可能位移或滑块已消失
            if fresh is None:
                if i == 1:
                    return SolveResult(STATUS_NOT_FOUND, 0, "反应等待期间滑块已消失")
                self._record(True)
                return SolveResult(STATUS_SOLVED, i - 1, "间隔期间滑块已消失")
            hit = fresh

            gx, gy = self._pick_grab_point(hit)
            jit = max(0, int(self.cfg.overshoot_jitter))
            total = self.cfg.distance + self.cfg.overshoot + random.randint(-(jit // 3), jit)
            total = max(total, self.cfg.distance + 5)
            _log(f"第 {i}/{attempts} 次：模板中心({hit.x},{hit.y}) 分数 {hit.score:.3f} "
                 f"→ 按住({gx:.1f},{gy:.1f}) 向右拖 {total}px")
            try:
                human_drag(gx, gy, total, self.cfg, target_w=hit.w or 40)
            except pyautogui.FailSafeException:
                raise
            except Exception as e:
                _log(f"拖拽异常：{e}")

            if self.wait_vanish(self.cfg.vanish_timeout):
                _log("滑块已消失，判定验证通过。")
                self._record(True)
                return SolveResult(STATUS_SOLVED, i, "ok")
            _log("拖拽后滑块仍在。")

        self._record(False)
        self._save_debug("fail")
        return SolveResult(STATUS_FAILED, attempts, "多次拖拽后仍未通过")

    def wait_manual(self, timeout: float, notify_text: str = "请手动完成滑块验证") -> SolveResult:
        timeout = max(5.0, float(timeout))
        _log(f"等待人工完成滑块验证（最多 {timeout:.0f} 秒）...")
        notify(f"{notify_text}（最多等待 {timeout:.0f} 秒）", "orange", 6000)
        deadline = time.time() + timeout
        miss = 0
        while time.time() < deadline:
            interruptible_sleep(1.0)
            if self.locate() is None:
                miss += 1
                if miss >= 2:
                    _log("滑块已消失（人工完成）。")
                    return SolveResult(STATUS_MANUAL_OK, 0, "人工完成")
            else:
                miss = 0
        self._save_debug("manual_timeout")
        return SolveResult(STATUS_MANUAL_TIMEOUT, 0, "人工验证等待超时")

    def handle(self, hit: Optional[Hit] = None, auto: bool = True, manual_fallback: bool = True,
               manual_timeout: float = 300.0, notify_text: str = "请手动完成滑块验证") -> SolveResult:
        """统一入口：auto=开关A；auto 失败/被暂停时按 manual_fallback 决定是否转人工"""
        if not self.available:
            return SolveResult(STATUS_FAILED, 0, "模板不可用")
        if hit is None:
            hit = self.locate()
        if hit is None:
            return SolveResult(STATUS_NOT_FOUND, 0, "未发现滑块")

        if auto:
            allowed, reason = (True, "") if self.guard is None else self.guard.allow()
            if allowed:
                res = self.solve(hit)
                if res.status in (STATUS_SOLVED, STATUS_NOT_FOUND):
                    return res
                if not manual_fallback:
                    return res
                _log("自动拖拽未通过，转为人工等待。")
                notify_text = f"{notify_text}（自动拖拽未通过）"
            else:
                _log(f"自动拖拽已暂停：{reason}")
                if not manual_fallback:
                    return SolveResult(STATUS_BLOCKED, 0, reason)
                notify_text = f"{notify_text}（自动已暂停：{reason}）"
        return self.wait_manual(manual_timeout, notify_text)


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
    ap = _Parser(description="通用拖拽滑块验证（拟人化）")
    ap.add_argument("template")
    ap.add_argument("--mode", choices=["auto", "manual", "detect"], default="auto")
    ap.add_argument("--manual-fallback", dest="manual_fallback", action="store_true", default=True)
    ap.add_argument("--no-manual-fallback", dest="manual_fallback", action="store_false")
    ap.add_argument("--manual-wait", type=float, default=300.0)
    ap.add_argument("--no-guard", action="store_true", help="关闭风控保护器（不建议）")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--distance", type=int, default=257)
    ap.add_argument("--overshoot", type=int, default=45)
    ap.add_argument("--grab-dx", type=int, default=0)
    ap.add_argument("--grab-dy", type=int, default=0)
    ap.add_argument("--duration", type=_range, default=(0.8, 1.6), help="如 0.8-1.6")
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--vanish-timeout", type=float, default=4.0)
    ap.add_argument("--wait", type=float, default=0.0, help="等待滑块出现的秒数；0=只看一眼")
    ap.add_argument("--after", choices=["none", "reload", "cmdr"], default="none",
                    help="仅在自动拖拽通过后执行")
    ap.add_argument("--app", default="Google Chrome")
    ap.add_argument("--pre-after-delay", type=float, default=1.0)
    ap.add_argument("--after-delay", type=float, default=2.5)
    ap.add_argument("--dry-run", action="store_true", help="等同 --mode detect")
    args = ap.parse_args(argv)

    mode = "detect" if args.dry_run else args.mode
    cfg = SliderConfig(
        template=args.template, threshold=args.threshold, distance=args.distance,
        overshoot=args.overshoot, grab_offset=(args.grab_dx, args.grab_dy),
        duration=args.duration, max_attempts=args.attempts, vanish_timeout=args.vanish_timeout,
        guard=None if args.no_guard else GuardPolicy(),
    )
    solver = SliderSolver(cfg)
    if not solver.available:
        print("SLIDER_ERROR")
        return EXIT_DEPENDENCY

    hit = solver.wait_appear(args.wait) if args.wait > 0 else solver.locate()
    if hit is None:
        print("SLIDER_NOT_FOUND")
        return EXIT_NOT_FOUND

    if mode == "detect":
        _log(f"[detect] 滑块中心=({hit.x},{hit.y}) 尺寸={hit.w}x{hit.h} 分数={hit.score:.3f} 缩放={solver.scale}")
        print("SLIDER_FOUND")
        return EXIT_SOLVED

    res = solver.handle(hit, auto=(mode == "auto"), manual_fallback=args.manual_fallback,
                        manual_timeout=args.manual_wait)
    _log(f"结果：{res.status}（{res.message}）")

    if res.status == STATUS_NOT_FOUND:
        print("SLIDER_NOT_FOUND")
        return EXIT_NOT_FOUND
    if res.status == STATUS_SOLVED:
        if args.after in ("reload", "cmdr"):
            sleep(rand_in((args.pre_after_delay * 0.7, args.pre_after_delay * 1.6)))
            reload_browser(args.app, use_applescript=(args.after == "reload"))
            sleep(args.after_delay * random.uniform(0.9, 1.3))
        print("SLIDER_SOLVED")
        return EXIT_SOLVED
    if res.status == STATUS_MANUAL_OK:
        print("SLIDER_MANUAL_OK")
        return EXIT_SOLVED
    print("SLIDER_BLOCKED" if res.status == STATUS_BLOCKED else "SLIDER_FAILED")
    return EXIT_FAILED


if __name__ == "__main__":
    try:
        sys.exit(main())
    except pyautogui.FailSafeException:
        print("用户将鼠标甩到屏幕角落，已中止。")
        print("SLIDER_ERROR")
        sys.exit(EXIT_USER_ABORT)