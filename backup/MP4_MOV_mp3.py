import os
import subprocess

def find_first_video_file(directory):
    # 遍历目录，找到第一个扩展名是mp4或mov的文件
    for filename in os.listdir(directory):
        if filename.lower().endswith(('.mp4', '.mov')):
            return filename
    return None

def extract_audio(input_video_path, output_audio_path):
    # 构建FFmpeg命令
    command = [
        'ffmpeg', '-i', input_video_path,  # 输入文件
        '-q:a', '0',  # 保持最高音频质量
        '-map', 'a',  # 只映射音频流
        output_audio_path  # 输出文件
    ]

    # 运行FFmpeg命令
    try:
        subprocess.run(command, check=True)
        print(f"音频成功提取到 {output_audio_path}")
    except subprocess.CalledProcessError as e:
        print(f"提取音频失败: {e}")

if __name__ == "__main__":
    directory = "/Users/yanzhang/Movies/Subtitle/"  # 指定目录路径
    first_video_file = find_first_video_file(directory)

    if first_video_file:
        input_video = os.path.join(directory, first_video_file)
        output_audio = os.path.join(directory, "output.mp3")
        extract_audio(input_video, output_audio)

        # 获取文件名（不包括扩展名）
        base_name = os.path.splitext(first_video_file)[0]
        final_audio_path = os.path.join(directory, base_name + '.mp3')

        # 重命名MP3文件
        os.rename(output_audio, final_audio_path)
        print(f"MP3文件已重命名为 {final_audio_path}")
    else:
        print("在指定目录中未找到扩展名为mp4或mov的文件")