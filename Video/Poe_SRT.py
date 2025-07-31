import re
import os
import sys
import pyperclip

# ————————————
# 可修改的默认输出路径
DEFAULT_OUTPUT_PATH = '/Users/yanzhang/Downloads/Videos/subtitle.srt'

# 解析命令行参数：如果提供了第一个参数，就当作新的输出路径
if len(sys.argv) > 1:
    output_path = sys.argv[1]
else:
    output_path = DEFAULT_OUTPUT_PATH


def fix_timestamp(line):
    """修复时间戳中的负数问题"""
    pattern = r'(\d{2}:\d{2}:\d{2}),(-\d+)\s-->'
    
    def replace_negative(match):
        time_part = match.group(1)
        negative_num = match.group(2)
        # 将负数转换为3位数的正数形式
        fixed_num = f"{abs(int(negative_num)):03d}"
        return f"{time_part},{fixed_num} -->"
    
    return re.sub(pattern, replace_negative, line)


def SRT_File(clipboard_content):
    print("执行 SRT_File()")
    
    # 使用正则表达式找到第一个以数字开头并且紧跟一个换行符的行
    match = re.search(r'^(\d+).*\n', clipboard_content, re.MULTILINE)
    if not match:
        print('剪贴板内容中没有找到符合条件的行。')
        return

    # 从匹配行的起点开始截取
    start_index = match.start()
    remaining_content = clipboard_content[start_index:]

    # 按行分割并修复时间戳
    fixed_lines = []
    for line in remaining_content.splitlines():
        if '-->' in line:
            line = fix_timestamp(line)
        fixed_lines.append(line)
    fixed_content = '\n'.join(fixed_lines)

    # 确定写入模式：不存在就写新文件，存在就追加
    mode = 'a' if os.path.exists(output_path) else 'w'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 写入
    with open(output_path, mode, encoding='utf-8') as f:
        f.write(fixed_content)
        f.write('\n\n')  # 两个换行分隔块

    print(f'内容已写入到 {output_path}（模式：{mode}）。')


def main():
    try:
        # 获取剪贴板内容
        clipboard_content = pyperclip.paste()
    except pyperclip.PyperclipException:
        print("无法访问剪贴板，请检查 pyperclip 是否支持当前系统。")
        sys.exit(1)

    try:
        SRT_File(clipboard_content)
    except Exception as e:
        print(f"发生错误: {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()