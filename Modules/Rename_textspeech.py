import re
import os
import glob

def rename_first_segment_file(directory):
    # 构造搜索路径
    search_pattern = os.path.join(directory, 'textspeech_*.txt')
    
    # 使用glob找到所有符合条件的文件
    files = glob.glob(search_pattern)
    
    # 定义一个函数用于从文件名中提取数字，并确保正确处理文件名数字
    def extract_number(filename):
        # 从完整路径中提取文件名部分
        basename = os.path.basename(filename)
        # 使用正则表达式匹配数字
        match = re.search(r'textspeech_(\d+)\.txt', basename)
        return int(match.group(1)) if match else float('inf')
    
    # 检查是否找到了文件
    if files:
        # 按文件名中数字排序
        files.sort(key=extract_number)
        # 获取数值最小的文件（列表中的第一个文件）
        min_file = files[0]
        # 构造新文件名
        new_name = re.sub(r'textspeech_(\d+)\.txt', r'done_\1.txt', min_file)
        # 改名操作
        os.rename(min_file, new_name)
        print(f"已将文件 {min_file} 改名为 {new_name}")
    else:
        print("没有找到以 'segment_' 开头的txt文件")