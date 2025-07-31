import codecs
import pyperclip
import re
import os
import sys

def count_non_empty_lines(text):
    """计算非空行数"""
    return len([line for line in text.split('\n') if line.strip()])

def process_clipboard_content(clipboard_content):
    """处理剪贴板内容，取消两行之间只有一个换行符的情况，并在合并的句子之间增加一个空格。"""
    # 统计空行数量
    empty_lines = len(re.findall(r'\n\s*\n', clipboard_content))
    
    # 如果有不止一个空行，进行单行换行符的合并并在合并的句子之间增加一个空格
    if empty_lines > 0:
        processed_content = re.sub(r'(?<!\n)\n(?!\n)', ' ', clipboard_content)
    else:
        processed_content = clipboard_content
    
    return processed_content

def SRT_File(clipboard_content):
    """处理剪贴板内容并写入文件。"""
    print("已写入bob.txt")
    # 定义文件路径
    file_path = '/Users/yanzhang/Downloads/bob.txt'

    # 检查文件是否存在，不存在则创建
    with codecs.open(file_path, 'a', 'utf-8') as file:
        file.write(clipboard_content + '\n')  # 追加剪贴板内容并在最后加入换行符

def main(passed_index):
    directory = "/tmp/"
    file_index_path = os.path.join(directory, 'FileIndex.txt')

    try:
        # 读取 /tmp/FileIndex.txt 文件内容
        with open(file_index_path, 'r') as f:
            file_index = int(f.read().strip())

        # 获取剪贴板内容
        clipboard_content = pyperclip.paste()
        processed_content = process_clipboard_content(clipboard_content)
        
        # 比较传入的参数和文件中的索引
        if int(passed_index) == file_index:
            # 如果一致，执行 SRT_File 并删除 FileIndex.txt
            SRT_File(processed_content)
            try:
                os.remove(file_index_path)
                print(f"已删除 {file_index_path}")
            except OSError as e:
                print(f"删除 {file_index_path} 时出错: {e}")
        else:
            # 如果不一致，按照原流程执行
            non_empty_lines = count_non_empty_lines(processed_content)
            if non_empty_lines == 15:
                SRT_File(processed_content)
            else:
                diff_file = os.path.join(directory, 'diff.txt')
                with open(diff_file, 'w', encoding='utf-8') as diff:
                    diff.write(f"剪贴板行数: {non_empty_lines}\n")
                print(f"行数不为15。已创建 {diff_file}")
        
    except pyperclip.PyperclipException as e:
        print("无法访问剪贴板，请检查pyperclip是否支持当前系统。")
    except FileNotFoundError:
        print(f"文件 {file_index_path} 不存在")
    except ValueError:
        print(f"文件 {file_index_path} 内容无法转换为整数")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        print("请提供文件索引作为参数")