import re

def extract_urls(file_path):
    """
    从HTML文件中提取所有 <a href="..."> 的URL
    """
    urls = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 使用正则表达式查找 href 属性
            # 逻辑说明：查找 <a 开头，忽略中间属性，直到找到 href='...' 或 href="..."
            found = re.findall(r"<a\s+(?:[^>]*?\s+)?href=(['\"])(.*?)\1", content)
            
            for quote, url in found:
                urls.add(url.strip()) # 去除可能的首尾空格
                
    except FileNotFoundError:
        print(f"错误: 找不到文件 {file_path}")
        return set()
    return urls

# --- 主程序配置 ---
file_a_path = '/Users/yanzhang/Downloads/bloomberg_2026_01_05_12_27_40.html'  # 修改为你的第一个文件名
file_b_path = '/Users/yanzhang/Coding/News/backup/site/bloomberg copy.html'  # 修改为你的第二个文件名

# 1. 提取链接
print(f"正在读取文件...")
urls_a = extract_urls(file_a_path)
urls_b = extract_urls(file_b_path)

# 2. 进行集合运算
common_urls = urls_a & urls_b        # 交集：两个文件都有的
only_in_a = urls_a - urls_b          # 差集：只在 A 中有
only_in_b = urls_b - urls_a          # 差集：只在 B 中有

# 3. 输出统计结果
print("=" * 40)
print(f"分析结果:")
print(f"  - {file_a_path} 中的 URL 总数: {len(urls_a)}")
print(f"  - {file_b_path} 中的 URL 总数: {len(urls_b)}")
print("-" * 40)
print(f"✅ 一致的 URL (两个文件都有): {len(common_urls)} 个")
print(f"❌ 不同的 URL (总数): {len(only_in_a) + len(only_in_b)} 个")
print(f"    - 仅在 {file_a_path} 中: {len(only_in_a)} 个")
print(f"    - 仅在 {file_b_path} 中: {len(only_in_b)} 个")
print("=" * 40)

# 4. (可选) 如果想看具体是哪些链接不同，可以取消下面代码的注释
# print(f"\n仅在 {file_a_path} 中的链接:")
# for url in only_in_a: print(f"  - {url}")
# print(f"\n仅在 {file_b_path} 中的链接:")
# for url in only_in_b: print(f"  - {url}")
