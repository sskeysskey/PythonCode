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
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
import platform

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础路径
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 3. 浏览器与驱动路径 (跨平台适配)
if platform.system() == 'Darwin':
    # macOS 配置
    CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver_beta")
elif platform.system() == 'Windows':
    # Windows 配置
    CHROME_BINARY_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(CHROME_BINARY_PATH):
        CHROME_BINARY_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver.exe")
else:
    # Linux
    CHROME_BINARY_PATH = "/usr/bin/google-chrome"
    CHROME_DRIVER_PATH = "/usr/bin/chromedriver"

# 4. 业务文件路径 (修改为 bbc.html)
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "bbc.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "bbc.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# 设置超时时间
TIMEOUT = 20 

# ================= 工具函数 =================

def open_html_file(file_path):
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
    
    if parsed_url1.netloc != parsed_url2.netloc:
        return False
        
    path1 = parsed_url1.path.rstrip('/')
    path2 = parsed_url2.path.rstrip('/')
    
    return path1 == path2

# ================= 主程序逻辑 =================

def main():
    print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
    
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        print(f"警告：未找到 Chrome 二进制文件于 {CHROME_BINARY_PATH}，尝试使用系统默认路径...")

    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-images")
    options.add_argument("--blink-settings=imagesEnabled=false")
    
    options.page_load_strategy = 'none'  

    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Selenium 启动失败: {e}")
        return
        
    driver.set_page_load_timeout(45)
    wait = WebDriverWait(driver, 15)

    new_rows = []
    new_rows1 = []
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)

    try:
        print("正在访问 BBC News...")
        
        try:
            # 访问 BBC 新闻主页
            driver.get("https://www.bbc.com/news")
            time.sleep(5) 
        except TimeoutException:
            print("警告: 页面加载超时，尝试继续执行...")
        
        # 处理可能的 Cookie 弹窗
        try:
            accept_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept') or contains(., 'Agree') or contains(., 'Yes, I agree')]")
            ))
            print("检测到 Cookie 弹窗，正在点击...")
            accept_button.click()
            time.sleep(1)
        except Exception:
            print("未检测到明显的 Cookie 弹窗或已自动跳过，继续执行。")

        # 读取旧的 HTML 文件
        if old_file_list:
            old_file_path = old_file_list[0]
            threshold_date = datetime.now() - timedelta(days=45)
            try:
                with open(old_file_path, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    rows = soup.find_all('tr')[1:] 
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

        # 滚动页面以加载更多内容
        print("开始滚动页面以加载更多内容...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 1000);") 
            print(f"滚动次数: {i+1}/4")
            time.sleep(1)
        print("滚动完成，开始抓取内容。")

        try:
            # 适配 BBC 的选择器
            # 包含 internal-link, external-anchor，以及卡片内的所有 a 标签
            selector = "a[data-testid='internal-link'], a[data-testid='external-anchor'], div[data-testid*='card'] a"
            titles_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            
            formatted_datetime = datetime.now().strftime("%Y_%m_%d_%H")
            
            raw_data_list = []
            seen_links = set() 

            print(f"初步定位到 {len(titles_elements)} 个元素，开始提取...")

            for element in titles_elements:
                try:
                    href = element.get_attribute('href')
                    if not href:
                        continue
                        
                    # 处理相对路径 (BBC 经常使用 /news/articles/...)
                    if href.startswith('/'):
                        href = f"https://www.bbc.com{href}"
                        
                    title_text = element.get_attribute('innerText').strip()
                    if not title_text:
                        title_text = element.text.strip()
                    
                    # 过滤掉杂音文本，如时间标签、"Read more"等
                    title_text = title_text.replace('\n', ' ').strip()
                    
                    if href and title_text and href not in seen_links:
                        if len(title_text) > 10 and "BBC" not in title_text: 
                            raw_data_list.append((href, title_text))
                            seen_links.add(href)
                except StaleElementReferenceException:
                    continue 
                except Exception:
                    continue
            
            print(f"提取到 {len(raw_data_list)} 个有效原始链接，开始业务逻辑过滤...")

            # 定义需要过滤的“杂音”标题列表
            noise_titles = [
                "Terms of Use", "Subscription Terms", "Privacy Policy", 
                "Accessibility Help", "Advertise with us", 
                "Do not share or sell my info", "Content Index", 
                "Set Preferred Source"
            ]

            for href, title_text in raw_data_list:
                # 过滤掉非新闻类的链接 (如天气、体育等，可根据需要调整)
                if '/weather/' in href or '/sport/' in href or '/sounds/' in href or '/live/' in href or '/videos/' in href:
                    continue

                # 过滤掉指定的“杂音”标题
                # 使用 any() 检查 title_text 是否包含列表中的任何一个字符串
                if any(noise in title_text for noise in noise_titles):
                    continue

                is_old_duplicate = any(is_similar(href, old_link) for _, _, old_link in old_content)
                is_new_duplicate = any(is_similar(href, new_link) for _, _, new_link in new_rows)
                
                if not is_old_duplicate and not is_new_duplicate:
                    print(f"  [新增] {title_text}") 
                    new_rows.append([formatted_datetime, title_text, href])
                    new_rows1.append(["BBC", title_text, href])

            print("-" * 40)
            if new_rows:
                print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
            else:
                print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
            print("-" * 40)

        except Exception as e:
            print("抓取过程中出现错误:", e)
            import traceback
            traceback.print_exc()
    finally:
        driver.quit()

    # --- 5. 文件写入操作 ---
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)

    if old_file_list:
        try:
            if os.path.exists(old_file_list[0]):
                os.remove(old_file_list[0])
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