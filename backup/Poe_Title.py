import os
import glob
import codecs
import re
import sys
import pyperclip
import tempfile  # <--- 新增：用于获取跨平台临时目录

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础 Coding 目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 定义模块路径并添加到 sys.path
MODULES_DIR = os.path.join(BASE_CODING_DIR, "python_code", "Modules")
if MODULES_DIR not in sys.path:
    sys.path.append(MODULES_DIR)

# 4. 定义新闻文件路径
NEWS_FILE_PATH = os.path.join(BASE_CODING_DIR, "News", "today_chn.txt")

# 5. 定义临时目录 (Mac下兼容 /tmp, Windows下自动适配)
# 注意：如果你的上游程序(生成segment文件的程序)在Mac上写死了 /tmp/，
# 这里在Mac上最好也保持 /tmp/。
if os.name == 'nt':
    TEMP_DIR = tempfile.gettempdir()
else:
    TEMP_DIR = "/tmp"

# ========================================================

# 尝试导入模块，如果失败则打印警告 (防止在没部署 Modules 的新电脑上直接报错)
try:
    from Rename_segment import rename_first_segment_file
except ImportError:
    print(f"警告: 无法从 {MODULES_DIR} 导入 Rename_segment。")
    print("请确保该文件存在，或者手动修改路径。")
    # 定义一个空函数防止程序崩溃
    def rename_first_segment_file(directory):
        print("模拟执行: rename_first_segment_file")

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
    # 使用 os.path.join 确保路径拼接跨平台正确
    search_pattern = os.path.join(directory, 'segment_*.txt')
    files = glob.glob(search_pattern)
    valid_files = [f for f in files if extract_number(f) is not None]
    return min(valid_files, key=extract_number) if valid_files else None

def NewsTitle_File(clipboard_content, file_path):
    """处理剪贴板内容并写入文件."""
    # 再移除所有空行
    clipboard_content = remove_empty_lines(clipboard_content)
    
    # 确保目标目录存在
    target_dir = os.path.dirname(file_path)
    if not os.path.exists(target_dir):
        try:
            os.makedirs(target_dir)
        except OSError:
            pass

    # 如果文件为空，直接写入内容并添加换行符。如果文件不为空且最后一个字符不是换行符，添加一个换行符后再写入新内容，否则直接写入新内容。
    if clipboard_content:
        with codecs.open(file_path, 'a+', 'utf-8') as file:
            file.seek(0, os.SEEK_END)
            if file.tell() > 0:
                file.seek(file.tell() - 1, os.SEEK_SET)
                # 读取时注意编码，虽然这里只读1个字节判断换行
                if file.read(1) != '\n':
                    file.write('\n')
            file.write(clipboard_content + '\n')
    else:
        print("剪贴板内容为空，未写入文件。")

def remove_empty_lines(text):
    """移除文本中的空行."""
    return '\n'.join(line for line in text.splitlines() if line.strip())

# --- [新增功能] 过滤非数字开头的行 ---
def filter_lines_starting_with_digit(text):
    """
    只保留以数字开头的行。
    例如：
    "1. Hello" -> 保留
    "2023年..." -> 保留
    "这是标题" -> 删除
    """
    filtered_lines = []
    for line in text.splitlines():
        # strip() 去除首尾空格，re.match(r'^\d') 匹配开头是否为数字
        if line.strip() and re.match(r'^\d', line.strip()):
            filtered_lines.append(line)
    return '\n'.join(filtered_lines)

def main():
    # 使用之前定义的跨平台变量
    directory = TEMP_DIR
    file_path = NEWS_FILE_PATH
    
    try:
        # 获取剪贴板内容并计算非空行数
        clipboard_content = pyperclip.paste()
        # --- 新增防御逻辑开始 ---
        # 如果剪贴板里包含发送给 AI 的标签 <document> 或者 prompt 里的关键词
        # 说明没有成功复制到翻译结果，直接报错，触发重试
        if "<document>" in clipboard_content or "只输出翻译内容" in clipboard_content:
            print("错误：检测到剪贴板内容仍为输入提示词，未获取到有效翻译！")
            sys.exit(1) # 强制报错
        # --- 新增防御逻辑结束 ---

        # 1. 先处理多空行/格式整理 (保留你原有的逻辑)
        clipboard_content = process_content_with_empty_lines(clipboard_content)

        # 2. >>> [关键修改点] 执行过滤：只保留以数字开头的行 <<<
        # 这一步会把非数字开头的“杂质”行清除
        clipboard_content = filter_lines_starting_with_digit(clipboard_content)
        
        # 3. 计算非空行数 (此时内容已经是过滤干净的了)
        clipboard_lines = count_non_empty_lines(clipboard_content)
        
        print(f"处理后剪贴板行数: {clipboard_lines}") # 方便调试查看
        if clipboard_lines == 0:
            print("剪贴板为空或内容无效（没有以数字开头的行）。")
            return
        
        # 查找最小数字的 segment 文件
        min_file = find_min_segment_file(directory)
        
        if min_file:
            # 读取文件内容并计算非空行数
            with open(min_file, 'r', encoding='utf-8') as f:
                file_content = f.read()
            file_lines = count_non_empty_lines(file_content)
            
            # 4. 比较行数
            if clipboard_lines != file_lines:
                # 如果不同，创建 diff.txt
                diff_file = os.path.join(directory, 'diff.txt')
                with open(diff_file, 'w', encoding='utf-8') as diff:
                    diff.write(f"剪贴板行数: {clipboard_lines}\n文件行数: {file_lines}\n")
                print(f"行数不同 (剪贴板:{clipboard_lines} vs 文件:{file_lines})。已创建 {diff_file}")
            else:
                # 写入的是经过过滤的内容
                NewsTitle_File(clipboard_content, file_path)
                rename_first_segment_file(directory)
                print("行数相同。程序执行完毕。")
        else:
            print(f"在 {directory} 未找到符合条件的 segment 文件。")
    
    except Exception as e:
        print(f"程序出错: {e}")
        # 在调试阶段，或者在命令行运行时，可能希望看到完整的错误堆栈
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
