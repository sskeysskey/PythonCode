import os
import re
import subprocess
import sys
import tempfile
import shutil  # 添加这行来导入 shutil 模块

def merge_videos(video_files, output_file):
    # 在临时目录中创建一个文件列表
    with tempfile.NamedTemporaryFile(delete=False, mode='w', dir=tempfile.gettempdir(), suffix='.txt') as file_list:
        for video_file in video_files:
            file_list.write(f"file '{video_file}'\n")
        temp_file_list_path = file_list.name
    
    try:
        # 使用 FFmpeg 合并视频文件
        ffmpeg_path = "/opt/homebrew/bin/ffmpeg"  # 请将此路径替换为你系统中的实际路径
        command = [ffmpeg_path, "-f", "concat", "-safe", "0", "-i", temp_file_list_path, "-c", "copy", output_file]
        subprocess.run(command, check=True)
    finally:
        # 删除临时文件列表
        os.remove(temp_file_list_path)

def extract_audio(input_video, output_audio):
    try:
        # 构建FFmpeg命令
        ffmpeg_path = "/opt/homebrew/bin/ffmpeg"  # 请将此路径替换为你系统中的实际路径
        command = [
            ffmpeg_path,
            '-i', input_video,          # 输入视频文件
            '-q:a', '0',                # 设置音频质量为最高
            '-map', 'a',                # 仅选择音频流
            output_audio                # 输出音频文件
        ]
        
        # 执行FFmpeg命令
        subprocess.run(command, check=True)
        print(f"音频提取成功，保存为 {output_audio}")
    except subprocess.CalledProcessError as e:
        print(f"音频提取失败: {e}")

def get_video_files(directory):
    def sort_key(filename):
        # 提取文件名中的数字部分
        match = re.search(r'\d+', os.path.splitext(os.path.basename(filename))[0])
        if match:
            return int(match.group())
        return float('inf')  # 将非数字命名的文件排到最后

    # 获取指定目录下所有的MP4文件并按数字顺序排序
    video_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.mp4') and f != 'output.mp4']
    return sorted(video_files, key=sort_key)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("请提供一个目录路径作为参数，例如：python merge_videos.py /path/to/directory")
        sys.exit(1)
    
    directory = sys.argv[1]
    
    if not os.path.isdir(directory):
        print(f"目录 {directory} 不存在或不是一个有效的目录。")
        sys.exit(1)
    
    video_files = get_video_files(directory)
    
    if not video_files:
        print(f"在目录 {directory} 下没有找到任何MP4文件。")
    else:
        output_file = os.path.join(directory, "output.mp4")
        merge_videos(video_files, output_file)
        print(f"视频已成功合并为 {output_file}")
        
        # 提取音频并保存为 MP3
        output_mp3 = os.path.join(directory, "output.mp3")
        extract_audio(output_file, output_mp3)
        
        # 重命名 MP3 文件并删除临时文件
        tmp_dir = "/tmp/"
        book_dir = "/Users/yanzhang/Documents/Books/"
        mp3name_file_path = os.path.join(tmp_dir, 'mp3name.txt')
        output_mp3 = os.path.join(directory, "output.mp3")
        
        if os.path.exists(mp3name_file_path) and os.path.isfile(mp3name_file_path):
            with open(mp3name_file_path, 'r') as mp3name_file:
                book_name = mp3name_file.read().strip()
                final_mp3_name = book_name + ".mp3"  # 确保文件名以 .mp3 结尾
        
            final_mp3_path = os.path.join(directory, final_mp3_name)
            book_path = os.path.join(book_dir, book_name + ".txt")
            
            try:
                os.rename(output_mp3, final_mp3_path)
                print(f"MP3 文件已重命名为 {final_mp3_path}")
            except OSError as e:
                print(f"重命名失败: {e}")
            
            try:
                os.remove(mp3name_file_path)
                print(f"临时文件 {mp3name_file_path} 已删除")
            except OSError as e:
                print(f"删除临时文件失败: {e}")
            
            # 移动 book_path 文件到 mp3 目录
            read_dir = "/Users/yanzhang/Documents/Books/mp3/"
            if os.path.exists(book_path):
                try:
                    shutil.move(book_path, read_dir)
                    print(f"文件 {book_path} 已成功移动到 {read_dir}")
                except shutil.Error as e:
                    print(f"移动文件失败: {e}")
            else:
                print(f"文件 {book_path} 不存在")
        else:
            print(f"临时文件 {mp3name_file_path} 不存在或不是一个有效的文件")