#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动模式：选一个（或多个）媒体文件生成 SRT。

用法：
    python whisper_mlx_manual.py                     # 弹窗选文件
    python whisper_mlx_manual.py a.mp4 b.mkv         # 直接指定
    python whisper_mlx_manual.py --multi --overwrite # 弹窗多选并覆盖旧字幕
"""

import argparse
import logging
import pathlib
import sys

import whisper_mlx_core as core


def main() -> int:
    ap = argparse.ArgumentParser(description="MLX-Whisper 单文件字幕生成")
    ap.add_argument("files", nargs="*", help="媒体文件路径（省略则弹窗选择）")
    ap.add_argument("--multi", action="store_true", help="弹窗时允许多选")
    ap.add_argument("--overwrite", action="store_true", help="已有字幕也重新生成")
    ap.add_argument("--model", default=core.DEFAULT_MODEL,
                    help=f"模型 key 或 HF repo，可选: {', '.join(core.MODELS)}")
    ap.add_argument("--lang", default=core.DEFAULT_LANGUAGE,
                    help="语言代码（如 zh / en），省略则自动检测")
    ap.add_argument("--fmt", default="srt", choices=["srt", "vtt"])
    ap.add_argument("--no-antiidle", action="store_true", help="不移动鼠标防挂机")
    ap.add_argument("--enhance", action="store_true",
                    help="启用激进音频增强（可能让时间戳漂移，仅原声很差时用）")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    core.setup_logging(logging.DEBUG if args.debug else logging.INFO)
    if not core.check_ffmpeg():
        return 1
    if args.enhance:
        core.AUDIO_PARAMS["aggressive_enhance"] = True
        logging.warning("已启用激进音频增强：词级时间戳可能变差。")
    if not args.no_antiidle:
        core.start_anti_idle()

    paths = args.files
    if not paths:
        logging.info("请在弹出的窗口中选择要处理的媒体文件...")
        paths = core.select_files(multiple=args.multi)
    if not paths:
        logging.info("未选择任何文件，程序退出。")
        return 0

    medias = []
    for p in paths:
        mp = pathlib.Path(p).expanduser()
        if not mp.is_file():
            logging.error(f"不是有效文件，忽略: {mp}")
            continue
        if mp.suffix.lower() not in core.MEDIA_EXTS:
            logging.error(f"不支持的格式，忽略: {mp.suffix}")
            continue
        medias.append(mp)
    if not medias:
        logging.error("没有可处理的文件。")
        return 1

    counter = {"done": 0, "skipped": 0, "failed": 0}
    try:
        for i, media in enumerate(medias, 1):
            logging.info(f"===== [{i}/{len(medias)}] {media.name} =====")
            counter[core.process_file(media, args.model, args.lang,
                                      args.fmt, args.overwrite)] += 1
    except KeyboardInterrupt:
        logging.warning("收到中断信号，提前结束。")

    if counter["done"]:
        logging.info(f"✅ 完成 {counter['done']} 个")
    if counter["skipped"]:
        logging.info(f"⏭ 跳过 {counter['skipped']} 个（已存在字幕，可用 --overwrite）")
    if counter["failed"]:
        logging.info(f"❌ 失败 {counter['failed']} 个")
    logging.info("所有任务处理完毕。")
    return 0 if counter["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())