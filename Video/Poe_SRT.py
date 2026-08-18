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


def filter_last_sentence(content):
    """
    过滤逻辑：如果最后一个有内容的句子以“需要我”开头，则将其删除。
    """
    # 按行分割，去除空行
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    if not lines:
        return content

    # 获取最后一行
    last_line = lines[-1]
    
    # 检查是否以“需要我”开头
    if last_line.startswith("需要我"):
        print(f"检测到最后一句以“需要我”开头，正在删除: {last_line}")
        # 重新构建内容：去掉最后一行
        # 注意：这里假设内容是以行为单位的，如果你的SRT格式比较复杂，
        # 可能需要更精细的逻辑，但对于大多数情况，去掉最后一行是有效的。
        # 我们使用 rstrip() 配合正则去掉最后一行，保留前面的内容
        pattern = re.compile(re.escape(last_line) + r'\s*$', re.MULTILINE)
        return pattern.sub('', content).strip()
    
    return content


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

def normalize_srt_blocks(content):
    """
    将紧凑型 SRT（块之间无空行）规范化为标准 SRT（块之间用一个空行分隔）。
    识别规则：某行是纯数字序号，且紧接的下一行包含 '-->'，则视为一个新块的开始。
    """
    # 先去掉所有空行，统一处理
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if not lines:
        return content

    blocks = []
    current_block = []
    n = len(lines)

    for i, line in enumerate(lines):
        is_index = re.match(r'^\d+$', line.strip())
        next_is_timestamp = (i + 1 < n) and ('-->' in lines[i + 1])

        # 遇到新块起点：把上一个块存起来
        if is_index and next_is_timestamp and current_block:
            blocks.append('\n'.join(current_block))
            current_block = []

        current_block.append(line)

    if current_block:
        blocks.append('\n'.join(current_block))

    # 块之间用一个空行分隔
    return '\n\n'.join(blocks)


def SRT_File(clipboard_content):
    print("执行 SRT_File()")

    # 先进行内容过滤
    clipboard_content = filter_last_sentence(clipboard_content)

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

    # 【新增】规范化字幕块，块之间插入空行
    fixed_content = normalize_srt_blocks(fixed_content)

    # 确定写入模式
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