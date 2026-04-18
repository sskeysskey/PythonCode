import os
import glob
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
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
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "washingtonpost.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "washingtonpost.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_eng.html")

# ========================================================

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度 (忽略协议和参数差异)
    """
    if not url1 or not url2:
        return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    base_url1 = f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}"
    base_url2 = f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"
    return base_url1 == base_url2

def is_short_title(title):
    """
    判断标题是否过短 (少于 5 个单词 或 少于 40 个字符)
    """
    if not title:
        return True
    return len(title.split()) < 5 or len(title) < 40

def get_full_title_with_retry(driver, max_retries=3):
    """
    在当前窗口（详情页）上，带重试地获取完整标题。
    使用 JS 直接读取 textContent，避免 stale 引用。
    """
    h1_css = "h1[data-testid='headline'], h1[data-qa='headline'], h1"
    
    for attempt in range(max_retries):
        try:
            # 1. 等待 h1 出现
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, h1_css))
            )
            # 2. 再稍等一下，让 React hydration 完成
            time.sleep(0.8)
            
            # 3. 用 JS 原子地读取当前最新的 h1 文本（而不是先拿 element 再 .text）
            full_title = driver.execute_script(
                f"const el = document.querySelector(\"{h1_css}\");"
                "return el ? el.textContent.trim() : '';"
            )
            
            if full_title and len(full_title) >= 10:
                return full_title
            # 如果读到空或过短，重试
        except StaleElementReferenceException:
            # 文档推荐做法：捕获异常 -> 重新定位 -> 重试
            if attempt == max_retries - 1:
                raise
            time.sleep(0.5)
            continue
        except TimeoutException:
            return None
    
    return None

def fetch_full_title_via_http(url, user_agent):
    try:
        headers = {"User-Agent": user_agent}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 优先拿 meta og:title（WaPo 的 og:title 一般是完整标题）
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        h1 = soup.find("h1")
        return h1.get_text(strip=True) if h1 else None
    except Exception:
        return None

def main():
    # 获取当前日期
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # ================= 1. 初始化 Selenium (优化版) =================
    print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
    
    options = webdriver.ChromeOptions()
    # 仅当二进制文件存在时才设置，否则依赖 Selenium 自动查找
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    else:
        print(f"警告：未找到 Chrome 二进制文件于 {CHROME_BINARY_PATH}，尝试使用系统默认路径...")

    # --- Headless模式 & 伪装设置 ---
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    
    # --- 伪装 User-Agent ---
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
    
    # 初始化容器
    new_rows = []
    new_rows1 = []
    old_content = []
    
    try:
        # 打开 WashingtonPost 网站
        print("正在访问 Washington Post...")
        driver.get("https://www.washingtonpost.com/")

        # ================= 2. 滚动加载 (替代 pyautogui) =================
        # 使用 JS 滚动，更稳定且支持 Headless
        print("开始滚动页面...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.5)
        print("滚动完成。")

        # ================= 3. 读取旧文件逻辑 =================
        old_file_list = glob.glob(OLD_FILE_PATTERN)
        if old_file_list:
            old_file_path = old_file_list[0]
            # 保持原逻辑：保留10天内的数据
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
                                if date >= seven_days_ago:
                                    title_column = cols[1]
                                    title = title_column.text.strip()
                                    link = title_column.find('a')['href'] if title_column.find('a') else None
                                    old_content.append([date_str, title, link])
                            except ValueError:
                                continue
            except OSError as e:
                print(f"读取旧文件时出错: {e}")

        # ================= 4. 抓取新内容 (Snapshot 策略) =================
        
        # 既有的所有链接（用于排重）
        all_links = [old_link for _, _, old_link in old_content]

        # 动态生成年份选择器，避免硬编码
        # 逻辑：查找包含当前年份链接的文章
        css_selector = f"a[href*='/{current_datetime.year}/']:not(.label-link)"
        
        try:
            # 等待元素加载
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            
            # --- 步骤 A: 获取元素对象 ---
            titles_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
            print(f"找到了 {len(titles_elements)} 个潜在链接元素。")

            # --- 步骤 B: 快速提取数据 ---
            raw_data_list = []
            for element in titles_elements:
                try:
                    href = element.get_attribute('href')
                    # 尝试获取标题，优先查找内部 h2/h3，兼容性处理
                    try:
                        title_text = element.find_element(By.CSS_SELECTOR, "h2, h3").text.strip()
                    except:
                        title_text = element.text.strip() or element.get_attribute('innerText').strip()
                    
                    if href and title_text:
                        raw_data_list.append((href, title_text))
                except StaleElementReferenceException:
                    continue 
                except Exception:
                    continue
            
            print(f"成功提取了 {len(raw_data_list)} 条原始数据。")

            # --- 步骤 B.5: 针对过短的标题，进入详情页抓取完整标题 ---
            print("正在检查并修复过短的标题...")
            updated_raw_data_list = []
            
            for href, title_text in raw_data_list:
                # if is_short_title(title_text):
                #     full_title = fetch_full_title_via_http(href, user_agent)
                #     if full_title and not is_short_title(full_title):
                #         print(f"  ✅ HTTP 获取完整标题: '{full_title}'")
                #         title_text = full_title
                if is_short_title(title_text):
                    print(f"发现短标题: '{title_text}' -> 正在进入详情页获取完整标题...")
                    main_handle = driver.current_window_handle
                    try:
                        driver.execute_script(f"window.open('{href}', '_blank');")
                        # 切到新标签
                        new_handle = [h for h in driver.window_handles if h != main_handle][-1]
                        driver.switch_to.window(new_handle)
                        
                        full_title = get_full_title_with_retry(driver)
                        if full_title:
                            print(f"  ✅ 成功获取完整标题: '{full_title}'")
                            title_text = full_title
                        else:
                            print("  ⚠️ 未能获取完整标题，保留原标题。")
                    except Exception as e:
                        print(f"  ⚠️ 获取详情页标题失败 ({type(e).__name__})，保留原标题。")
                    finally:
                        # 关闭详情页，切回主页
                        if driver.current_window_handle != main_handle:
                            driver.close()
                        driver.switch_to.window(main_handle)
                
                updated_raw_data_list.append((href, title_text))
                
            # 将更新后的数据赋值回 raw_data_list
            raw_data_list = updated_raw_data_list

            # --- 步骤 C: 逻辑过滤 (纯 Python 处理) ---
            print("开始过滤数据...")
            # 定义排除关键字
            exclude_keywords = ['podcasts', 'sports', '/music/', 'weather', '/books/',
                                'food', '/advice/', '/tv/', '/entertainment/',
                                '/national-security/', '/opinions/']
                                
            for href, title_text in raw_data_list:
                lower_title = title_text.lower()
                
                # 逻辑解释：
                # 1. "xi jinping" in lower_title -> 忽略大小写 (匹配 Xi Jinping, xi jinping, XI JINPING)
                # 2. "Xi's" in title_text      -> 严格匹配 (只匹配 Xi's，不匹配 xi's 或 XI'S)
                if "xi jinping" in lower_title or "Xi's" in title_text or "Tiananmen" in title_text:
                    continue
                
                # 1. 关键字过滤
                if any(keyword in href for keyword in exclude_keywords):
                    continue

                # 2. 排重过滤 (使用 is_similar)
                # 检查旧内容
                if any(is_similar(href, old_link) for _, _, old_link in old_content):
                    continue
                # 检查本次新内容
                if any(is_similar(href, new_link) for _, _, new_link in new_rows):
                    continue
                
                # 通过所有检查，添加数据
                new_rows.append([formatted_datetime, title_text, href])
                new_rows1.append(["WashingtonPost", title_text, href])
                all_links.append(href)

            # --- 日志输出 ---
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

    # ================= 5. 文件写入操作 =================
    
    # 确保目标目录存在
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)

    # 删除旧文件
    if old_file_list and os.path.exists(old_file_list[0]):
        try:
            os.remove(old_file_list[0])
            print(f"文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: {e.strerror}. 文件无法删除。")

    # 创建 Site HTML 文件
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
        print(f"已更新站点文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 Site HTML 出错: {e}")

    # 创建/更新 每日新闻总表
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
                
                # 尝试多种换行格式的结束标签
                content = content.replace(closing_tag, "")
                content = content.replace("</table>\n</body>\n</html>", "")
                
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