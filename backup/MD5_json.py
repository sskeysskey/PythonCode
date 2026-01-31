import hashlib

def compute_md5(path):
    hash_md5 = hashlib.md5()
    try:
        with open(path, "rb") as f:
            # 每次读取 4096 字节，防止大文件占用过多内存
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except FileNotFoundError:
        return "文件未找到，请检查路径是否正确。"

# 你的目标文件路径
file_path = "/Users/yanzhang/Coding/LocalServer/Resources/ONews/onews_260131.json"

# 执行计算并打印结果
md5_result = compute_md5(file_path)
print(f"文件: {file_path}")
print(f"MD5 码为: {md5_result}")