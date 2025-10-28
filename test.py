# 在代码开头添加这段来检查版本
import subprocess

# 检查 Chrome 版本
try:
    chrome_version = subprocess.check_output(
        ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--version']
    ).decode('utf-8').strip()
    print(f"Chrome 版本: {chrome_version}")
except Exception as e:
    print(f"无法获取 Chrome 版本: {e}")

# 检查 ChromeDriver 版本
try:
    driver_version = subprocess.check_output(
        ["/Users/yanzhang/Downloads/backup/chromedriver", '--version']
    ).decode('utf-8').strip()
    print(f"ChromeDriver 版本: {driver_version}")
except Exception as e:
    print(f"无法获取 ChromeDriver 版本: {e}")