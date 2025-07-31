import os
import re
import sys
import shutil
import subprocess

# 设置基本路径
base_path = "/Users/yanzhang/Downloads/"
backup_folder = "/Users/yanzhang/Movies/Caption_Backup/"

def find_bob_file(base_path):
    bob_pattern = re.compile(r'bob', re.IGNORECASE)
    for file in os.listdir(base_path):
        if file.endswith('.txt') and bob_pattern.search(file):
            return file
    return None

def count_valid_lines(file_path, is_bob_file):
    with open(file_path, 'r', encoding='utf-8') as f:
        if is_bob_file:
            return sum(1 for line in f if line.strip())
        else:
            return sum(1 for line in f if line.strip() and re.search(r'[a-zA-Z]', line))

def display_dialog(message):
    applescript_code = f'display dialog "{message}" buttons {{"OK"}} default button "OK"'
    subprocess.run(['osascript', '-e', applescript_code], check=True)

# 删除以 "concatenated" 开头的 PNG 文件
for file in os.listdir(base_path):
    if file.startswith("concatenated") and file.endswith(".png"):
        os.remove(os.path.join(base_path, file))

# 查找以Bob开头的txt文件或bob.txt
bob_file = find_bob_file(base_path)

if not bob_file:
    print("未找到以Bob开头的txt文件或bob.txt，处理终止。")
    exit()

# 查找目录下的第一个srt文件
srt_file = next((f for f in os.listdir(base_path) if f.endswith(".srt")), None)

if not srt_file:
    print("未找到srt文件，处理终止。")
    exit()

# 计算有效行数
bob_lines = count_valid_lines(os.path.join(base_path, bob_file), True)
srt_lines = count_valid_lines(os.path.join(base_path, srt_file), False)

if bob_lines != srt_lines:
    display_dialog(f"文件行数不匹配x：Bob文件有 {bob_lines} 行，SRT文件有 {srt_lines} 行有效内容。")
    sys.exit(1) # 以错误码 1 退出

# 读取文件内容
with open(os.path.join(base_path, bob_file), 'r', encoding='utf-8') as f:
    file1_lines = f.readlines()
with open(os.path.join(base_path, srt_file), 'r', encoding='utf-8') as f:
    file2_lines = f.readlines()

# 初始化结果列表和索引
result_lines = []
file1_line_index = 0

# 合并文件内容
for line in file2_lines:
    if line.strip() and re.search(r'[a-zA-Z]+', line):
        if file1_line_index < len(file1_lines):
            while file1_line_index < len(file1_lines) and not file1_lines[file1_line_index].strip():
                file1_line_index += 1
            if file1_line_index < len(file1_lines):
                result_lines.append(file1_lines[file1_line_index].rstrip() + '\n')
                file1_line_index += 1
            else:
                result_lines.append(line)
        else:
            result_lines.append(line)
    else:
        result_lines.append(line)

# 确保最后一行也有换行符
if result_lines and not result_lines[-1].endswith('\n'):
    result_lines[-1] += '\n'

# 创建临时文件
temp_file = os.path.join(base_path, "temp.srt")
with open(temp_file, 'w', encoding='utf-8') as f:
    f.writelines(result_lines)

# 备份原始文件到备份文件夹
shutil.copy2(os.path.join(base_path, srt_file), os.path.join(backup_folder, srt_file))
shutil.copy2(os.path.join(base_path, bob_file), os.path.join(backup_folder, bob_file))

# 用新内容替换原始srt文件
os.replace(temp_file, os.path.join(base_path, srt_file))

# 删除原始bob文件
os.remove(os.path.join(base_path, bob_file))

print(f"处理完成。使用的文件: {bob_file} 和 {srt_file}")