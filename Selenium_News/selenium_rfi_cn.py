import re
import os
import glob
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta

# --- 新增 Selenium 等待组件 ---
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
import platform

# ================= 配置区域 (RFI 专用) =================

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
    # Linux 或其他
    CHROME_BINARY_PATH = "/usr/bin/google-chrome"
    CHROME_DRIVER_PATH = "/usr/bin/chromedriver"

# 4. 业务文件路径
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "rfi_cn.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "rfi_cn.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_rficn.html")

# ========================================================

def is_similar(url1, url2):
    """
    比较两个 URL 的相似度 (针对 RFI 优化：忽略分类路径，只比对文章 ID/标题部分)
    """
    if not url1 or not url2:
        return False

    def get_core_id(url):
        # 1. 解析 URL 并去除末尾可能的斜杠
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        
        # 2. 尝试提取 'YYYYMMDD-标题' 结构 (RFI 文章的核心指纹)
        # 逻辑：查找路径中最后出现的 "8位数字-任意字符" 模式
        # 这能匹配 "/20260115-abc" 忽略前面的 "/cn/中国/"
        match = re.search(r'(\d{8}-.*)$', path)
        
        if match:
            # 找到了，返回类似于 "20260115-xxxx..." 的部分作为指纹
            return match.group(1)
        
        # 3. 如果没找到标准文章 ID（可能是首页或其他非文章页），则回退到比较整个路径
        return path

    # 比较两个 URL 提取出的核心指纹是否一致
    return get_core_id(url1) == get_core_id(url2)

def format_html_row(row):
    """
    today_rficn.html 专用的行格式化函数
    """
    site, title, link = row
    clickable_title = f'<a href="{link}" target="_blank">{title}</a>'
    return f"<tr><td>{site}</td><td>{clickable_title}</td></tr>\n"

def main():
    # 获取当前日期
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")
    current_year = str(current_datetime.year) # 例如 "2026"

    # ================= 1. 初始化 Selenium =================
    print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
    
    options = webdriver.ChromeOptions()
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
        # 打开 RFI 网站
        print("正在访问 RFI CN...")
        driver.get("https://www.rfi.fr/cn/")

        # ================= NEW: 处理 Didomi 隐私弹窗 =================
        try:
            print("正在检测隐私弹窗 (Didomi)...")
            # 设置显式等待，最多等待 10 秒
            wait = WebDriverWait(driver, 10)
            # Didomi 标准同意按钮 ID
            agree_button = wait.until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            agree_button.click()
            print("✅ 已点击同意隐私条款，弹窗关闭。")
            time.sleep(1) # 等待动画消失
        except TimeoutException:
            print("ℹ️ 未检测到弹窗 (可能已默认接受或无需弹窗)。")
        except Exception as e:
            print(f"⚠️ 处理弹窗时遇到非致命错误: {e}")

        # ================= 2. 滚动加载 =================
        print("开始滚动页面...")
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.5)
        print("滚动完成。")

        # ================= 3. 读取旧文件逻辑 =================
        old_file_list = glob.glob(OLD_FILE_PATTERN)
        if old_file_list:
            old_file_path = old_file_list[0]
            seven_days_ago = current_datetime - timedelta(days=30)
            
            try:
                with open(old_file_path, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    all_rows = soup.find_all('tr')
                    if len(all_rows) > 1:
                        rows = all_rows[1:]
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
        all_links = [old_link for _, _, old_link in old_content]
        
        # RFI 专用选择器
        selectors = [
            "//div[contains(@class, 'article__title')]/a",
            "//div[contains(@class, 'm-item-list-article')]//div[contains(@class, 'article__title')]/a"
        ]

        print("开始扫描标题元素...")
        raw_data_list = []

        for selector in selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for element in elements:
                    try:
                        href = element.get_attribute('href')
                        title_text = element.text.strip()

                        if not title_text:
                            try:
                                h2_elem = element.find_element(By.TAG_NAME, "h2")
                                title_text = h2_elem.text.strip()
                            except:
                                pass
                        
                        if href and title_text:
                            # 确保链接完整
                            if not href.startswith('http'):
                                href = "https://www.rfi.fr" + href
                            raw_data_list.append((href, title_text))

                    except StaleElementReferenceException:
                        continue 
                    except Exception:
                        continue
            except Exception as e:
                print(f"选择器 {selector} 处理出错: {e}")

        print(f"成功提取了 {len(raw_data_list)} 条原始数据，开始过滤...")

        # --- 步骤 C: 逻辑过滤 (针对 RFI 修改) ---
        for href, title_text in raw_data_list:
            # 1. 域名检查
            if 'rfi.fr' not in href: continue
            
            # 2. 关键词过滤
            if any(x in href for x in ['podcasts']): continue
            
            # 3. URL 格式校验 (NEW)
            # RFI 格式: .../20260115-标题...
            # 我们检查链接中是否包含 "YYYYMMDD-" 的模式 (例如 20260115-)
            # 或者简单的包含当前年份字符串 (2026)，以防止漏掉格式略有不同的文章
            is_valid_article_format = False
            
            # 检查是否包含 8位数字+横杠 (最准确)
            if re.search(r'\d{8}-', href):
                is_valid_article_format = True
            # 备用检查: 必须包含当前年份 (过滤掉 /cn/中国/ 这种纯分类页)
            elif current_year in href:
                is_valid_article_format = True
            
            if not is_valid_article_format:
                continue

            # 4. 重复检查
            is_duplicate = False
            if any(is_similar(href, old_link) for _, _, old_link in old_content):
                is_duplicate = True
            if any(is_similar(href, new_link) for _, _, new_link in new_rows):
                is_duplicate = True
            
            if not is_duplicate:
                new_rows.append([formatted_datetime, title_text, href])
                new_rows1.append(["RFI", title_text, href])
                all_links.append(href)

        print("-" * 40)
        if new_rows:
            print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条 RFI 新闻！")
        else:
            print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
        print("-" * 40)

    except Exception as e:
        print("抓取过程中出现错误:", e)

    finally:
        driver.quit()

    # ================= 5. 文件写入操作 =================
    
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(TODAY_HTML_PATH), exist_ok=True)

    # 删除旧文件
    if old_file_list and os.path.exists(old_file_list[0]):
        try:
            os.remove(old_file_list[0])
            print(f"文件 {old_file_list[0]} 已被删除。")
        except OSError as e:
            print(f"错误: {e.strerror}. 文件无法删除。")

    # 创建站点 HTML 文件 (rfi_cn.html)
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

    # 创建/更新 每日新闻总表 (today_rficn.html)
    if new_rows1:
        file_exists = os.path.isfile(TODAY_HTML_PATH)
        try:
            if file_exists:
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as file:
                    content = file.read()
                    content = content.replace("</table></body></html>", "")
                    content = content.replace("</table>\n</body>\n</html>", "")
                
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as file:
                    file.write(content)
                    for row in new_rows1:
                        file.write(format_html_row(row))
                    file.write("</table>\n</body>\n</html>")
            else:
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as file:
                    file.write("<!DOCTYPE html>\n")
                    file.write("<html>\n<head>\n<meta charset='utf-8'>\n</head>\n<body>\n")
                    file.write("<table border='1'>\n")
                    file.write("<tr><th>site</th><th>Title</th></tr>\n")
                    for row in new_rows1:
                        file.write(format_html_row(row))
                    file.write("</table>\n</body>\n</html>")
            
            with open(TODAY_HTML_PATH, 'r+', encoding='utf-8') as file:
                file.flush()
                os.fsync(file.fileno())
                
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()
