import os
from pathlib import Path

def create_file_on_desktop():
    # 1. 获取当前用户的主目录 (Home Directory)
    home_dir = Path.home()
    
    # 2. 构建桌面的路径 (通常是 ~/Desktop)
    desktop_path = home_dir / "Desktop"
    
    # 3. 构建文件的完整路径
    file_path = desktop_path / "stop_downie.txt"
    
    try:
        # 4. 创建并写入文件
        # 'w' 模式表示写入，如果文件已存在会覆盖；如果想追加内容请用 'a'
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("这是一个由 Python 自动创建的文件。")
        
        print(f"成功：文件已创建在 {file_path}")
        
    except Exception as e:
        print(f"发生错误：无法创建文件。错误信息: {e}")

if __name__ == "__main__":
    create_file_on_desktop()