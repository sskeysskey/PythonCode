#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量模式：选一个文件夹，把里面所有媒体文件转成 SRT。

用法：
    python whisper_mlx_auto.py                 # 弹窗选目录
    python whisper_mlx_auto.py /path/to/dir    # 直接指定目录
    python whisper_mlx_auto.py /path -r --overwrite --model large-v3 --lang zh
"""

import argparse
import logging
import pathlib
import sys

import whisper_mlx_core as core


def main() -> int:
    ap = argparse.ArgumentParser(description="MLX-Whisper 批量字幕生成")
    ap.add_argument("directory", nargs="?", help="媒体文件所在目录（省略则弹窗选择）")
    ap.add_argument("-r", "--recursive", action="store_true", help="递归子目录")
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

    target = args.directory
    if not target:
        logging.info("请在弹出的窗口中选择要处理的视频文件夹...")
        target = core.select_directory()
    if not target:
        logging.info("未选择任何目录，程序退出。")
        return 0

    directory = pathlib.Path(target).expanduser()
    if not directory.is_dir():
        logging.error(f"所选路径不是有效目录 -> {directory}")
        return 1

    logging.info(f"扫描目录: {directory}")
    files = core.find_media_files(directory, recursive=args.recursive)
    if not files:
        logging.warning("没有找到任何受支持的媒体文件。")
        return 0

    logging.info(f"发现 {len(files)} 个媒体文件，开始处理...")
    counter = {"done": 0, "skipped": 0, "failed": 0}
    try:
        for i, media in enumerate(files, 1):
            logging.info(f"===== [{i}/{len(files)}] {media.name} =====")
            status = core.process_file(media, args.model, args.lang,
                                       args.fmt, args.overwrite)
            counter[status] += 1
    except KeyboardInterrupt:
        logging.warning("收到中断信号，提前结束。")

    logging.info(f"统计：成功 {counter['done']}，跳过 {counter['skipped']}，"
                 f"失败 {counter['failed']}。")
    logging.info("所有任务处理完毕。")
    return 0 if counter["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())