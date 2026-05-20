import json
from bs4 import BeautifulSoup
import re

# 这里放入您提供的 HTML 代码片段（为了演示，这里做了截断，实际使用时请填入完整的 HTML 字符串）
html_content = """
<div id="viewbox_report" class="video-info-container mac">
    <h1 data-title="坚持这样练习，英语听力口语突飞猛进" class="video-title special-text-indent">坚持这样练习，英语听力口语突飞飞猛进</h1>
</div>
<div class="pubdate-ip-text">2026-04-22 19:00:00</div>
<div class="ordinary-tag">
    <a href="..." class="tag-link">英语听力</a>
</div>
<div class="ordinary-tag">
    <a href="..." class="tag-link">英语口语</a>
</div>
<div id="user-name">
    <a target="_blank" href="Uspace.bilibili.com/1228912908">"曦雅英语"</a>
</div>
<p id="contents">
    <span>欢迎了解课程\n</span>
</p>
"""

def extract_bilibili_data(html_str):
    # 使用 lxml 解析器容错率更高，适合处理复制出来的带有特殊字符的 HTML
    soup = BeautifulSoup(html_str, 'lxml')
    
    # 1. 提取 name (视频标题)
    name = ""
    title_tag = soup.find('h1', class_=re.compile(r'video-title'))
    if title_tag:
        name = title_tag.get('data-title') or title_tag.text.strip()
        
    # 2. 提取 time (发布时间)
    time = ""
    time_tag = soup.find('div', class_='pubdate-ip-text')
    if time_tag:
        time = time_tag.text.strip()
        
    # 3. 提取 tag (标签列表)
    tags = []
    tag_links = soup.find_all('a', class_='tag-link')
    for tag in tag_links:
        tags.append(tag.text.strip())
        
    # 4. 提取 user (留言用户名)
    user = ""
    user_name_div = soup.find('div', id='user-name')
    if user_name_div and user_name_div.find('a'):
        # 去除可能包含的引号和空白符
        user = user_name_div.find('a').text.strip().replace('"', '').replace('”', '').replace('“', '')
        
    # 5. 提取 content (留言内容)
    content = ""
    contents_p = soup.find('p', id='contents')
    if contents_p and contents_p.find('span'):
        content = contents_p.find('span').text.strip()
        
    # 组装成字典
    data = {
        "name": name,
        "time": time,
        "tag": tags,
        "user": user,
        "content": content
    }
    
    return data

def save_to_json(data, file_path):
    # 写入 JSON 文件，ensure_ascii=False 保证中文正常显示
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"数据已成功写入到 {file_path}")

if __name__ == "__main__":
    # 解析数据
    extracted_data = extract_bilibili_data(html_content)
    
    # 打印查看结果
    print("提取到的数据：", json.dumps(extracted_data, ensure_ascii=False, indent=4))
    
    # 写入到您指定的路径
    target_path = "/Users/yanzhang/Downloads/a.json"
    try:
        save_to_json(extracted_data, target_path)
    except Exception as e:
        print(f"写入文件时发生错误，请检查路径权限: {e}")