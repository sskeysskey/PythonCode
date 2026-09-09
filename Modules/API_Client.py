#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API_Client.py —— 统一的 OpenAI 兼容 API 客户端（千问 / DeepSeek）
供 News_Engine.scpt 调用，替代旧的 API_Close.py / API_Poe.py / API_Poe_Close.py。

用法:
    API_Client.py <provider> [选项]

provider:
    qianwen_api | qianwen | qwen      -> 阿里云百炼 DashScope 兼容模式
    deepseek_api | deepseek          -> DeepSeek 官方 API

选项:
    --mode normal|cheap      模型档位（默认 normal）
    --model NAME             直接指定模型，覆盖 --mode
    --from-clipboard         从剪贴板读取 Prompt（默认行为）
    --prompt-file PATH       从文件读取 Prompt
    --prompt TEXT            直接给出 Prompt
    --min-chinese N          结果至少含 N 个汉字才算合格（默认 50；0 = 只要求非空）
    --max-chars N            Prompt 超长时中段截断的字符上限（默认 120000）
    --timeout SEC            整体超时（默认 420）
    --retries N              瞬时错误重试次数（默认 2）
    --no-gui                 不弹窗，流式内容打到 stderr
    --out-file PATH          额外把结果写入文件
    --api-style chat|responses   默认 chat（chat/completions）

退出码（与 News_auto.py 保持同一套协议）:
    0  成功，结果已写入剪贴板
    1  结果不合格（太短 / 汉字不足）
    2  超时
    3  参数错误 / 依赖缺失
    4  API 调用失败（网络 / 鉴权 / 限流 / 余额）
    5  拒答或命中内容安全策略 -> 需要交接给下一个 AI
    6  用户手动关闭窗口（中止整个流程）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback

# ================= 退出码 =================
EXIT_OK = 0
EXIT_UNQUALIFIED = 1
EXIT_TIMEOUT = 2
EXIT_BAD_USAGE = 3
EXIT_API_ERROR = 4
EXIT_HANDOFF = 5
EXIT_ABORT = 6

SUCCESS_MARKER = "---API_RESPONSE_COMPLETE---"
ERROR_MARKER = "---API_RESPONSE_ERROR---"

USER_HOME = os.path.expanduser("~")
LOG_PATH = os.path.join(USER_HOME, "Coding", "News", "api_client.log")
LAST_RESULT_PATH = "/tmp/news_api_last_result.txt"

# 外部配置（优先级高于下面的内置默认值），格式示例：
# {
#   "qianwen": {"api_key": "sk-...", "models": {"normal": "qwen3.6-flash"}},
#   "deepseek": {"api_key": "sk-..."}
# }
CONFIG_CANDIDATES = [
    os.path.join(USER_HOME, ".config", "news_api_keys.json"),
    os.path.join(USER_HOME, "Coding", "python_code", "Modules", "api_keys.json"),
]

DEFAULT_PROVIDERS = {
    "qianwen": {
        "label": "千问API",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "sk-ws-H.PMYPYIH.lgsp.MEUCIFkboYDEKJnI53g7JWmqvaprHCLwhdhvwnWgiin78T3SAiEAkVnR4osNY5jKAK8K14uiP2G0mKmlBPXJKxH9Qib2o-E",
        "api_key_env": ["NEWS_QIANWEN_API_KEY", "DASHSCOPE_API_KEY"],
        "models": {"normal": "qwen3.6-flash", "cheap": "qwen3.6-flash"},
        "api_style": "chat",
        # 想强制关闭思考模式可写: {"enable_thinking": false}
        "extra_body": {"enable_thinking": False},
        "temperature": None,
        "max_tokens": None,
        "request_timeout": 180,
    },
    "deepseek": {
        "label": "DeepSeekAPI",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-e14a7491825942b9a8bea54fb3db8cae",
        "api_key_env": ["NEWS_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"],
        "models": {"normal": "deepseek-v4-flash", "cheap": "deepseek-v4-flash"},
        "api_style": "chat",
        "extra_body": {"enable_thinking": False},
        "temperature": None,
        "max_tokens": None,
        "request_timeout": 180,
    },
}

