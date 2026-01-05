import os
import pyperclip
from datetime import datetime

# 配置路径 (保持与 Poe_News.py 一致)
TXT_DIRECTORY = '/Users/yanzhang/Coding/News'

def get_cleaned_clipboard_content() -> str:
    """
    获取剪贴板内容，并去除其中的所有空行。
    """
    content = pyperclip.paste()
    if not content:
        return ""
    
    # 1. 按行分割
    # 2. strip() 去除每行前后的空白字符
    # 3. if line.strip() 过滤掉纯空白行
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    # 重新用换行符连接
    return "\n".join(lines)

def main():
    # 1. 获取并清理剪贴板内容（去除空行）
    english_content = get_cleaned_clipboard_content()
    
    if not english_content:
        print("剪贴板为空或仅包含空行，跳过写入。")
        return

    # 2. 计算文件名 (必须与 Poe_News.py 的逻辑完全一致)
    now = datetime.now()
    txt_file_name = f"News_{now.strftime('%y_%m_%d')}.txt"
    txt_file_path = os.path.join(TXT_DIRECTORY, txt_file_name)
    
    # 3. 追加写入
    # Poe_News.py 在中文写完后已经加了 \n\n，所以这里直接写内容即可
    # 为了保险，我们在英文内容前确认没有多余空行，或者保持格式整洁
    try:
        with open(txt_file_path, 'a', encoding='utf-8-sig') as f:
            # 写入清理后的内容 + 结尾两个换行符作为条目分隔
            f.write(english_content + '\n\n')
        print(f"英文内容（已去空行）已追加至: {txt_file_path}")
    except Exception as e:
        print(f"追加英文内容失败: {e}")

if __name__ == "__main__":
    main()