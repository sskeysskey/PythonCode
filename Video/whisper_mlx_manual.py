import os
import pathlib
import subprocess
import logging
import re
import platform
import shutil
from typing import List, Dict, Any, Optional

import numpy as np
import mlx.core as mx
import mlx_whisper

import tkinter as tk
from tkinter import filedialog

import time
import random
import threading

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # 避免移到角落时抛异常
    _HAS_PYAUTOGUI = True
except Exception:
    _HAS_PYAUTOGUI = False

# ============ 配置 logging =============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)

# ============ 常量 =============
# 自动探测 ffmpeg，找不到再退回默认路径
FFMPEG_BIN = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

MODELS = {
    "tiny-q4":    "mlx-community/whisper-tiny-mlx-q4",
    "large-v3":   "mlx-community/whisper-large-v3-mlx",
    "small-q4":   "mlx-community/whisper-small.en-mlx-q4",
    "small-fp32": "mlx-community/whisper-small-mlx-fp32",
}
LANGUAGES = {
    "auto": None,
    "en": "English",
    "zh": "Chinese",
    "es": "Spanish",
}

DEFAULT_VIDEO_DIR = pathlib.Path("/Users/yanzhang/Downloads/Videos/MLX_Whisper")
TEMP_DIR = pathlib.Path("/tmp")

# 支持的视频/音频后缀
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".flv",
              ".mp3", ".wav", ".m4a", ".aac", ".flac"}

AUDIO_PARAMS = {
    "sample_rate": 16000,
    "normalize_volume": True,
    "remove_noise": True,
    "voice_enhance": True,
}

# 关键修复点：使用温度回退元组而不是单一 0.0，
# 否则中间某个窗口解码失败时无法重试，会被直接丢弃 -> 中间整段空白。
WHISPER_PARAMS = {
    "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    "condition_on_previous_text": True,
    "word_timestamps": True,
    "prepend_punctuations": "\"'([{-",
    "append_punctuations": "\"'.。,，!！?？:：)]}",
    "compression_ratio_threshold": 2.4,
    "logprob_threshold": -1.0,
    "no_speech_threshold": 0.6,
}

# 字幕排版参数
SUB_MAX_CHARS = 42      # 单条字幕大致最大字符数
SUB_MAX_DUR   = 7.0     # 单条字幕最长持续时间
SUB_MIN_DUR   = 1.0     # 单条字幕最短持续时间
SUB_MAX_GAP   = 1.2     # 词间停顿超过该值就断句
SUB_GAP       = 0.04    # 相邻字幕之间留出的最小间隔


# ============ 防挂机鼠标移动（可选） =============
def move_mouse_periodically():
    if not _HAS_PYAUTOGUI:
        logging.warning("未安装 pyautogui，跳过防挂机鼠标移动。")
        return
    while True:
        try:
            screen_width, screen_height = pyautogui.size()
            x = random.randint(100, screen_width - 100)
            y = random.randint(100, screen_height - 100)
            pyautogui.moveTo(x, y, duration=1)
            time.sleep(random.randint(30, 60))
        except Exception as e:
            logging.debug(f"鼠标移动出错: {e}")
            time.sleep(30)


# ============ 音频处理 =============
def enhance_audio(audio_path: str) -> str:
    temp_path = TEMP_DIR / f"enhanced_{os.path.basename(audio_path)}.wav"
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", audio_path,
        "-af", "afftdn=nf=-25,acompressor=threshold=-12dB:ratio=2:attack=200:release=1000,"
               "loudnorm=I=-16:LRA=11:TP=-1.5",
        str(temp_path)
    ]
    subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
    return str(temp_path)


def prepare_audio(audio_path: str) -> mx.array:
    src = audio_path
    if AUDIO_PARAMS["voice_enhance"]:
        try:
            src = enhance_audio(audio_path)
        except Exception as e:
            logging.warning(f"音频增强失败，使用原始音频: {e}")
            src = audio_path

    cmd = [
        FFMPEG_BIN, "-y", "-i", src,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(AUDIO_PARAMS["sample_rate"]),
        "-ac", "1",
    ]
    if AUDIO_PARAMS["normalize_volume"]:
        cmd.extend(["-filter:a", "volume=2.0"])
    cmd.append("-")

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw, _ = p.communicate()
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    if AUDIO_PARAMS["remove_noise"]:
        try:
            from scipy import signal
            b, a = signal.butter(4, 100 / (AUDIO_PARAMS["sample_rate"] / 2), 'high')
            arr = signal.filtfilt(b, a, arr).astype(np.float32)
        except ImportError:
            logging.warning("未安装 scipy，跳过高通降噪。")

    return mx.array(arr)