PROVIDER_ALIASES = {
    "qianwen": "qianwen", "qianwen_api": "qianwen", "qianwen-api": "qianwen",
    "qwen": "qianwen", "qwen_api": "qianwen", "tongyi": "qianwen", "tongyi_api": "qianwen",
    "deepseek": "deepseek", "deepseek_api": "deepseek", "deepseek-api": "deepseek",
    "ds": "deepseek", "ds_api": "deepseek",
}

# ================= 拒答识别 =================
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
    "抱歉，我不能提供",
    "我无法提供该内容",
]

# 服务端内容安全 / 拒答类错误特征
REFUSAL_MARKERS = [
    "data_inspection_failed", "datainspectionfailed", "data inspection failed",
    "inappropriate content", "content_filter", "contentfilter", "content filter",
    "content exists risk", "content_exists_risk", "risk control", "riskcontrol",
    "content_policy", "content policy", "invalid_prompt", "unsafe content",
    "sensitive", "内容安全", "违规", "敏感", "不合规", "涉及风险",
]

# 可重试的瞬时错误特征
TRANSIENT_MARKERS = [
    "timeout", "timed out", "connection", "connect error", "temporarily",
    "overloaded", "rate limit", "too many requests", "internal server error",
    "bad gateway", "service unavailable", "502", "503", "504", "read error",
    "remote end closed", "ssl",
]

# 额度 / 鉴权类（不重试，直接归为 API 错误）
FATAL_API_MARKERS = [
    "insufficient_quota", "insufficient balance", "arrearage", "quota exceeded",
    "allocated quota", "invalid_api_key", "incorrect api key", "authentication",
    "unauthorized", "permission", "access_denied", "model_not_found",
    "does not exist", "invalid_request_error",
]


# ================= 小工具 =================
def log_line(text):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def clipboard_get():
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        try:
            return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
        except Exception:
            return ""


def clipboard_set(text, verify=True, retries=3):
    for _ in range(retries):
        ok = False
        try:
            import pyperclip
            pyperclip.copy(text)
            ok = True
        except Exception:
            try:
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
                ok = True
            except Exception:
                ok = False
        if not ok:
            time.sleep(0.3)
            continue
        if not verify:
            return True
        time.sleep(0.15)
        back = clipboard_get()
        if back and back.strip() == text.strip():
            return True
        time.sleep(0.3)
    return False


def normalize_provider(raw):
    p = (raw or "").strip().lower()
    if p.endswith("_ui") or p.endswith("-ui"):
        print("错误：'%s' 是网页版 provider，请用 News_auto.py，不要用 API_Client.py" % raw)
        sys.exit(EXIT_BAD_USAGE)
    return PROVIDER_ALIASES.get(p, p)


def load_provider_cfg(name):
    cfg = json.loads(json.dumps(DEFAULT_PROVIDERS.get(name, {})))  # deep copy
    if not cfg:
        print("错误：未知 provider '%s'，可选：%s" % (name, list(DEFAULT_PROVIDERS.keys())))
        sys.exit(EXIT_BAD_USAGE)

    # 外部 json 覆盖
    for path in CONFIG_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            part = data.get(name) or {}
            for k, v in part.items():
                if k == "models" and isinstance(v, dict):
                    cfg.setdefault("models", {}).update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            log_line("读取配置 %s 失败: %s" % (path, e))

    # 环境变量优先
    for env_name in cfg.get("api_key_env", []) or []:
        val = os.environ.get(env_name)
        if val:
            cfg["api_key"] = val.strip()
            break

    if not cfg.get("api_key"):
        print("错误：provider '%s' 缺少 api_key" % name)
        sys.exit(EXIT_BAD_USAGE)
    return cfg


def strip_think_tags(text):
    if not text:
        return text
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.S)
    return text


