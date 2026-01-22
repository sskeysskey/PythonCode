import os
import time
import glob
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
import sys
import platform # <--- 新增

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础路径
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 3. 浏览器与驱动路径 (跨平台适配)
if platform.system() == 'Darwin':
    # macOS 配置 (保持原样)
    CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver_beta")
elif platform.system() == 'Windows':
    # Windows 配置 (默认使用标准版 Chrome)
    CHROME_BINARY_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(CHROME_BINARY_PATH):
        CHROME_BINARY_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver.exe")
else:
    # Linux
    CHROME_BINARY_PATH = "/usr/bin/google-chrome"
    CHROME_DRIVER_PATH = "/usr/bin/chromedriver"

# 4. 业务文件路径
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "economist.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "economist.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# 设置超时时间
TIMEOUT = 20 

# ================= 工具函数 =================

def open_html_file(file_path):
    # <--- 跨平台修改：处理 Windows 路径反斜杠和 file:// 格式 --->
    real_path = os.path.realpath(file_path)
    if os.name == 'nt':
        url = 'file:///' + real_path.replace('\\', '/')
    else:
        url = 'file://' + real_path
    webbrowser.open(url, new=2)

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度，如果是同一篇文章则返回 True。
    """
    if not url1 or not url2:
        return False
        
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    # 比较基本部分：协议、主机名
    if parsed_url1.netloc != parsed_url2.netloc:
        return False
        
    # 对于Economist特有的URL结构进行处理
    path1 = parsed_url1.path.rstrip('/')
    path2 = parsed_url2.path.rstrip('/')
    
    path_components1 = path1.split('/')
    path_components2 = path2.split('/')
    
    # 确保路径组件足够比较
    if len(path_components1) < 5 or len(path_components2) < 5:
        return path1 == path2
    
    # 去掉空字符串
    path_components1 = [comp for comp in path_components1 if comp]
    path_components2 = [comp for comp in path_components2 if comp]
    
    min_length = min(len(path_components1), len(path_components2))
    comp_length = min(min_length, 5)
    
    return path_components1[:comp_length] == path_components2[:comp_length]

# ================= 主程序逻辑 =================

def main():
    # ================= 1. 初始化 Selenium (核心移植部分) =================
    print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
    
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        print(f"警告：未找到 Chrome 二进制文件于 {CHROME_BINARY_PATH}，尝试使用系统默认路径...")

    # --- Headless模式 & 伪装设置 ---
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    
    # --- 伪装设置 (User-Agent & 去除自动化特征) ---
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # --- 性能优化 ---
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--blink-settings=imagesEnabled=false")  # 禁用图片加载
    options.page_load_strategy = 'eager'  # DOM准备好就开始

    # 设置 ChromeDriver
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        print("请下载对应版本的 ChromeDriver 并放置在该路径下。")
        return

    # 启动浏览器
    service = Service(executable_path=CHROME_DRIVER_PATH)
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Selenium 启动失败: {e}")
        return
        
    # 设置页面加载超时
    driver.set_page_load_timeout(30)
    wait = WebDriverWait(driver, 10)

    # 初始化变量，防止 finally 中报错
    new_rows = []
    new_rows1 = []
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)

    try:
        print("正在访问 The Economist...")
        driver.get("https://www.economist.com/")
        
        # --- 2. 处理 Cookie 同意弹窗 ---
        try:
            # 尝试查找包含 "Accept" 或 "Agree" 字样的按钮
            accept_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept') or contains(., 'Agree')]")
            ))
            print("检测到 Cookie 弹窗，正在点击...")
            accept_button.click()
            time.sleep(1) # 等待弹窗消失
        except Exception:
            # 如果没找到按钮，可能是因为无头模式+伪装直接绕过了弹窗，或者是选择器不匹配
            print("未检测到明显的 Cookie 弹窗或已自动跳过，继续执行。")

        # --- 3. 查找旧的 HTML 文件 ---
        if old_file_list:
            old_file_path = old_file_list[0]
            threshold_date = datetime.now() - timedelta(days=45)
            try:
                with open(old_file_path, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    rows = soup.find_all('tr')[1:]  # 跳过标题行
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            date_str = cols[0].text.strip()
                            try:
                                date_obj = datetime.strptime(date_str, '%Y_%m_%d_%H')
                                if date_obj >= threshold_date:
                                    title_column = cols[1]
                                    title = title_column.text.strip()
                                    link = title_column.find('a')['href'] if title_column.find('a') else None
                                    old_content.append([date_str, title, link])
                            except ValueError:
                                continue
            except Exception as e:
                print(f"读取旧文件出错: {e}")

        # --- 4. 抓取新内容 ---
        
        # [新增] 滚动机制
        print("开始滚动页面以加载更多内容...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 1000);") # Economist 页面较长，每次滚动 1000
            print(f"滚动次数: {i+1}/4")
            time.sleep(0.5)
        print("滚动完成，开始抓取内容。")

        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
            
            # 获取元素列表
            titles_elements = driver.find_elements(By.CSS_SELECTOR, f"a[href*='/{datetime.now().year}/']")
            formatted_datetime = datetime.now().strftime("%Y_%m_%d_%H")
            
            # [核心修改] 第一步：只提取原始数据 (Snapshot)
            # 这样可以避免 "Stale element reference" 错误
            raw_data_list = []
            for element in titles_elements:
                try:
                    href = element.get_attribute('href')
                    # 尝试多种方式获取文本
                    title_text = element.text.strip() or element.get_attribute('innerText').strip()
                    if href and title_text:
                        raw_data_list.append((href, title_text))
                except StaleElementReferenceException:
                    continue # 忽略失效的元素
                except Exception:
                    continue
            
            print(f"提取到 {len(raw_data_list)} 个原始链接，开始处理逻辑...")

            # [核心修改] 第二步：处理逻辑 (过滤和排重)
            for href, title_text in raw_data_list:
                lower_title = title_text.lower()
                
                # 逻辑解释：
                # 1. "xi jinping" in lower_title -> 忽略大小写 (匹配 Xi Jinping, xi jinping, XI JINPING)
                # 2. "Xi's" in title_text      -> 严格匹配 (只匹配 Xi's，不匹配 xi's 或 XI'S)
                if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                    continue

                # 原有的排除逻辑 (保持不变)
                if ('podcasts' not in href and "film" not in href and "cartoon" not in href and 
                    not ('letters' in href and 'editor' in href and 'Sources and acknowledgments' in href)):
                    
                    # 检查重复
                    is_old_duplicate = any(is_similar(href, old_link) for _, _, old_link in old_content)
                    is_new_duplicate = any(is_similar(href, new_link) for _, _, new_link in new_rows)
                    
                    if not is_old_duplicate and not is_new_duplicate:
                        new_rows.append([formatted_datetime, title_text, href])
                        new_rows1.append(["Economist", title_text, href])

            print("-" * 40)
            if new_rows:
                print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
            else:
                print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
            print("-" * 40)

        except Exception as e:
            print("抓取过程中出现错误:", e)
    finally:
        # 关闭驱动
        driver.quit()

    # --- 5. 文件写入操作 ---
    
    # 确保目标目录存在
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)

    if old_file_list:
        try:
            if os.path.exists(old_file_list[0]):
                os.remove(old_file_list[0])
                print(f"文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: 无法删除旧文件 {e}")

    # 创建 site HTML 文件
    try:
        with open(NEW_HTML_PATH, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>Date</th><th>Title</th></tr>\n")
            
            for row in new_rows:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
            
            for row in old_content:
                clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>" if row[2] else row[1]
                html_file.write(f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n")
            
            html_file.write("</table></body></html>")
        print(f"已更新文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 HTML 出错: {e}")

    # 创建每日新闻总表 HTML
    if new_rows1:
        closing_tag = "</table></body></html>"
        file_exists = os.path.isfile(TODAY_HTML_PATH)
        
        append_content = ""
        for row in new_rows1:
            clickable_title = f"<a href='{row[2]}' target='_blank'>{row[1]}</a>"
            append_content += f"<tr><td>{row[0]}</td><td>{clickable_title}</td></tr>\n"
        
        try:
            if file_exists:
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as html_file:
                    content = html_file.read()
                if closing_tag in content:
                    content = content.replace(closing_tag, "")
                new_file_content = content + append_content + closing_tag
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write(new_file_content)
            else:
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write("<html><body><table border='1'>\n")
                    html_file.write("<tr><th>site</th><th>Title</th></tr>\n")
                    html_file.write(append_content)
                    html_file.write(closing_tag)
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()
