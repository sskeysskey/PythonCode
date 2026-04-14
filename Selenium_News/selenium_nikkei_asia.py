import os
import glob
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from urllib.parse import urlparse
from datetime import datetime, timedelta
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
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "nikkei_asia.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "nikkei_asia.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# 设置超时时间
TIMEOUT = 20 

# ================= 过滤黑名单 =================
# 这里列出所有不需要抓取的栏目名称
EXCLUDED_TITLES = {
    "Bonds", "Commodities", "Wealth Management", "China", "Japan", "India",
    "South Korea", "Indonesia", "Taiwan", "Thailand", "U.S.", "Hong Kong",
    "Macao", "Mongolia", "North Korea", "Malaysia", "Singapore", "Philippines",
    "Vietnam", "Myanmar", "Cambodia", "Laos", "Brunei", "East Timor",
    "Pakistan", "Afghanistan", "Bangladesh", "Sri Lanka", "Nepal", "Bhutan",
    "Maldives", "Kazakhstan", "Uzbekistan", "Turkmenistan", "Tajikistan",
    "Kyrgyzstan", "Australia", "New Zealand", "Papua New Guinea", "ARTIFICIAL INTELLIGENCE",
    "Pacific Islands", "Middle East", "Russia & Caucasus", "North America",
    "Latin America", "Europe", "Africa", "Trading Asia", "Opinion", "Life & Arts",
    "Politics", "Economy", "Business", "Tech", "Spotlight", "Tech Asia", "Artificial intelligence",
    "Electric vehicles"
}