def is_refusal_text(text):
    if not text:
        return False
    normalized = re.sub(r"\s+", "", text)
    return any(p in normalized for p in REFUSAL_PHRASES)


def is_qualified(text, min_chinese):
    if not text or not text.strip():
        return False
    if min_chinese <= 0:
        return len(text.strip()) >= 20
    return len(re.findall(r"[\u4e00-\u9fff]", text)) > min_chinese


def classify_exception(exc):
    """返回 refusal / transient / fatal"""
    pieces = [str(exc)]
    for attr in ("message", "body", "response"):
        try:
            v = getattr(exc, attr, None)
            if v is not None:
                pieces.append(repr(v)[:2000])
        except Exception:
            pass
    low = " ".join(pieces).lower()

    if any(m in low for m in REFUSAL_MARKERS):
        return "refusal"

    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    cls_name = type(exc).__name__.lower()

    if any(m in low for m in FATAL_API_MARKERS):
        return "fatal"
    if status in (408, 409, 429, 500, 502, 503, 504):
        return "transient"
    if "timeout" in cls_name or "connection" in cls_name or "apiconnection" in cls_name:
        return "transient"
    if any(m in low for m in TRANSIENT_MARKERS):
        return "transient"
    return "fatal"


def truncate_middle(text, max_chars):
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = int(max_chars * 0.65)
    tail = max_chars - head
    return text[:head] + "\n\n……（中间内容因长度限制已省略）……\n\n" + text[-tail:], True


# ================= 流式请求 =================
class Aborted(Exception):
    pass


def stream_once(cfg, model, prompt, on_delta, on_think, deadline, api_style, abort_check):
    try:
        import openai
    except ImportError:
        print("错误：未安装 openai 库，请执行 pip3 install openai")
        sys.exit(EXIT_BAD_USAGE)

    client = openai.OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=float(cfg.get("request_timeout") or 180),
        max_retries=0,
    )
    extra = dict(cfg.get("extra_body") or {})
    parts = []
    finish_reason = None

    if api_style == "responses":
        kwargs = dict(model=model, input=prompt, stream=True)
        if extra:
            kwargs["extra_body"] = extra
        stream = client.responses.create(**kwargs)
        for event in stream:
            if abort_check():
                raise Aborted()
            if time.time() > deadline:
                raise TimeoutError("整体超时")
            etype = getattr(event, "type", "") or ""
            if etype == "response.output_text.delta":
                d = getattr(event, "delta", "") or ""
                if d:
                    parts.append(d)
                    on_delta(d)
            elif etype == "response.reasoning_text.delta":
                on_think(getattr(event, "delta", "") or "")
            elif etype == "response.incomplete":
                finish_reason = "length"
            elif etype == "response.failed":
                raise RuntimeError("responses API 返回 failed: %s" % repr(getattr(event, "response", ""))[:800])
        return "".join(parts), finish_reason

    kwargs = dict(model=model, messages=[{"role": "user", "content": prompt}], stream=True)
    if extra:
        kwargs["extra_body"] = extra
    if cfg.get("temperature") is not None:
        kwargs["temperature"] = cfg["temperature"]
    if cfg.get("max_tokens"):
        kwargs["max_tokens"] = cfg["max_tokens"]

    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if abort_check():
            raise Aborted()
        if time.time() > deadline:
            raise TimeoutError("整体超时")
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        ch = choices[0]
        delta = getattr(ch, "delta", None)
        if delta is not None:
            content = getattr(delta, "content", None)
            if content:
                parts.append(content)
                on_delta(content)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                on_think(reasoning)
        fr = getattr(ch, "finish_reason", None)
        if fr:
            finish_reason = fr
    return "".join(parts), finish_reason


