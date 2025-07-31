import os
import glob
import codecs
import re
import sys
import pyperclip
sys.path.append('/Users/yanzhang/Coding/python_code/Modules')
from Rename_segment import rename_first_segment_file

def process_content_with_empty_lines(text):
    """
    处理含有多个空行的文本内容
    - 如果有超过5个空行，进行特殊处理
    - 合并没有空行分隔的句子
    - 保持有空行分隔的句子之间只有一个换行符
    """
    # 将文本分割成行
    lines = text.splitlines()
    
    # 计算空行数量
    empty_line_count = sum(1 for line in lines if not line.strip())
    
    # 如果空行少于5个，直接返回原始文本
    if empty_line_count <= 5:
        return text
    
    # 处理多空行情况
    result = []
    current_segment = []
    
    for line in lines:
        if line.strip():  # 非空行
            current_segment.append(line)
        else:  # 空行
            if current_segment:  # 如果当前段落有内容
                # 将当前段落合并为一行
                result.append(' '.join(current_segment))
                current_segment = []
            if result and not result[-1] == '':  # 确保只添加一个空行
                result.append('')
    
    # 处理最后一个段落
    if current_segment:
        result.append(' '.join(current_segment))
    
    return '\n'.join(result)

def count_non_empty_lines(content):
    return sum(1 for line in content.splitlines() if line.strip())

def extract_number(filename):
    basename = os.path.basename(filename)
    match = re.search(r'segment_(\d+)\.txt', basename)
    return int(match.group(1)) if match else None

def find_min_segment_file(directory):
    search_pattern = os.path.join(directory, 'segment_*.txt')
    files = glob.glob(search_pattern)
    valid_files = [f for f in files if extract_number(f) is not None]
    return min(valid_files, key=extract_number) if valid_files else None

def NewsTitle_File(clipboard_content, file_path):
    """处理剪贴板内容并写入文件."""
    # 再移除所有空行
    clipboard_content = remove_empty_lines(clipboard_content)
    
    # 如果文件为空，直接写入内容并添加换行符。如果文件不为空且最后一个字符不是换行符，添加一个换行符后再写入新内容，否则直接写入新内容。
    if clipboard_content:
        with codecs.open(file_path, 'a+', 'utf-8') as file:
            file.seek(0, os.SEEK_END)
            if file.tell() > 0:
                file.seek(file.tell() - 1, os.SEEK_SET)
                if file.read(1) != '\n':
                    file.write('\n')
            file.write(clipboard_content + '\n')
    else:
        print("剪贴板内容为空，未写入文件。")

def remove_empty_lines(text):
    """移除文本中的空行."""
    return '\n'.join(line for line in text.splitlines() if line.strip())

def main():
    directory = "/tmp/"
    file_path = '/Users/yanzhang/Coding/News/today_chn.txt'
    
    try:
        # 获取剪贴板内容并计算非空行数
        clipboard_content = pyperclip.paste()
        # 先处理多空行情况
        clipboard_content = process_content_with_empty_lines(clipboard_content)
        clipboard_lines = count_non_empty_lines(clipboard_content)
        
        if clipboard_lines == 0:
            print("剪贴板为空或内容无效。")
            return
        
        # 查找最小数字的 segment 文件
        min_file = find_min_segment_file(directory)
        
        if min_file:
            # 读取文件内容并计算非空行数
            with open(min_file, 'r', encoding='utf-8') as f:
                file_content = f.read()
            file_lines = count_non_empty_lines(file_content)
            
            # 比较行数
            if clipboard_lines != file_lines:
                # 如果不同，创建 diff.txt
                diff_file = os.path.join(directory, 'diff.txt')
                with open(diff_file, 'w', encoding='utf-8') as diff:
                    diff.write(f"剪贴板行数: {clipboard_lines}\n文件行数: {file_lines}\n")
                print(f"行数不同。已创建 {diff_file}")
            else:
                NewsTitle_File(clipboard_content, file_path)
                rename_first_segment_file(directory)
                print("行数相同。程序执行完毕。")
        else:
            print("未找到符合条件的 segment 文件。")
    
    except Exception as e:
        print(f"程序出错: {e}")

if __name__ == "__main__":
    main()