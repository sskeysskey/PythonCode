import json
import os

# 定义文件路径
file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'

def remove_time_field(file_path):
    # 1. 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"错误：找不到文件 {file_path}")
        return

    try:
        # 2. 读取 JSON 文件
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 3. 定义需要处理的键名（Movie 和 Drama）
        categories = ['Movie', 'Drama', 'Show', 'Anime']

        # 4. 遍历并删除 time 字段
        for category in categories:
            if category in data:
                for item in data[category]:
                    if 'time' in item:
                        del item['time']
        
        # 5. 将修改后的数据写回文件
        # ensure_ascii=False 保证中文正常显示，indent=4 让 JSON 格式美观
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        print(f"成功！已从 {file_path} 中删除了所有 'time' 字段。")

    except Exception as e:
        print(f"发生错误: {e}")

# 执行函数
if __name__ == "__main__":
    remove_time_field(file_path)