def run_request(cfg, model, prompt, callbacks, total_timeout, retries, api_style):
    """返回 dict: status = ok | refusal | timeout | error | abort"""
    on_delta = callbacks["delta"]
    on_think = callbacks["think"]
    on_status = callbacks["status"]
    on_reset = callbacks["reset"]
    abort_check = callbacks["abort_check"]

    deadline = time.time() + total_timeout
    attempt = 0
    last_msg = ""

    while attempt <= retries:
        attempt += 1
        try:
            if attempt > 1:
                on_reset()
                on_status("第 %d 次请求中…" % attempt)
            text, finish = stream_once(cfg, model, prompt, on_delta, on_think,
                                       deadline, api_style, abort_check)
            if finish == "content_filter":
                return {"status": "refusal", "message": "finish_reason=content_filter"}
            return {"status": "ok", "text": text, "finish": finish}
        except Aborted:
            return {"status": "abort", "message": "用户中止"}
        except TimeoutError as e:
            return {"status": "timeout", "message": str(e)}
        except Exception as e:
            kind = classify_exception(e)
            last_msg = "%s: %s" % (type(e).__name__, str(e)[:600])
            log_line("请求失败(%s / %s) %s" % (kind, model, last_msg))
            if kind == "refusal":
                return {"status": "refusal", "message": last_msg}
            if kind == "transient" and attempt <= retries and time.time() < deadline:
                on_status("请求失败，%d 秒后重试：%s" % (2 * attempt, last_msg[:120]))
                time.sleep(2 * attempt)
                continue
            return {"status": "error", "message": last_msg}
    return {"status": "error", "message": last_msg or "重试次数已用尽"}


# ================= GUI =================
MODERN_STYLESHEET = """
    QMainWindow { background-color: #2d2d2d; }
    QTextEdit {
        background-color: #222222; color: #e0e0e0;
        border: 1px solid #444; border-radius: 5px; padding: 10px;
        font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
        font-size: 19pt;
    }
    QLabel { color: #9aa0a6; font-size: 11pt; }
    QScrollBar:vertical { border: none; background: #2d2d2d; width: 12px;
        margin: 15px 0 15px 0; border-radius: 6px; }
    QScrollBar::handle:vertical { background-color: #555; min-height: 30px; border-radius: 6px; }
    QScrollBar::handle:vertical:hover { background-color: #666; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        border: none; background: none; height: 15px; }
"""