# ================= 工具函数 =================

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度，如果相似度超过阈值则返回 True，否则返回 False。
    主要比较 URL 的协议、主机名和路径。
    """
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def main():
    # 获取当前日期
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

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
    options.add_argument("--disable-images")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.page_load_strategy = 'eager'

    # 设置 ChromeDriver
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        print("请下载对应版本的 ChromeDriver 并放置在该路径下。")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Selenium 启动失败: {e}")
        return
        
    driver.set_page_load_timeout(30)
    
    # 初始化数据容器
    new_rows = []
    new_rows1 = []
    old_content = []
    old_file_list = glob.glob(OLD_FILE_PATTERN)

    try:
        print("正在访问 Nikkei Asia...")
        driver.get("https://asia.nikkei.com/")

        # 等待页面主要内容加载
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-trackable='home']"))
            )
            print("页面主要内容已加载。")
        except Exception as e:
            print(f"等待页面加载超时: {e}")
            driver.quit()
            return

        # --- 2. 查找旧的 HTML 文件 ---
        if old_file_list:
            old_file_path = old_file_list[0]
            seven_days_ago = current_datetime - timedelta(days=30)
            try:
                with open(old_file_path, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    rows = soup.find_all('tr')[1:]  # 跳过标题行
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            date_str = cols[0].text.strip()
                            try:
                                date = datetime.strptime(date_str, '%Y_%m_%d_%H')
                                # 若日期符合条件则保留
                                if date >= seven_days_ago:
                                    title_column = cols[1]
                                    title = title_column.text.strip()
                                    link = title_column.find('a')['href'] if title_column.find('a') else None
                                    old_content.append([date_str, title, link])
                            except ValueError:
                                continue
            except OSError as e:
                print(f"读取文件时出错: {e}")

        # --- 3. 抓取新内容 ---
        all_links = [old_link for _, _, old_link in old_content if old_link]
        print("开始滚动页面以加载更多内容...")
        last_height = driver.execute_script("return document.body.scrollHeight")

        for i in range(2):  # 增加滚动次数
            driver.execute_script("window.scrollBy(0, 1000);")  # 增加滚动距离
            print(f"滚动次数: {i+1}/2")
            time.sleep(1.5)  # 关键：增加等待时间，让动态内容有时间加载
            
            # 检查页面高度是否变化（可选的智能等待）
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("  ↳ 页面高度未变化，可能已到底部")
            last_height = new_height

        # 最后等待一段时间让所有内容渲染完成
        time.sleep(2)
        print("滚动完成，开始抓取内容。")

        # 定义需要抓取的版块
        SECTIONS = ["Spotlight", "Business", "Economy"]
        # CSS选择器：不区分大小写
        css_selector = ", ".join(
            f"a[href*='/{section}/' i]:not(.label-link)" for section in SECTIONS
        )

        # 替换为更严格的等待：
        try:
            # 等待至少有一定数量的元素出现
            WebDriverWait(driver, 15).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, css_selector)) > 50
            )
            print(f"检测到足够多的链接元素，开始提取...")
            
            # === [核心修改 1]：先获取元素对象 ===
            titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
            print(f"找到了 {len(titles_elements)} 个符合条件的链接元素。")
            
            # === [核心修改 2]：快速提取数据 (Snapshot)，避免 StaleElementReference ===
            # 我们在这里只做提取，不做复杂的过滤，尽快把数据拿到手
            raw_data_list = []
            
            for element in titles_elements:
                try:
                    href = element.get_attribute('href')
                    # 尝试获取标题
                    try:
                        title_text = element.find_element(By.CSS_SELECTOR, "h2, h3").text.strip()
                    except:
                        title_text = element.text.strip() or element.get_attribute('innerText').strip()
                    
                    if href and title_text:
                        raw_data_list.append((href, title_text))
                        
                except StaleElementReferenceException:
                    # 如果这个元素在遍历过程中失效了，直接跳过，不影响整体
                    continue
                except Exception:
                    continue
            
            print(f"成功提取了 {len(raw_data_list)} 条原始数据，开始过滤...")

            # === [核心修改 3]：对静态数据进行逻辑过滤 ===
            for href, title_text in raw_data_list:
                lower_title = title_text.lower()
                
                # 逻辑解释：
                # 1. "xi jinping" in lower_title -> 忽略大小写 (匹配 Xi Jinping, xi jinping, XI JINPING)
                # 2. "Xi's" in title_text      -> 严格匹配 (只匹配 Xi's，不匹配 xi's 或 XI'S)
                if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                    continue
                
                # 1. 检查是否在黑名单中
                if title_text in EXCLUDED_TITLES:
                    continue

                # 2. 检查长度（真正的新闻标题通常不会只有 1 个单词）
                #    如果标题只有1个单词，且不在排除名单里，大概率也是误判，建议过滤
                if len(title_text.split()) <= 1:
                    continue
                
                # 3. 原有的关键字排除
                general_keywords_to_exclude = [
                    'Podcast', 'sports', '/music/', 'weather', '/books/', 'food',
                    'The-Future-of-Asia', 'Your-Week-in-Asia'
                ]
                if any(keyword.lower() in href.lower() for keyword in general_keywords_to_exclude):
                    continue

                # 4. 结构判断 (Spotlight/Business 下的二级目录)
                skip_due_to_structure = False
                try:
                    parsed_url = urlparse(href)
                    if parsed_url.netloc == "asia.nikkei.com":
                        path_segments = [
                            seg for seg in parsed_url.path.strip("/").split("/") if seg
                        ]
                        # 排除仅有两级目录的特定链接 (例如 /Spotlight/xxxx)
                        if (
                            path_segments and
                            path_segments[0].lower() in [s.lower() for s in SECTIONS] and
                            len(path_segments) == 2
                        ):
                            skip_due_to_structure = True
                except ValueError:
                    skip_due_to_structure = True
                
                if skip_due_to_structure:
                    continue

                # 滤重逻辑
                if not any(is_similar(href, existing_link) for existing_link in all_links):
                    new_rows.append([formatted_datetime, title_text, href])
                    new_rows1.append(["NikkeiAsia", title_text, href])
                    all_links.append(href)

            # 日志
            print("-" * 40)
            if new_rows:
                print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
            else:
                print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
            print("-" * 40)

        except Exception as e:
            print("抓取过程中出现错误:", e)
    finally:
        driver.quit()

    # --- 4. 文件写入操作 ---
    
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

    # 创建 HTML 文件
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
        file_exists = os.path.isfile(TODAY_HTML_PATH)
        closing_tag = "</table></body></html>"
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
                new_content = content + append_content + closing_tag
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as html_file:
                    html_file.write(new_content)
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
