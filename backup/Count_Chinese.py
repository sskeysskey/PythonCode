import sys
import re

def count_chinese_characters(text):
    # 使用正则表达式匹配所有中文字符 (Unicode 范围: \u4e00-\u9fff)
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    chinese_chars = chinese_pattern.findall(text)
    return len(chinese_chars)

if __name__ == "__main__":
    # 从命令行参数获取文本
    if len(sys.argv) > 1:
        content = sys.argv[1]
        count = count_chinese_characters(content)
        # 如果超过 50 个汉字，输出 true，否则输出 false
        if count > 50:
            print("true")
        else:
            print("false")
    else:
        print("false")