def run_with_gui(cfg, model, prompt, args):
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QTextEdit,
                                 QVBoxLayout, QWidget, QLabel)
    from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
    from PyQt6.QtGui import QTextCursor, QFont, QGuiApplication, QColor

    holder = {"result": None, "aborted": False}

    class Worker(QThread):
        sig_delta = pyqtSignal(str)
        sig_think = pyqtSignal(str)
        sig_status = pyqtSignal(str)
        sig_reset = pyqtSignal()
        sig_done = pyqtSignal(dict)

        def run(self):
            callbacks = {
                "delta": self.sig_delta.emit,
                "think": self.sig_think.emit,
                "status": self.sig_status.emit,
                "reset": self.sig_reset.emit,
                "abort_check": lambda: holder["aborted"],
            }
            res = run_request(cfg, model, prompt, callbacks,
                              args.timeout, args.retries, args.api_style)
            self.sig_done.emit(res)

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.first_chunk = True
            self.dots = 0
            self.finished = False
            self.init_ui()
            self.wait_timer = QTimer(self)
            self.wait_timer.timeout.connect(self.tick)
            self.wait_timer.start(500)
            self.worker = Worker()
            self.worker.sig_delta.connect(self.on_delta)
            self.worker.sig_think.connect(self.on_think)
            self.worker.sig_status.connect(self.on_status)
            self.worker.sig_reset.connect(self.on_reset)
            self.worker.sig_done.connect(self.on_done)
            QTimer.singleShot(80, self.worker.start)

        def init_ui(self):
            self.setWindowTitle("%s · %s" % (cfg.get("label", ""), model))
            self.resize(900, 640)
            self.center()
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(15, 15, 15, 15)
            layout.setSpacing(8)
            self.status = QLabel("准备中…（Esc 中止）")
            self.area = QTextEdit()
            self.area.setReadOnly(True)
            self.area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.area.setTextColor(QColor("lightgray"))
            self.area.setText("请稍候...")
            layout.addWidget(self.status)
            layout.addWidget(self.area)

        def center(self):
            geo = self.frameGeometry()
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo.moveCenter(screen.availableGeometry().center())
                self.move(geo.topLeft().x(), geo.topLeft().y() + 60)

        def keyPressEvent(self, event):
            if event.key() == Qt.Key.Key_Escape:
                if not self.finished:
                    holder["aborted"] = True
                    holder["result"] = {"status": "abort", "message": "用户按下 Esc"}
                self.close()
            super().keyPressEvent(event)

        def closeEvent(self, event):
            if not self.finished and holder["result"] is None:
                holder["aborted"] = True
                holder["result"] = {"status": "abort", "message": "窗口被关闭"}
            event.accept()

        def tick(self):
            if self.first_chunk:
                self.dots = (self.dots + 1) % 4
                self.area.setText("正在等待服务器响应%s" % ("." * self.dots).ljust(3))

        def ensure_started(self):
            if self.first_chunk:
                self.wait_timer.stop()
                self.area.clear()
                self.first_chunk = False

        def on_status(self, msg):
            self.status.setText(msg)

        def on_reset(self):
            self.area.clear()
            self.first_chunk = False

        def on_delta(self, text):
            self.ensure_started()
            self.area.setTextColor(QColor("white"))
            self.area.moveCursor(QTextCursor.MoveOperation.End)
            self.area.insertPlainText(text)
            self.area.ensureCursorVisible()

        def on_think(self, text):
            self.ensure_started()
            self.area.setTextColor(QColor("#7f8c8d"))
            self.area.moveCursor(QTextCursor.MoveOperation.End)
            self.area.insertPlainText(text)
            self.area.ensureCursorVisible()
            self.area.setTextColor(QColor("white"))

        def on_done(self, res):
            self.finished = True
            holder["result"] = res
            if res.get("status") == "ok":
                self.status.setText("完成，正在写入剪贴板…")
                QTimer.singleShot(150, QApplication.instance().quit)
            else:
                self.ensure_started()
                self.area.setTextColor(QColor("#ff5252"))
                self.area.moveCursor(QTextCursor.MoveOperation.End)
                self.area.insertPlainText("\n\n❌ [%s] %s" % (res.get("status"), res.get("message", "")))
                self.status.setText("失败：%s" % res.get("status"))
                QTimer.singleShot(2200, QApplication.instance().quit)

    app = QApplication(sys.argv[:1])
    font = QFont()
    font.setFamilies([".AppleSystemUIFont", "PingFang SC", "Microsoft YaHei"])
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(MODERN_STYLESHEET)
    win = Window()
    win.show()
    app.exec()
    return holder["result"] or {"status": "error", "message": "GUI 异常退出"}


def run_headless(cfg, model, prompt, args):
    callbacks = {
        "delta": lambda t: (sys.stderr.write(t), sys.stderr.flush()),
        "think": lambda t: None,
        "status": lambda m: (sys.stderr.write("\n[%s]\n" % m), sys.stderr.flush()),
        "reset": lambda: sys.stderr.write("\n---- 重试，重新开始 ----\n"),
        "abort_check": lambda: False,
    }
    return run_request(cfg, model, prompt, callbacks, args.timeout, args.retries, args.api_style)


