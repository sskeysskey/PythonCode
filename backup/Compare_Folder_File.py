import os
from pathlib import Path
from typing import Set, Dict
from collections import defaultdict

def compare_directories(dir1: str, dir2: str) -> Dict[str, Set[str]]:
    """
    比较两个目录的文件差异
    
    Args:
        dir1: 第一个目录的路径
        dir2: 第二个目录的路径
        
    Returns:
        包含差异信息的字典，键为差异类型，值为文件集合
    """
    try:
        # 获取两个目录中的所有文件（使用 Path 对象使代码更现代化）
        files1 = {f.name for f in Path(dir1).rglob('*') if f.is_file()}
        files2 = {f.name for f in Path(dir2).rglob('*') if f.is_file()}
        
        # 计算差异
        differences = {
            'only_in_dir1': files1 - files2,
            'only_in_dir2': files2 - files1,
            'common': files1 & files2
        }
        
        return differences
        
    except Exception as e:
        print(f"发生错误: {str(e)}")
        return {}

def print_comparison_results(results: Dict[str, Set[str]], dir1: str, dir2: str):
    """
    打印比较结果
    
    Args:
        results: 比较结果字典
        dir1: 第一个目录路径
        dir2: 第二个目录路径
    """
    if not results:
        print("比较过程出现错误")
        return
        
    print(f"\n目录比较结果:")
    print(f"目录1: {dir1}")
    print(f"目录2: {dir2}")
    print("-" * 50)
    
    print(f"\n仅在目录1中存在的文件 ({len(results['only_in_dir1'])}个):")
    for file in sorted(results['only_in_dir1']):
        print(f"  - {file}")
        
    print(f"\n仅在目录2中存在的文件 ({len(results['only_in_dir2'])}个):")
    for file in sorted(results['only_in_dir2']):
        print(f"  - {file}")
        
    print(f"\n两个目录共有的文件 ({len(results['common'])}个):")
    for file in sorted(results['common']):
        print(f"  - {file}")

def main():
    # 示例使用
    dir1 = '/Users/yanzhang/Downloads/backup/TXT/Done/'
    dir2 = '/Users/yanzhang/Documents/Books/mp3/'
    
    if not os.path.exists(dir1) or not os.path.exists(dir2):
        print("错误：一个或两个目录路径不存在")
        return
        
    results = compare_directories(dir1, dir2)
    print_comparison_results(results, dir1, dir2)

if __name__ == "__main__":
    main()