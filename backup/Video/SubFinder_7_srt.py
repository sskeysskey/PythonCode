import cv2
import numpy as np
import pytesseract
from pytesseract import Output
import os
from imagehash import phash
from difflib import SequenceMatcher
import hashlib
from PIL import Image

def preprocess_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return thresh

def image_hash(image):
    pil_image = Image.fromarray(image)
    return str(phash(pil_image))

def are_similar_texts(text1, text2):
    return SequenceMatcher(None, text1, text2).ratio() > 0.85

def extract_subtitle_frames(video_path, output_folder, roi):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)

    prev_hash = ""
    prev_text = ""
    start_time = None
    last_change_time = None
    subtitle_roi = None
    recent_hashes = {}
    MIN_TEXT_LENGTH = 5
    MIN_TIME_BETWEEN_SUBTITLES = 0.3

    last_subtitle_time = -MIN_TIME_BETWEEN_SUBTITLES
    subtitles = []
    subtitle_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        current_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        x, y, w, h = roi
        cropped_frame = frame[y:y+h, x:x+w]

        processed_frame = preprocess_image(cropped_frame)

        d = pytesseract.image_to_data(processed_frame, output_type=Output.DICT)
        text = " ".join([d['text'][i] for i in range(len(d['text'])) if int(d['conf'][i]) > 50]).strip()

        if len(text) >= MIN_TEXT_LENGTH:
            current_hash = image_hash(processed_frame)

            if not are_similar_texts(text, prev_text) and current_hash not in recent_hashes:
                if prev_hash and current_time - last_subtitle_time >= MIN_TIME_BETWEEN_SUBTITLES:
                    if start_time is not None:
                        save_subtitle(output_folder, start_time, last_change_time, subtitle_roi)
                        subtitle_count += 1
                        subtitles.append({
                            'number': subtitle_count,
                            'start': format_time(start_time),
                            'end': format_time(last_change_time)
                        })
                        print(f"Saved subtitle: {format_time(start_time)} - {format_time(last_change_time)}")
                    start_time = current_time
                    recent_hashes = {}

                last_change_time = current_time
                subtitle_roi = cropped_frame.copy()
                prev_hash = current_hash
                prev_text = text
                last_subtitle_time = current_time
                recent_hashes[current_hash] = current_time
            else:
                last_change_time = current_time
                recent_hashes[current_hash] = current_time

    if prev_hash and start_time is not None:
        save_subtitle(output_folder, start_time, last_change_time, subtitle_roi)
        subtitle_count += 1
        subtitles.append({
            'number': subtitle_count,
            'start': format_time(start_time),
            'end': format_time(last_change_time)
        })
        print(f"Saved subtitle: {format_time(start_time)} - {format_time(last_change_time)}")

    cap.release()
    cv2.destroyAllWindows()

    write_srt_file(output_folder, subtitles)

def save_subtitle(output_folder, start_time, end_time, roi_image):
    start_time_str = format_time(start_time)
    end_time_str = format_time(end_time)
    output_filename = os.path.join(output_folder, f"{start_time_str}_{end_time_str}.png")
    cv2.imwrite(output_filename, roi_image)

def write_srt_file(output_folder, subtitles):
    srt_filename = os.path.join(output_folder, "sub.srt")
    with open(srt_filename, 'w', encoding='utf-8') as f:
        for subtitle in subtitles:
            f.write(f"{subtitle['number']}\n")
            f.write(f"{subtitle['start']} --> {subtitle['end']}\n")
            f.write("waiting for joint\n\n")

def format_time(time):
    hours = int(time // 3600)
    minutes = int((time % 3600) // 60)
    seconds = int(time % 60)
    milliseconds = int((time % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

video_path = '/Users/yanzhang/Downloads/RPReplay_Final1726992388.mov'
output_folder = '/Users/yanzhang/Movies/Subtitle'
roi = (13, 996, 873, 135)  # 替换为实际的ROI坐标和尺寸
extract_subtitle_frames(video_path, output_folder, roi)