# ================= 主流程 =================
def main():
    parser = argparse.ArgumentParser(description="统一 OpenAI 兼容 API 客户端")
    parser.add_argument("provider")
    parser.add_argument("--mode", default="normal", choices=["normal", "cheap"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--from-clipboard", action="store_true")
    parser.add_argument("--prompt-file", default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--min-chinese", type=int, default=50)
    parser.add_argument("--max-chars", type=int, default=120000)
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--out-file", default=None)
    parser.add_argument("--api-style", default=None, choices=["chat", "responses"])
    args = parser.parse_args()

    name = normalize_provider(args.provider)
    cfg = load_provider_cfg(name)
    model = args.model or (cfg.get("models") or {}).get(args.mode) \
        or (cfg.get("models") or {}).get("normal")
    if not model:
        print("错误：未能确定模型名称")
        sys.exit(EXIT_BAD_USAGE)
    args.api_style = args.api_style or cfg.get("api_style") or "chat"

    # ---- 取 Prompt ----
    if args.prompt is not None:
        prompt = args.prompt
    elif args.prompt_file:
        try:
            with open(args.prompt_file, "r", encoding="utf-8") as f:
                prompt = f.read()
        except Exception as e:
            print("错误：读取 prompt 文件失败：%s" % e)
            sys.exit(EXIT_BAD_USAGE)
    else:
        prompt = clipboard_get()

    prompt = (prompt or "").strip()
    if len(prompt) < 30:
        print("错误：Prompt 为空或过短（%d 字符）" % len(prompt))
        sys.exit(EXIT_BAD_USAGE)

    prompt, truncated = truncate_middle(prompt, args.max_chars)
    if truncated:
        log_line("Prompt 超过 %d 字符，已中段截断" % args.max_chars)

    # ---- 发请求 ----
    use_gui = not args.no_gui
    if use_gui:
        try:
            import PyQt6  # noqa: F401
        except ImportError:
            use_gui = False
            sys.stderr.write("未安装 PyQt6，自动切换到无窗口模式\n")

    if use_gui:
        res = run_with_gui(cfg, model, prompt, args)
    else:
        res = run_headless(cfg, model, prompt, args)

    status = res.get("status")

    if status == "abort":
        print(ERROR_MARKER + " ABORT")
        sys.exit(EXIT_ABORT)
    if status == "refusal":
        log_line("[%s/%s] 拒答/内容安全：%s" % (name, model, res.get("message", "")))
        print(ERROR_MARKER + " REFUSAL: %s" % res.get("message", ""))
        sys.exit(EXIT_HANDOFF)
    if status == "timeout":
        log_line("[%s/%s] 超时：%s" % (name, model, res.get("message", "")))
        print(ERROR_MARKER + " TIMEOUT")
        sys.exit(EXIT_TIMEOUT)
    if status != "ok":
        log_line("[%s/%s] API 错误：%s" % (name, model, res.get("message", "")))
        print(ERROR_MARKER + " API_ERROR: %s" % res.get("message", ""))
        sys.exit(EXIT_API_ERROR)

    text = strip_think_tags(res.get("text") or "").strip()

    try:
        with open(LAST_RESULT_PATH, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    if is_refusal_text(text):
        log_line("[%s/%s] 正文命中拒答话术" % (name, model))
        print(ERROR_MARKER + " REFUSAL_TEXT")
        sys.exit(EXIT_HANDOFF)

    if not is_qualified(text, args.min_chinese):
        cn = len(re.findall(r"[\u4e00-\u9fff]", text))
        log_line("[%s/%s] 内容不合格：总长 %d，汉字 %d（阈值 %d）"
                 % (name, model, len(text), cn, args.min_chinese))
        print(ERROR_MARKER + " UNQUALIFIED len=%d cn=%d" % (len(text), cn))
        sys.exit(EXIT_UNQUALIFIED)

    if args.out_file:
        try:
            with open(args.out_file, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            log_line("写出文件失败：%s" % e)

    if not clipboard_set(text):
        print(ERROR_MARKER + " CLIPBOARD_FAIL")
        log_line("[%s/%s] 剪贴板写入失败" % (name, model))
        sys.exit(EXIT_API_ERROR)

    print("%s len=%d" % (SUCCESS_MARKER, len(text)))
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log_line("未捕获异常：\n" + traceback.format_exc())
        print(ERROR_MARKER + " UNCAUGHT")
        sys.exit(EXIT_API_ERROR)