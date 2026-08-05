#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
whisper_mlx_core.py
MLX-Whisper 字幕生成核心（被 whisper_mlx_auto.py / whisper_mlx_manual.py 共用）

设计要点（针对“复读”与“时间轴漂移”）：
1. condition_on_previous_text=False        -> 断掉跨窗口复读链
2. 能量 VAD 只解码有语音的区段             -> 静音段不产生幻觉，且提速
3. 词级 VAD 过滤 + cue 起点吸附到语音起点  -> 幻觉词被丢弃，时间轴对齐真实语音
4. 音频链保持时间轴无损（默认不用 loudnorm/afftdn/acompressor）
5. 段级质量过滤 + 句内重复折叠 + 字幕级去重
"""

from __future__ import annotations

import inspect
import logging
import pathlib
import platform
import random
import re
import shutil
import subprocess
import threading
import time
from bisect import bisect_right
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import mlx.core as mx
import mlx_whisper

# ---------------------------------------------------------------- 可选依赖
try:
    import pyautogui

    pyautogui.FAILSAFE = False
    _HAS_PYAUTOGUI = True
except Exception:
    _HAS_PYAUTOGUI = False


# ================================================================ 日志
def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )


# ================================================================ 常量 / 配置
FFMPEG_BIN = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

MODELS = {
    "tiny-q4": "mlx-community/whisper-tiny-mlx-q4",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "small-q4": "mlx-community/whisper-small.en-mlx-q4",
    "small-fp32": "mlx-community/whisper-small-mlx-fp32",
}
DEFAULT_MODEL = "large-v3"
DEFAULT_LANGUAGE: Optional[str] = None  # None = 自动检测；也可写 "zh" / "en"

DEFAULT_MEDIA_DIR = pathlib.Path("/Users/yanzhang/Downloads/Videos/MLX_Whisper")

MEDIA_EXTS = {
    ".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".flv", ".ts", ".mpg", ".mpeg",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
}

# ---- 音频：默认只做“不会破坏时间轴”的处理 -------------------------------
AUDIO_PARAMS = {
    "sample_rate": 16000,
    "highpass_hz": 70,          # 去低频隆隆声；最小相位，延迟可忽略。0 = 关闭
    "peak_normalize": True,     # numpy 峰值归一（完全不改时间轴）
    "peak_target": 0.95,
    "max_gain": 8.0,
    # 下面这个默认关闭！afftdn/acompressor/loudnorm 会改动包络甚至整体延迟，
    # 直接导致 whisper 的词级时间戳漂移。只有原声非常糟糕时才临时打开。
    "aggressive_enhance": False,
}

# ---- VAD（纯 numpy 能量法）--------------------------------------------
VAD_PARAMS = {
    "enabled": True,
    "frame_ms": 30,
    "hop_ms": 10,
    "rel_db": 9.0,          # 高于噪声底多少 dB 算语音（调小=更敏感）
    "floor_db": -48.0,      # 绝对下限
    "min_speech": 0.20,     # 短于此的语音块丢掉（秒）
    "min_silence": 0.35,    # 短于此的静音不切断（秒）
    "chunk_pad": 0.25,      # 送去解码时前后各留一点（秒）
    "word_pad": 0.45,       # 判断“词是否落在语音里”的宽容度（秒）
    "max_chunk": 28.0,      # 合并后单块最长时长（秒）
    "max_drop_ratio": 0.60, # 若要丢掉的词超过此比例，则放弃词级过滤（安全阀）
    "snap_max_shift": 1.5,  # cue 起点最多向后吸附多少秒
}

# ---- Whisper 解码参数 -------------------------------------------------
WHISPER_PARAMS: Dict[str, Any] = {
    "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    "condition_on_previous_text": False,   # ★ 关键：禁止跨窗口复读
    "word_timestamps": True,
    "prepend_punctuations": "\"'“¿([{-",
    "append_punctuations": "\"'.。,，!！?？:：”)]}、",
    "compression_ratio_threshold": 2.2,
    "logprob_threshold": -1.0,
    "no_speech_threshold": 0.5,
    "hallucination_silence_threshold": 2.0,  # 若当前 mlx_whisper 不支持会自动忽略
}

# ---- 段级质量过滤 ------------------------------------------------------
SEG_FILTER = {
    "max_compression_ratio": 2.6,   # 太“可压缩”= 重复啰嗦
    "min_avg_logprob": -1.10,
    "no_speech_prob": 0.80,
}

# ---- 字幕排版 ---------------------------------------------------------
SUB_MAX_WIDTH = 42      # 显示宽度（中文算 2，英文算 1）→ 约 21 个汉字
SUB_MAX_DUR = 6.0
SUB_MIN_DUR = 0.80
SUB_HARD_MAX_DUR = 9.0
SUB_MAX_GAP = 0.70      # 词间停顿超过此值断句
SUB_GAP = 0.04          # 相邻字幕最小间隔
DROP_INTERJECTION_CUES = True   # 丢掉整条只有“哦/嗯/呃…”的字幕


# ================================================================ 防挂机
def _mouse_loop() -> None:
    if not _HAS_PYAUTOGUI:
        logging.debug("未安装 pyautogui，跳过防挂机鼠标移动。")
        return
    while True:
        try:
            w, h = pyautogui.size()
            pyautogui.moveTo(random.randint(100, w - 100),
                             random.randint(100, h - 100), duration=1)
            time.sleep(random.randint(30, 60))
        except Exception as e:
            logging.debug(f"鼠标移动出错: {e}")
            time.sleep(30)


def start_anti_idle() -> None:
    threading.Thread(target=_mouse_loop, daemon=True).start()


# ================================================================ 工具
def check_ffmpeg() -> bool:
    if shutil.which("ffmpeg") or pathlib.Path(FFMPEG_BIN).exists():
        return True
    logging.error(f"找不到 ffmpeg（尝试路径: {FFMPEG_BIN}），请先 brew install ffmpeg。")
    return False


def fmt_hms(sec: float) -> str:
    sec = max(0.0, float(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def format_timestamp(sec: float, vtt: bool = False) -> str:
    sec = max(0.0, float(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    out = f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    return out if vtt else out.replace(".", ",")


def _display_width(text: str) -> int:
    w = 0
    for ch in text:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


# ================================================================ 音频加载
def load_audio(path: str) -> np.ndarray:
    """一次 ffmpeg 解码为 16k / mono / float32，尽量不破坏时间轴。"""
    sr = int(AUDIO_PARAMS["sample_rate"])
    filters: List[str] = []

    if AUDIO_PARAMS["aggressive_enhance"]:
        # 注意：这些滤镜会改动包络（loudnorm 还有 3s lookahead），可能让词级时间戳漂移
        filters += [
            "afftdn=nf=-25",
            "acompressor=threshold=-12dB:ratio=2:attack=200:release=1000",
            "loudnorm=I=-16:LRA=11:TP=-1.5",
        ]
    hp = AUDIO_PARAMS.get("highpass_hz") or 0
    if hp:
        filters.append(f"highpass=f={int(hp)}")

    cmd = [
        FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", path,
        "-vn", "-sn", "-dn", "-map", "0:a:0?",
    ]
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(sr), "-ac", "1", "-"]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "ignore").strip()[-500:]
        raise RuntimeError(f"ffmpeg 解码失败: {err or '无音频轨？'}")

    audio = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)

    if AUDIO_PARAMS["peak_normalize"] and audio.size:
        peak = float(np.max(np.abs(audio)))
        if peak > 1e-6:
            gain = min(AUDIO_PARAMS["peak_target"] / peak, AUDIO_PARAMS["max_gain"])
            if gain > 1.0 or peak > 1.0:
                audio = (audio * gain).astype(np.float32)

    return audio


# ================================================================ VAD
def detect_speech_regions(audio: np.ndarray, sr: int) -> List[Tuple[float, float]]:
    """返回 [(start, end), ...]（秒，未加 padding）。失败时返回整段。"""
    total = len(audio) / sr if sr else 0.0
    if total <= 0:
        return []
    if not VAD_PARAMS["enabled"]:
        return [(0.0, total)]

    frame = max(1, int(sr * VAD_PARAMS["frame_ms"] / 1000))
    hop = max(1, int(sr * VAD_PARAMS["hop_ms"] / 1000))
    if len(audio) < frame * 3:
        return [(0.0, total)]

    x = audio.astype(np.float64)
    cs = np.concatenate(([0.0], np.cumsum(x * x)))          # 前缀和，省内存
    idx = np.arange(0, len(audio) - frame + 1, hop)
    energy = (cs[idx + frame] - cs[idx]) / frame
    db = 10.0 * np.log10(energy + 1e-12)

    noise = float(np.percentile(db, 15))
    loud = float(np.percentile(db, 95))
    if loud - noise < 6.0:                                   # 动态范围太小，无法可靠区分
        logging.info("  VAD: 动态范围过小，按整段处理。")
        return [(0.0, total)]

    thr = max(noise + VAD_PARAMS["rel_db"], VAD_PARAMS["floor_db"])
    thr = min(thr, loud - 6.0)
    mask = (db > thr).astype(np.int8)

    d = np.diff(np.concatenate(([0], mask, [0])))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    regions = [
        (float(idx[s]) / sr, float(idx[e - 1] + frame) / sr)
        for s, e in zip(starts, ends)
    ]
    if not regions:
        logging.info("  VAD: 未检测到语音，按整段处理。")
        return [(0.0, total)]

    # 合并近邻 + 丢掉过短
    merged: List[List[float]] = [list(regions[0])]
    for s, e in regions[1:]:
        if s - merged[-1][1] <= VAD_PARAMS["min_silence"]:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    out = [(max(0.0, s), min(total, e)) for s, e in merged
           if (e - s) >= VAD_PARAMS["min_speech"]]
    if not out:
        return [(0.0, total)]

    speech = sum(e - s for s, e in out)
    logging.info(f"  VAD: {len(out)} 段语音，共 {speech:.1f}s / {total:.1f}s "
                 f"({speech / total * 100:.0f}%)")
    return out


def build_chunks(regions: List[Tuple[float, float]], total: float) -> List[Tuple[float, float]]:
    """把语音区段合并成 ≤ max_chunk 的解码块；切点一定落在静音里。"""
    if not regions:
        return [(0.0, total)]
    pad = VAD_PARAMS["chunk_pad"]
    mx_len = VAD_PARAMS["max_chunk"]

    chunks: List[List[float]] = []
    for s, e in regions:
        s = max(0.0, s - pad)
        e = min(total, e + pad)
        if chunks and (e - chunks[-1][0]) <= mx_len:
            chunks[-1][1] = e
        else:
            chunks.append([s, e])
    return [(a, b) for a, b in chunks if b - a > 0.05]


# ================================================================ 幻觉文案
_HALLU_RE = re.compile(
    r"(字幕(由|组|制作|志愿者)|請不吝|请不吝|订阅|訂閱|点赞|按赞|"
    r"谢谢(大家的?)?(观看|收看|觀看)|感谢观看|感謝觀看|"
    r"Amara\.org|subtitles?\s+by|subscribe\s+to|"
    r"明镜与点点栏目|MING\s*PAO)",
    re.IGNORECASE,
)
_EN_FILLER_RE = re.compile(
    r"^\s*(um+|uh+|er+|erm+|ah+|hmm+|mm+|mhm+)\s*[,.\u3002\uff0c]?\s*$", re.IGNORECASE
)
_INTERJ_CUE_RE = re.compile(r"^[\s]*[哦嗯呃啊唉噢哎呀哈嘿咦喔噫欸]{1,3}[\s。，,.!！?？…、~]*$")
_NORM_RE = re.compile(r"[\s。，、,.!！?？:：;；\-—…\"'“”‘’()（）\[\]{}]+")


def _norm_text(t: str) -> str:
    return _NORM_RE.sub("", t or "").lower()


# ================================================================ 文本清理
def collapse_repeats(text: str) -> str:
    """折叠句内的病态重复：'好好好好好' / 'A A A A' / '哈哈哈哈哈哈'。"""
    if not text or len(text) > 2000:
        return text
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"(.{2,30}?)\1{2,}", r"\1", text)                  # 短语重复 ≥3 次
        text = re.sub(r"\b(\w+)(?:\s+\1\b){2,}", r"\1", text, flags=re.I)  # 单词重复 ≥3 次
        text = re.sub(r"(.)\1{4,}", r"\1\1\1", text)                     # 单字重复 ≥5 次
    return text


def post_process_text(text: str) -> str:
    text = collapse_repeats(text)
    text = re.sub(r"(\d+)\s+([a-zA-Z])", r"\1\2", text)
    text = re.sub(r"([。，！？!?])\1+", r"\1", text)
    text = re.sub(r"\.{3,}", "...", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# ================================================================ 解码
try:
    _TRANSCRIBE_PARAMS = set(inspect.signature(mlx_whisper.transcribe).parameters)
except Exception:
    _TRANSCRIBE_PARAMS = set()

_DECODE_SAFE = {"language", "task", "initial_prompt", "beam_size", "best_of",
                "patience", "length_penalty", "suppress_tokens", "without_timestamps"}


def _filter_kwargs(opts: Dict[str, Any]) -> Dict[str, Any]:
    if not _TRANSCRIBE_PARAMS:
        return dict(opts)
    out = {}
    for k, v in opts.items():
        if k in _TRANSCRIBE_PARAMS or k in _DECODE_SAFE:
            out[k] = v
        else:
            logging.debug(f"当前 mlx_whisper 不支持参数 {k}，已忽略。")
    return out


def _transcribe_once(seg: np.ndarray, model_repo: str,
                     language: Optional[str]) -> Dict[str, Any]:
    opts = dict(WHISPER_PARAMS)
    if language:
        opts["language"] = language
    opts = _filter_kwargs(opts)
    try:
        return mlx_whisper.transcribe(
            mx.array(seg), path_or_hf_repo=model_repo, verbose=False, **opts
        )
    except TypeError as e:
        logging.debug(f"transcribe 参数不兼容({e})，去掉可选参数重试。")
        for k in ("hallucination_silence_threshold", "prepend_punctuations",
                  "append_punctuations"):
            opts.pop(k, None)
        return mlx_whisper.transcribe(
            mx.array(seg), path_or_hf_repo=model_repo, verbose=False, **opts
        )


def _is_bad_segment(seg: Dict[str, Any]) -> Tuple[bool, str]:
    txt = (seg.get("text") or "").strip()
    if not txt:
        return True, "空文本"
    cr = seg.get("compression_ratio")
    if cr is not None and cr > SEG_FILTER["max_compression_ratio"]:
        return True, f"压缩比 {cr:.2f} 过高（重复）"
    alp = seg.get("avg_logprob")
    if alp is not None and alp < SEG_FILTER["min_avg_logprob"]:
        return True, f"平均logprob {alp:.2f} 过低"
    nsp = seg.get("no_speech_prob")
    if nsp is not None and nsp > SEG_FILTER["no_speech_prob"] and (alp is None or alp < -0.4):
        return True, f"no_speech_prob {nsp:.2f} 过高"
    if _HALLU_RE.search(txt) and len(txt) <= 28:
        return True, "命中幻觉文案黑名单"
    return False, ""


def _extract_words(result: Dict[str, Any], offset: float,
                   lo: float, hi: float) -> List[Dict[str, Any]]:
    words: List[Dict[str, Any]] = []
    for seg in result.get("segments", []) or []:
        bad, why = _is_bad_segment(seg)
        if bad:
            logging.info(f"    ✂ 丢弃可疑片段（{why}）: "
                         f"{(seg.get('text') or '').strip()[:40]}")
            continue

        seg_words = seg.get("words") or []
        if not seg_words:  # 没词级时间戳时退化为整段
            txt = (seg.get("text") or "").strip()
            if txt:
                seg_words = [{"word": txt,
                              "start": seg.get("start", 0.0),
                              "end": seg.get("end", 0.0)}]
        for w in seg_words:
            tok = w.get("word", "")
            if not tok.strip():
                continue
            try:
                s = float(w.get("start", 0.0)) + offset
                e = float(w.get("end", s)) + offset
            except (TypeError, ValueError):
                continue
            s = min(max(s, lo), hi)
            e = min(max(e, s), hi)
            words.append({"word": tok, "start": s, "end": e,
                          "prob": float(w.get("probability", 1.0) or 1.0)})
    return words


def transcribe_chunks(audio: np.ndarray, sr: int,
                      chunks: List[Tuple[float, float]],
                      model_repo: str,
                      language: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    words: List[Dict[str, Any]] = []
    lang = language
    total = len(chunks)
    for i, (cs, ce) in enumerate(chunks, 1):
        a = audio[int(cs * sr): int(ce * sr)]
        if a.size < int(0.10 * sr):
            continue
        logging.info(f"  [{i}/{total}] 解码 {fmt_hms(cs)} → {fmt_hms(ce)}  ({ce - cs:.1f}s)")
        res = _transcribe_once(a, model_repo, lang)
        if lang is None:
            lang = res.get("language") or None
            if lang:
                logging.info(f"  → 检测到语言: {lang}（后续块沿用，避免语种跳变）")
        words.extend(_extract_words(res, offset=cs, lo=cs, hi=ce + 0.5))

    words.sort(key=lambda w: (w["start"], w["end"]))
    return words, lang


# ================================================================ 词级 VAD 过滤
def filter_words_by_speech(words: List[Dict[str, Any]],
                           regions: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    if not words or not regions or not VAD_PARAMS["enabled"]:
        return words
    pad = VAD_PARAMS["word_pad"]
    spans = [(max(0.0, s - pad), e + pad) for s, e in regions]
    starts = [s for s, _ in spans]

    kept, dropped = [], []
    for w in words:
        j = bisect_right(starts, w["end"]) - 1
        ok = False
        for k in (j - 1, j, j + 1):
            if 0 <= k < len(spans):
                s, e = spans[k]
                if (w["end"] > s and w["start"] < e):
                    ok = True
                    break
        (kept if ok else dropped).append(w)

    if not dropped:
        return words
    if len(dropped) > len(words) * VAD_PARAMS["max_drop_ratio"]:
        logging.warning("  VAD 判定要丢弃的词过多，已放弃词级过滤（可调小 VAD_PARAMS['rel_db']）。")
        return words
    logging.info(f"  依据静音检测丢弃 {len(dropped)} 个疑似幻觉词。")
    return kept


# ================================================================ 分句成 cue
def words_to_cues(words: List[Dict[str, Any]],
                  remove_fillers: bool = True) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for w in words:
        tok = w.get("word", "")
        if not tok.strip():
            continue
        if remove_fillers and _EN_FILLER_RE.match(tok):
            continue
        filtered.append(w)

    cues: List[Dict[str, Any]] = []
    group: List[Dict[str, Any]] = []
    width = 0

    def finalize(g: List[Dict[str, Any]]) -> None:
        if not g:
            return
        text = post_process_text("".join(x["word"] for x in g))
        if not text:
            return
        if DROP_INTERJECTION_CUES and _INTERJ_CUE_RE.match(text):
            logging.debug(f"丢弃单独语气词字幕: {text}")
            return
        if _HALLU_RE.search(text) and len(text) <= 28:
            logging.info(f"    ✂ 丢弃幻觉文案: {text}")
            return
        cues.append({"start": g[0]["start"], "end": g[-1]["end"], "text": text})

    for w in filtered:
        tok_w = _display_width(w["word"].strip())
        if group:
            gap = w["start"] - group[-1]["end"]
            dur = group[-1]["end"] - group[0]["start"]
            last = group[-1]["word"].strip()
            ends_sentence = bool(re.search(r"[.!?。！？…]$", last))
            if (width + tok_w > SUB_MAX_WIDTH
                    or dur >= SUB_MAX_DUR
                    or gap > SUB_MAX_GAP
                    or ends_sentence):
                finalize(group)
                group, width = [], 0
        group.append(w)
        width += tok_w
    finalize(group)
    return cues


# ================================================================ 复读去重
def drop_repeated_cues(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """1) 连续相同文本的 run 只保留首条；2) 25s 滑窗内同一句最多 2 次。"""
    if not cues:
        return cues

    # --- 连续 run ---
    stage1: List[Dict[str, Any]] = []
    i = 0
    while i < len(cues):
        key = _norm_text(cues[i]["text"])
        j = i + 1
        while j < len(cues) and key and _norm_text(cues[j]["text"]) == key:
            j += 1
        run = cues[i:j]
        if len(run) == 1 or not key:
            stage1.extend(run)
        else:
            keep = 1 if len(key) >= 4 else min(2, len(run))
            logging.info(f"  ⚠ 检测到复读 {len(run)} 次，仅保留 {keep} 条: "
                         f"“{cues[i]['text'][:24]}”")
            stage1.extend(run[:keep])
        i = j

    # --- 滑窗 ---
    out: List[Dict[str, Any]] = []
    hist: List[Tuple[str, float]] = []
    for c in stage1:
        key = _norm_text(c["text"])
        if len(key) >= 4:
            hist = [h for h in hist if c["start"] - h[1] <= 25.0]
            if sum(1 for h in hist if h[0] == key) >= 2:
                logging.info(f"  ⚠ 短时间内第 3 次出现，丢弃: “{c['text'][:24]}”")
                continue
        hist.append((key, c["start"]))
        out.append(c)
    return out


# ================================================================ 时间轴修正
def snap_cues_to_speech(cues: List[Dict[str, Any]],
                        regions: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    """若 cue 起点落在静音里，把它向后吸附到真正的语音起点（修“字幕比语音早”）。"""
    if not cues or not regions or not VAD_PARAMS["enabled"]:
        return cues
    starts = [s for s, _ in regions]
    limit = VAD_PARAMS["snap_max_shift"]
    for c in cues:
        j = bisect_right(starts, c["start"]) - 1
        inside = j >= 0 and c["start"] <= regions[j][1]
        if inside:
            continue
        k = bisect_right(starts, c["start"])
        if k < len(regions):
            onset = regions[k][0]
            if 0 < onset - c["start"] <= limit and onset < c["end"] - 0.15:
                c["start"] = onset
    return cues


def adjust_cue_timing(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cues.sort(key=lambda c: (c["start"], c["end"]))
    n = len(cues)
    for i, c in enumerate(cues):
        c["start"] = max(0.0, c["start"])
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + SUB_MIN_DUR
        if c["end"] - c["start"] > SUB_HARD_MAX_DUR:
            c["end"] = c["start"] + SUB_HARD_MAX_DUR
        if c["end"] - c["start"] < SUB_MIN_DUR:
            want = c["start"] + SUB_MIN_DUR
            if i + 1 < n:
                want = min(want, cues[i + 1]["start"] - SUB_GAP)
            c["end"] = max(c["end"], want)
        if i + 1 < n and c["end"] > cues[i + 1]["start"] - SUB_GAP:
            c["end"] = max(cues[i + 1]["start"] - SUB_GAP, c["start"] + 0.20)
    return cues


# ================================================================ 写文件
def write_subtitles(cues: List[Dict[str, Any]], fmt: str, out_path: str) -> None:
    fmt = fmt.lower()
    with open(out_path, "w", encoding="utf-8") as f:
        if fmt == "vtt":
            f.write("WEBVTT\n\n")
        for idx, c in enumerate(cues, start=1):
            a = format_timestamp(c["start"], vtt=(fmt == "vtt"))
            b = format_timestamp(c["end"], vtt=(fmt == "vtt"))
            line = " ".join(c["text"].split())
            if fmt == "srt":
                f.write(f"{idx}\n{a} --> {b}\n{line}\n\n")
            else:
                f.write(f"{a} --> {b}\n{line}\n\n")


# ================================================================ 主流程
def run_pipeline(media_path: str,
                 model_key: str = DEFAULT_MODEL,
                 language: Optional[str] = DEFAULT_LANGUAGE,
                 fmt: str = "srt",
                 remove_fillers: bool = True) -> bool:
    try:
        logging.info(f"▶ 开始处理: {media_path}")
        repo = MODELS.get(model_key, model_key)
        sr = int(AUDIO_PARAMS["sample_rate"])

        audio = load_audio(media_path)
        total = len(audio) / sr
        logging.info(f"  音频时长 {fmt_hms(total)}（{total / 60:.1f} 分钟）")
        if total < 0.2:
            logging.warning("  音频太短或无有效音频，跳过。")
            return False

        regions = detect_speech_regions(audio, sr)
        chunks = build_chunks(regions, total)

        words, lang = transcribe_chunks(audio, sr, chunks, repo, language)
        logging.info(f"  原始识别 {len(words)} 个词")

        words = filter_words_by_speech(words, regions)

        cues = words_to_cues(words, remove_fillers=remove_fillers)
        cues = drop_repeated_cues(cues)
        cues = snap_cues_to_speech(cues, regions)
        cues = adjust_cue_timing(cues)

        if not cues:
            logging.warning("  没有可写入的字幕内容（可能整段无语音）。")
            return False

        out_path = str(pathlib.Path(media_path).with_suffix("." + fmt))
        write_subtitles(cues, fmt, out_path)
        logging.info(f"✔ 已保存 {len(cues)} 条字幕: {out_path}")
        return True

    except KeyboardInterrupt:
        raise
    except Exception as e:
        logging.error(f"处理 {media_path} 时出错: {e}", exc_info=True)
        return False


def process_file(media: pathlib.Path,
                 model_key: str = DEFAULT_MODEL,
                 language: Optional[str] = DEFAULT_LANGUAGE,
                 fmt: str = "srt",
                 overwrite: bool = False) -> str:
    """返回 'done' / 'skipped' / 'failed'。"""
    out = media.with_suffix("." + fmt)
    if out.exists() and not overwrite:
        logging.info(f"已存在字幕，跳过: {media.name}")
        return "skipped"
    return "done" if run_pipeline(str(media), model_key, language, fmt) else "failed"


# ================================================================ 文件对话框
def _bring_to_front() -> None:
    if platform.system() != "Darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell app "System Events" to set frontmost of first process '
             'whose unix id is (do shell script "echo $PPID") to true'],
            check=False, capture_output=True, timeout=3)
    except Exception:
        pass


def _initial_dir() -> Optional[str]:
    return str(DEFAULT_MEDIA_DIR) if DEFAULT_MEDIA_DIR.exists() else None


def select_directory(title: str = "请选择包含视频文件的文件夹") -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    _bring_to_front()
    path = filedialog.askdirectory(title=title, initialdir=_initial_dir())
    root.destroy()
    return path or None


def select_files(multiple: bool = False,
                 title: str = "请选择视频/音频文件") -> List[str]:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    _bring_to_front()
    patterns = " ".join(f"*{e}" for e in sorted(MEDIA_EXTS))
    filetypes = [("媒体文件", patterns), ("所有文件", "*.*")]
    if multiple:
        res = filedialog.askopenfilenames(title=title, initialdir=_initial_dir(),
                                          filetypes=filetypes)
        paths = list(res)
    else:
        p = filedialog.askopenfilename(title=title, initialdir=_initial_dir(),
                                       filetypes=filetypes)
        paths = [p] if p else []
    root.destroy()
    return [p for p in paths if p]


def find_media_files(directory: pathlib.Path, recursive: bool = False) -> List[pathlib.Path]:
    it = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in MEDIA_EXTS)