import re

file_path = "/Users/yanzhang/Coding/News/TodayCNH_260726.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 匹配连续两行相同的checkbox td，删除重复一条
pattern = re.compile(
    r'(<td class="checkbox-cell"><input class="news-checkbox" type="checkbox" \/></td>\s*)'
    r'\1',
    re.MULTILINE
)
new_content = pattern.sub(r"\1", content)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("清理完成")