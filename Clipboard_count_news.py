import re
import pyperclip

def process_clipboard_content():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()
    
    # 修改匹配模式,使用更精确的模式来匹配Close及其之前的内容
    pattern = r'(?s).*?Close\s*\n'  # (?s)让.也匹配换行符
    match = re.search(pattern, clipboard_content, re.MULTILINE)
    
    if match:
        processed_content = clipboard_content[match.end():].strip()
    else:
        processed_content = clipboard_content
    
    # 删除URL
    url_pattern = r'https?://[^\s<>"]+?(?:\.[^\s<>"]+)+(?:/[^\s<>"]*)?'
    processed_content = re.sub(url_pattern, '', processed_content)
    
    # 删除Copyright及其后的所有内容
    copyright_pattern = r'Copyright ©.*$.*'
    processed_content = re.sub(copyright_pattern, '', processed_content, flags=re.MULTILINE | re.DOTALL)
    
    # 清理结果(移除多余空行并确保末尾只有一个换行)
    processed_content = re.sub(r'\n\s*\n', '\n\n', processed_content).strip() + '\n'
    
    # 将处理后的内容写回剪贴板
    pyperclip.copy(processed_content)
    
    return processed_content

def save_content_to_file(content, filepath):
    """将内容保存到指定文件"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"文件已创建：{filepath}")
    except IOError as e:
        print(f"创建文件时出错：{e}")

def count_words_and_create_file():
    # 处理剪贴板内容
    processed_content = process_clipboard_content()
    
    # 计算英文单词数量
    num_english_words = len(re.findall(r'\b[A-Za-z]+\b', processed_content))
    
    if num_english_words > 500:
        print(f"单词数量为 {num_english_words}，属于长文章，正在创建 longarticle.txt...")
        save_content_to_file(processed_content, '/tmp/longarticle.txt')
    elif num_english_words >= 1:  # 此条件覆盖了 1 到 500 的范围
        print(f"单词数量为 {num_english_words}，属于短文章，正在创建 shortarticle.txt...")
        save_content_to_file(processed_content, '/tmp/shortarticle.txt')
    else:  # 此条件处理单词数小于 1 (即为 0) 的情况
        print(f"单词数量为 {num_english_words}，不创建文件。")

if __name__ == '__main__':
    count_words_and_create_file()