import os
import subprocess

def check_virtualenv(path):
    activate_script = os.path.join(path, 'bin', 'activate')
    if os.path.exists(path) and os.path.isdir(path):
        if os.path.exists(activate_script):
            print(f"{path} 是一个Python虚拟环境。")
            # 在一个新的shell里面运行source命令激活虚拟环境
            subprocess.run(f"source {activate_script} && pip list", shell=True, executable='/bin/bash')
        else:
            print(f"{path} 不是一个Python虚拟环境。")
    else:
        print(f"路径 {path} 不存在。")

check_virtualenv("/Users/yanzhang/my_venv")
check_virtualenv("/Users/yanzhang/venv")