# ============ 文本与时间处理 =============
def post_process_text(text: str) -> str:
    text = re.sub(r'(\d+)\s+([a-zA-Z])', r'\1\2', text)
    text = re.sub(r'([。，！？!?])\1+', r'\1', text)
    text = re.sub(r'\.{2,}', '...', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def format_timestamp(sec: float, vtt: bool = False) -> str:
    sec = max(0.0, sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if vtt:
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


_FILLER_RE = re.compile(
    r"^\s*(um+|uh+|er+|ah+|hmm+|mm+|uhh+|erm+)\s*[,.\u3002\uff0c]?\s*$",
    re.IGNORECASE,
)


def words_to_cues(words: List[Dict[str, Any]],
                  remove_fillers: bool = True) -> List[Dict[str, Any]]:
    """
    直接基于带时间戳的词来分句成块：
    - 时间戳永远取自真实的词，绝不会因为索引错位而漂移；
    - 遇到句末标点、长停顿、超长或超字数时断句；
    - 永不丢弃有内容的块（这是修复"中间整段空白"的关键之一）。
    """
    # 过滤填充词与空词
    filtered = []
    for w in words:
        token = w.get("word", "")
        if not token.strip():
            continue
        if remove_fillers and _FILLER_RE.match(token):
            continue
        filtered.append(w)

    cues: List[Dict[str, Any]] = []
    group: List[Dict[str, Any]] = []
    char_count = 0

    def finalize(g: List[Dict[str, Any]]):
        text = post_process_text("".join(x["word"] for x in g))
        if text:
            cues.append({"start": g[0]["start"], "end": g[-1]["end"], "text": text})

    for w in filtered:
        token = w["word"]
        token_len = len(token.strip())
        if group:
            gap = w["start"] - group[-1]["end"]
            dur = group[-1]["end"] - group[0]["start"]
            last_tok = group[-1]["word"].strip()
            ends_sentence = bool(re.search(r"[.!?。！？]$", last_tok))
            if (char_count + token_len > SUB_MAX_CHARS
                    or dur >= SUB_MAX_DUR
                    or gap > SUB_MAX_GAP
                    or ends_sentence):
                finalize(group)
                group, char_count = [], 0
        group.append(w)
        char_count += token_len

    if group:
        finalize(group)

    return cues


def adjust_cue_timing(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """微调时间：保证 end>start、太短的延长、相邻不重叠。绝不丢块。"""
    cues.sort(key=lambda c: c["start"])
    n = len(cues)
    for i, c in enumerate(cues):
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + SUB_MIN_DUR

        # 太短则延长，但不越过下一条的起点
        if c["end"] - c["start"] < SUB_MIN_DUR:
            desired_end = c["start"] + SUB_MIN_DUR
            if i + 1 < n:
                desired_end = min(desired_end, cues[i + 1]["start"] - SUB_GAP)
            c["end"] = max(c["end"], desired_end)

        # 防止与下一条重叠
        if i + 1 < n and c["end"] > cues[i + 1]["start"] - SUB_GAP:
            new_end = cues[i + 1]["start"] - SUB_GAP
            # 即使空间很小也保留一点可见时间，宁可轻微重叠也不丢内容
            c["end"] = max(new_end, c["start"] + 0.2)

    return cues


def write_subtitles(words: List[Dict[str, Any]],
                    fmt: str,
                    out_path: str,
                    remove_fillers: bool = True) -> None:
    cues = words_to_cues(words, remove_fillers=remove_fillers)
    cues = adjust_cue_timing(cues)

    if not cues:
        logging.warning("没有可写入的字幕内容（可能是无语音或识别失败）。")

    with open(out_path, "w", encoding="utf-8") as f:
        if fmt == "vtt":
            f.write("WEBVTT\n\n")
        for idx, c in enumerate(cues, start=1):
            start_ts = format_timestamp(c["start"], vtt=(fmt == "vtt"))
            end_ts = format_timestamp(c["end"], vtt=(fmt == "vtt"))
            one_line = c["text"].replace("\n", " ").strip()
            if fmt == "srt":
                f.write(f"{idx}\n{start_ts} --> {end_ts}\n{one_line}\n\n")
            else:
                f.write(f"{start_ts} --> {end_ts}\n{one_line}\n\n")


# ============ 转录 =============
def transcribe_audio(audio: mx.array,
                     model_repo: str,
                     language: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    直接交给 mlx_whisper 处理整段音频（它内部会做 30s 滑窗并正确衔接时间戳），
    不再手动分块/重叠，从根本上避免拼接错乱与中段丢失。
    """
    logging.info("→ 开始转录（由 mlx-whisper 内部分窗处理整段音频）...")
    opts = dict(WHISPER_PARAMS)
    if language:
        opts["language"] = language

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model_repo,
        fp16=True,
        verbose=False,
        **opts,
    )

    words: List[Dict[str, Any]] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append(w)
    return words


def run_pipeline(video_path: str,
                 model_key: str = "large-v3",
                 language: Optional[str] = None) -> bool:
    try:
        logging.info(f"▶ 开始处理: {video_path}")
        repo = MODELS.get(model_key, model_key)

        audio = prepare_audio(video_path)
        dur = audio.shape[0] / AUDIO_PARAMS["sample_rate"]
        logging.info(f"  音频时长约 {dur/60:.1f} 分钟")

        words = transcribe_audio(audio, model_repo=repo, language=language)
        logging.info(f"  识别到 {len(words)} 个词")

        srt_path = str(pathlib.Path(video_path).with_suffix('.srt'))
        write_subtitles(words, "srt", srt_path, remove_fillers=True)
        logging.info(f"✔ SRT 已保存: {srt_path}")
        return True

    except Exception as e:
        logging.error(f"处理 {video_path} 时出错: {e}")
        return False
    finally:
        for f in TEMP_DIR.glob("enhanced_*"):
            try:
                f.unlink()
            except Exception:
                pass


# ============ 选择单个文件（修改这里） =============
def select_single_media_file() -> Optional[str]:
    root = tk.Tk()
    root.withdraw()
    if platform.system() == "Darwin":
        try:
            script = 'tell app "System Events" to set frontmost of process "Python" to true'
            subprocess.run(['osascript', '-e', script], check=True, capture_output=True)
        except Exception:
            pass

    # 文件类型过滤
    filetypes = [
        ("媒体文件", "*.mp4 *.mov *.mkv *.m4v *.webm *.avi *.flv *.mp3 *.wav *.m4a *.aac *.flac"),
        ("所有文件", "*.*")
    ]

    path = filedialog.askopenfilename(
        title="请选择一个视频/音频文件",
        initialdir=str(DEFAULT_VIDEO_DIR) if DEFAULT_VIDEO_DIR.exists() else None,
        filetypes=filetypes
    )
    root.destroy()
    return path if path else None


# ============ 主程序（修改这里，只处理单个文件） =============
if __name__ == "__main__":
    if not pathlib.Path(FFMPEG_BIN).exists() and shutil.which("ffmpeg") is None:
        logging.error(f"找不到 ffmpeg（尝试路径: {FFMPEG_BIN}），请先安装或修改 FFMPEG_BIN。")
        exit()

    threading.Thread(target=move_mouse_periodically, daemon=True).start()

    logging.info("请在弹出的窗口中选择要处理的单个媒体文件...")
    # 选择单个文件
    media_file_path = select_single_media_file()

    if not media_file_path:
        logging.info("未选择任何文件，程序退出。")
        exit()

    media_path = pathlib.Path(media_file_path)

    # 校验文件是否有效
    if not media_path.is_file():
        logging.error(f"错误：所选路径不是有效文件 -> {media_path}")
        exit()

    if media_path.suffix.lower() not in MEDIA_EXTS:
        logging.error(f"不支持的文件格式: {media_path.suffix}")
        exit()

    # 检查是否已有字幕
    srt_path = media_path.with_suffix('.srt')
    if srt_path.exists():
        logging.info(f"已存在字幕文件，跳过处理: {media_path.name}")
    else:
        logging.info(f"开始处理: {media_path.name}")
        success = run_pipeline(str(media_path), "large-v3", None)
        if success:
            logging.info("✅ 文件处理完成！")
        else:
            logging.info("❌ 文件处理失败！")

    logging.info("所有任务处理完毕。")
    print("程序执行完毕，退出。")