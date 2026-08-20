import json
import os

def compare_json(obj1, obj2, path=""):
    """
    递归比较两个 JSON 对象，返回差异列表。
    """
    diffs = []

    # 如果类型不同
    if type(obj1) != type(obj2):
        diffs.append(f"类型不匹配 at {path}: {type(obj1).__name__} vs {type(obj2).__name__}")
        return diffs

    # 如果是字典
    if isinstance(obj1, dict):
        keys1 = set(obj1.keys())
        keys2 = set(obj2.keys())
        
        # 检查键的差异
        for key in keys1 - keys2:
            diffs.append(f"键缺失 at {path}: {key} (在第二个文件中不存在)")
        for key in keys2 - keys1:
            diffs.append(f"键新增 at {path}: {key} (在第一个文件中不存在)")
        
        # 递归比较共有键的值
        for key in keys1 & keys2:
            diffs.extend(compare_json(obj1[key], obj2[key], f"{path}.{key}" if path else key))

    # 如果是列表
    elif isinstance(obj1, list):
        if len(obj1) != len(obj2):
            diffs.append(f"列表长度不一致 at {path}: {len(obj1)} vs {len(obj2)}")
        
        # 简单比较：假设列表顺序一致，逐项比较
        # 如果列表顺序可能不一致，需要更复杂的逻辑（如基于 name 字段匹配）
        for i in range(min(len(obj1), len(obj2))):
            diffs.extend(compare_json(obj1[i], obj2[i], f"{path}[{i}]"))

    # 如果是基础类型（字符串、数字等）
    else:
        if obj1 != obj2:
            diffs.append(f"值不一致 at {path}: '{obj1}' vs '{obj2}'")

    return diffs

def main():
    # file1_path = '/Users/yanzhang/Downloads/OVideos.json'
    file1_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
    # file1_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos_backup.json'
    # file2_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
    file2_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping copy.json'

    # 检查文件是否存在
    if not os.path.exists(file1_path) or not os.path.exists(file2_path):
        print("错误：找不到指定的文件。请检查路径是否正确。")
        return

    # 读取文件
    try:
        with open(file1_path, 'r', encoding='utf-8') as f1, open(file2_path, 'r', encoding='utf-8') as f2:
            data1 = json.load(f1)
            data2 = json.load(f2)
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}")
        return

    # 执行比较
    differences = compare_json(data1, data2)

    # 输出结果
    if not differences:
        print("两个文件完全一致！")
    else:
        print(f"发现 {len(differences)} 处差异：")
        for diff in differences:
            print(f"- {diff}")

if __name__ == "__main__":
    main()