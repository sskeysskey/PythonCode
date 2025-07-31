import os
import shutil
import re
import sys
sys.path.append('/Users/yanzhang/Documents/python_code/Modules')
from Rename_textspeech import rename_first_segment_file

def find_and_move_mp4(source_dir, target_dir):
    # 查找source_dir目录下的第一个.mp4文件
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".mp4"):
                source_file_path = os.path.join(root, file)
                
                # 移动文件到target_dir
                shutil.move(source_file_path, target_dir)
                moved_file_path = os.path.join(target_dir, file)
                
                # 查找target_dir目录下所有以数字命名的mp4文件
                mp4_files = [f for f in os.listdir(target_dir) if re.match(r'^\d+\.mp4$', f)]
                
                if mp4_files:
                    # 获取现有文件名中数字的最大值
                    max_num = max(int(re.match(r'^(\d+)\.mp4$', f).group(1)) for f in mp4_files)
                    new_file_name = f"{max_num + 1}.mp4"
                else:
                    # 如果没有数字命名的文件，则新文件命名为1.mp4
                    new_file_name = "1.mp4"

                new_file_path = os.path.join(target_dir, new_file_name)
                
                # 重命名文件
                os.rename(moved_file_path, new_file_path)
                
                print(f"文件已移动并重命名为: {new_file_name}")
                return
    
    print("未找到任何.mp4文件")

# 指定源目录和目标目录
source_directory = "/Users/yanzhang/Downloads"
target_directory = "/Users/yanzhang/Movies/Subtitle"

# 调用函数
find_and_move_mp4(source_directory, target_directory)
directory = "/tmp/"
rename_first_segment_file(directory)