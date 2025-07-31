import pyperclip
import re

# 西里尔字母到拉丁字母的映射表
cyrillic_to_latin = {
    'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'У': 'Y', 'Х': 'X',
    'а': 'a', 'в': 'b', 'е': 'e', 'к': 'k', 'м': 'm', 'н': 'h', 'о': 'o', 'р': 'p', 'с': 'c', 'т': 't', 'у': 'y', 'х': 'x'
}

def translate_cyrillic(text, mapping):
    """ 使用提供的映射表转换文本中的西里尔字母到拉丁字母 """
    return ''.join(mapping.get(ch, ch) for ch in text)

def process_clipboard_content():
    # 从剪贴板获取内容
    content = pyperclip.paste()
    # 将内容按行分开
    lines = content.split('\n')

    # 用于存储最终的字串集合，使用集合可以自动去重
    result_set = set()

    # 正则表达式，匹配全大写字母的单词，要求单词两边是空格或位于行首行尾
    pattern = re.compile(r'(?<!\S)[A-Z]+(?!\S)')

    for line in lines:
        # 去除空白行
        if line.strip() == "":
            continue

        # 将西里尔字母转换为拉丁字母
        translated_line = translate_cyrillic(line, cyrillic_to_latin)

        # 新增规则：如果行内有小写字母或非空格符号，跳过这一行
        if re.search(r'[a-z]|[^A-Z\s]', translated_line):
            continue

        # 判断是否是全大写行
        if translated_line.isupper():
            # 对全大写行按空格分割，单独处理每个部分
            parts = translated_line.split()
            for part in parts:
                # 每个部分必须满足全大写无其他字符
                if part.isupper():
                    result_set.add(part)
        else:
            # 在非全大写的行中查找符合条件的大写字串
            matches = pattern.findall(translated_line)
            result_set.update(matches)

    # 将结果排序后转换成字符串，每个元素一行
    result_content = '\n'.join(sorted(result_set))
    
    # 将处理后的内容写回剪贴板
    pyperclip.copy(result_content)

# 调用函数
process_clipboard_content()