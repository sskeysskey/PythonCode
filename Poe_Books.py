import re
import os
import pyperclip
import sys
sys.path.append('/Users/yanzhang/Documents/python_code/Modules')
from Rename_segment import rename_first_segment_file

def get_clipboard_content():
    content = pyperclip.paste()
    if not content:
        return ""
    
    # 分割成行并去除空白行
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    # 如果行数小于3，直接返回原内容
    if len(lines) < 3:
        return "\n".join(lines)
    
    # 移除第一行和最后一行
    filtered_lines = lines[:-1]
    
    # 重新组合文本
    return "\n".join(filtered_lines)

def main():
    # 设置目录路径
    directory_path = '/Users/yanzhang/Documents/'

    # 寻找目录下的第一个txt文件
    for filename in os.listdir(directory_path):
        if filename.endswith('.txt'):
            txt_file_path = os.path.join(directory_path, filename)
            break  # 找到第一个txt文件后停止循环

    # 读取剪贴板内容
    clipboard_content = get_clipboard_content()

    # 检查clipboard_content是否为None或者是否是一个字符串
    if clipboard_content:
        # 计算剪贴板内容中的中文字符数目
        chinese_characters_count = len(re.findall(r'[\u4e00-\u9fff]', clipboard_content))

        if chinese_characters_count < 200:
            print("剪贴板内容不符合要求，程序终止执行。")
            # 内容非法后的过渡传递参数
            pyperclip.copy("illegal")
            exit()

        # 使用splitlines()分割剪贴板内容为多行
        lines = clipboard_content.splitlines()
        # 移除空行
        non_empty_lines = [line for line in lines if line.strip()]
    else:
        print("剪贴板中没有内容或pyperclip无法访问剪贴板。")
        non_empty_lines = []  # 确保non_empty_lines是一个列表，即使剪贴板为空

    # 将非空行合并为一个字符串，用换行符分隔
    modified_content = '\n'.join(non_empty_lines)

    # 读取/tmp/segment.txt文件内容
    segment_file_path = '/tmp/segment.txt'
    with open(segment_file_path, 'r', encoding='utf-8-sig') as segment_file:
        segment_content = segment_file.read().strip()  # 使用strip()移除可能的空白字符

    # 在segment_content后面添加一个换行符
    segment_content += '\n'
    
    # 将读取到的segment_content内容插入在剪贴板内容的最前面
    final_content = segment_content + modified_content

    # 追加处理后的内容到TXT文件
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content)
        txt_file.write('\n\n')  # 添加两个换行符以创建一个空行

    # 使用函数
    directory = "/Users/yanzhang/Downloads/backup/TXT/Segments/"
    rename_first_segment_file(directory)

    # 删除/tmp/segment.txt文件
    os.remove(segment_file_path)

if __name__ == '__main__':
    main()