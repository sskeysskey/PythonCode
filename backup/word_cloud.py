# 导入必要的库
from wordcloud import WordCloud
import matplotlib.pyplot as plt

# 读取整个文本文件
with open('/Users/yanzhang/Downloads/backup/TXT/10倍成長思維.txt', 'r', encoding='utf-8') as file:
    text = file.read()

# 指定中文支持的字体路径
font_path = '/Users/yanzhang/Library/Fonts/FangZhengHeiTiJianTi-1.ttf'  # 替换为你的字体文件路径

# 创建词云对象，指定字体路径以支持中文
wordcloud = WordCloud(
    width=800,
    height=400,
    background_color='white',
    font_path=font_path  # 使用支持中文的字体
).generate(text)

# 显示生成的词云图片
plt.figure(figsize=(10, 5))
plt.imshow(wordcloud, interpolation='bilinear')
plt.axis('off')  # 不显示坐标轴
plt.show()