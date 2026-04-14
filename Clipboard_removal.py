import pyperclip
import re

def is_short_line_to_remove(line):
    """
    判断一行是否应该被删除：
    1. 以“以下是”开头
    2. 且该行中文字符数少于 10 个
    """
    # 检查是否以“以下是”开头
    if line.strip().startswith("以下是"):
        # 统计中文字符数 (使用正则表达式匹配中文字符)
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', line)
        if len(chinese_chars) < 10:
            return True
    return False

def clean_clipboard():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()
    
    # 1. 先处理现有的正则表达式过滤（移除“更多阅读”等开头行）
    pattern = r'^(?:更多阅读|延伸阅读|相关阅读|拓展阅读).*(?:\r?\n|$)'
    cleaned_content = re.sub(pattern, '', clipboard_content, flags=re.MULTILINE)
    
    # 2. 处理新增的过滤逻辑（按行过滤）
    lines = cleaned_content.splitlines()
    final_lines = []
    
    for line in lines:
        # 如果该行不满足“删除条件”，则保留
        if not is_short_line_to_remove(line):
            final_lines.append(line)
            
    # 将处理后的行重新合并
    final_content = "\n".join(final_lines)
    
    # 将处理后的内容写回剪贴板
    pyperclip.copy(final_content)
    
    return final_content

# 运行程序
if __name__ == "__main__":
    try:
        cleaned_text = clean_clipboard()
        print("剪贴板内容已清理完成！")
        print("已移除“更多阅读”等相关行，以及“以下是...”且中文少于10字的行。")
    except Exception as e:
        print(f"发生错误: {str(e)}")