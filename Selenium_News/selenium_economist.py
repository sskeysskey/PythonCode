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
# 引入异常处理，防止滚动后元素失效
from selenium.common.exceptions import StaleElementReferenceException

# ================= 配置区域 =================

# 1. 路径配置 (适配 Beta 版)
# Chrome Beta 浏览器程序路径 (必须指定，因为使用了 Beta 版驱动)
CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
# Chrome Beta 驱动路径
CHROME_DRIVER_PATH = "/Users/yanzhang/Downloads/backup/chromedriver_beta"

# 文件路径
FILE_PATTERN = "/Users/yanzhang/Coding/News/backup/site/economist.html"
NEW_HTML_PATH = "/Users/yanzhang/Coding/News/backup/site/economist.html"
TODAY_HTML_PATH = "/Users/yanzhang/Coding/News/today_eng.html"

# 设置超时时间
TIMEOUT = 20 

# ================= 工具函数 =================

def open_html_file(file_path):
    """打开生成的HTML文件"""
    webbrowser.open('file://' + os.path.realpath(file_path), new=2)

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
    # --- 1. 初始化 Selenium ---
    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_BINARY_PATH # 指定浏览器可执行文件位置

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

    # 检查驱动是否存在
    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    # 启动浏览器
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    
    # 设置页面加载超时
    driver.set_page_load_timeout(30)
    wait = WebDriverWait(driver, 10)

    # 初始化变量，防止 finally 中报错
    new_rows = []
    new_rows1 = []
    old_content = []
    old_file_list = glob.glob(FILE_PATTERN) # 提前获取

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
        print("正在抓取文章列表...")
        try:
            # 查找今年内的链接
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
            titles_elements = driver.find_elements(By.CSS_SELECTOR, f"a[href*='/{datetime.now().year}/']")
            formatted_datetime = datetime.now().strftime("%Y_%m_%d_%H")
            
            for title_element in titles_elements:
                href = title_element.get_attribute('href')
                # 在 headless 模式下 .text 有时为空，尝试 get_attribute('innerText')
                title_text = title_element.text.strip() or title_element.get_attribute('innerText').strip()
                
                if href and title_text:
                    if ('podcasts' not in href and "film" not in href and "cartoon" not in href and 
                        not ('letters' in href and 'editor' in href and 'Sources and acknowledgments' in href)):
                        
                        # 检查重复
                        is_old_duplicate = any(is_similar(href, old_link) for _, _, old_link in old_content)
                        is_new_duplicate = any(is_similar(href, new_link) for _, _, new_link in new_rows)
                        
                        if not is_old_duplicate and not is_new_duplicate:
                            new_rows.append([formatted_datetime, title_text, href])
                            new_rows1.append(["Economist", title_text, href])
                            # print(f"新发现: {title_text[:30]}...") 

            # ==================== 新增日志区域 ====================
            print("-" * 40)
            if new_rows:
                print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条新新闻！")
            else:
                print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
            print("-" * 40)
            # ====================================================

        except Exception as e:
            print("抓取过程中出现错误:", e)

    finally:
        # 关闭驱动
        driver.quit()

    # --- 5. 文件写入操作 ---

    # 删除旧文件
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
