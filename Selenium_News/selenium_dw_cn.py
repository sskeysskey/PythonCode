import re
import os
import glob
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from datetime import datetime, timedelta

# --- Selenium 组件 ---
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
import platform

# ================= 配置区域 (DW 专用) =================

USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 浏览器与驱动路径
if platform.system() == 'Darwin':
    CHROME_BINARY_PATH = "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver_beta")
elif platform.system() == 'Windows':
    CHROME_BINARY_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(CHROME_BINARY_PATH):
        CHROME_BINARY_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    CHROME_DRIVER_PATH = os.path.join(DOWNLOADS_DIR, "backup", "chromedriver.exe")
else:
    CHROME_BINARY_PATH = "/usr/bin/google-chrome"
    CHROME_DRIVER_PATH = "/usr/bin/chromedriver"

# 业务文件路径
OLD_FILE_PATTERN = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "de_cn.html")
NEW_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "backup", "site", "de_cn.html")
TODAY_HTML_PATH = os.path.join(BASE_CODING_DIR, "News", "today_dwcn.html")

# ========================================================

def is_similar(url1, url2):
    if not url1 or not url2: return False
    parsed_url1 = urlparse(url1)
    parsed_url2 = urlparse(url2)
    return f"{parsed_url1.scheme}://{parsed_url1.netloc}{parsed_url1.path}" == \
           f"{parsed_url2.scheme}://{parsed_url2.netloc}{parsed_url2.path}"

def format_html_row(row):
    site, title, link = row
    clickable_title = f'<a href="{link}" target="_blank">{title}</a>'
    return f"<tr><td>{site}</td><td>{clickable_title}</td></tr>\n"

def main():
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y_%m_%d_%H")

    # ================= 1. 初始化 Selenium =================
    print(f"正在初始化 Chrome 驱动 (OS: {platform.system()})...")
    
    options = webdriver.ChromeOptions()
    if os.path.exists(CHROME_BINARY_PATH):
        options.binary_location = CHROME_BINARY_PATH
    
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    options.add_argument(f'user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.page_load_strategy = 'eager'

    if not os.path.exists(CHROME_DRIVER_PATH):
        print(f"错误：未找到驱动文件: {CHROME_DRIVER_PATH}")
        return

    service = Service(executable_path=CHROME_DRIVER_PATH)
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Selenium 启动失败: {e}")
        return

    new_rows = []
    new_rows1 = []
    old_content = []

    try:
        print("正在访问 DW CN...")
        driver.get("https://www.dw.com/zh/")

        # ================= 处理 Privacy 弹窗 =================
        try:
            wait = WebDriverWait(driver, 5)
            # 查找并点击同意按钮
            agree_xpath = "//button[contains(., '同意')] | //button[contains(., 'Accept')]"
            agree_button = wait.until(EC.element_to_be_clickable((By.XPATH, agree_xpath)))
            agree_button.click()
            print("✅ 已点击同意隐私条款。")
            time.sleep(1)
        except:
            print("ℹ️ 未检测到弹窗或自动跳过。")

        # ================= 2. 深度滚动 (关键修改) =================
        print("开始深度滚动页面 (4次)...")
        # 增加滚动次数和等待时间，确保 React 加载出下方内容
        for i in range(4): 
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.5) # 这里的等待非常重要，给网页渲染时间
        print("滚动完成。")

        # ================= 3. 读取旧文件 =================
        old_file_list = glob.glob(OLD_FILE_PATTERN)
        if old_file_list:
            try:
                with open(old_file_list[0], 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    all_rows = soup.find_all('tr')
                    if len(all_rows) > 1:
                        for row in all_rows[1:]:
                            cols = row.find_all('td')
                            if len(cols) >= 2:
                                date_str = cols[0].text.strip()
                                try:
                                    if datetime.strptime(date_str, '%Y_%m_%d_%H') >= (current_datetime - timedelta(days=10)):
                                        t = cols[1].text.strip()
                                        l = cols[1].find('a')['href'] if cols[1].find('a') else None
                                        old_content.append([date_str, t, l])
                                except: continue
            except Exception as e:
                print(f"读取旧文件警告: {e}")

        # ================= 4. 抓取与提取 (增强版) =================
        # DW 链接特征：包含 /a- 且后面跟数字
        selectors = ["//a[contains(@href, '/a-')]"]

        print("开始扫描元素...")
        raw_data_list = []
        
        # 获取所有符合条件的 A 标签
        elements = driver.find_elements(By.XPATH, selectors[0])
        print(f"页面上共发现 {len(elements)} 个潜在链接元素，开始解析...")

        for element in elements:
            try:
                href = element.get_attribute('href')
                
                # --- 增强文本提取逻辑 ---
                # 1. 优先获取可见文本
                title_text = element.text.strip()
                
                # 2. 如果可见文本为空 (可能不在视口或被隐藏)，尝试获取 textContent (包含隐藏文本)
                if not title_text:
                    title_text = element.get_attribute("textContent").strip()
                
                # 3. 如果还是为空，尝试从 title 属性获取
                if not title_text:
                    title_text = element.get_attribute("title")
                
                # 4. 如果还是为空，尝试查找子元素中的 h2/h3/span
                if not title_text:
                    try:
                        inner = element.find_element(By.XPATH, ".//h2 | .//h3 | .//span")
                        title_text = inner.get_attribute("textContent").strip()
                    except:
                        pass

                if href and title_text:
                    if not href.startswith('http'):
                        href = "https://www.dw.com" + href
                    raw_data_list.append((href, title_text))

            except StaleElementReferenceException:
                continue 
            except Exception:
                continue

        print(f"解析完成，获得 {len(raw_data_list)} 条原始数据，开始逻辑过滤...")

        # --- 步骤 C: 逻辑过滤 (增强屏蔽版) ---
        seen_links = set()
        
        # 🚫 定义屏蔽黑名单 (标题或链接中包含这些词则丢弃)
        BLOCK_KEYWORDS = [
            # 标题关键词
            "订阅新闻", "数据保护", "责任声明", "无障碍内容声明", "隐私政策", 
            "关于我们", "德广联", "DW 简介", "版本说明", "联系我们",
            # URL 关键词
            "legal-notice", "accessibility-statement", "data-protection", 
            "newsletter-registration", "about-dw", "contact"
        ]

        for href, title_text in raw_data_list:
            if 'dw.com' not in href: continue
            
            # 1. 基础非文章过滤
            if any(x in href for x in ['/av-', '/media-center', 'search?', 'tv-programs']): continue
            
            # 严格校验 DW 文章 ID (必须包含 /a-数字)
            if not re.search(r'/a-\d+', href): continue

            # 3. 🚫 黑名单过滤 (关键新增)
            should_block = False
            for kw in BLOCK_KEYWORDS:
                if kw in title_text or kw in href:
                    should_block = True
                    break
            if should_block:
                continue

            # 去重键
            link_key = href.split('?')[0] # 忽略参数
            
            if link_key in seen_links: continue
            seen_links.add(link_key)

            # 历史去重
            is_duplicate = False
            if any(is_similar(href, old_link) for _, _, old_link in old_content):
                is_duplicate = True
            
            # 检查本次列表 (防止重复添加)
            if any(is_similar(href, new_link) for _, _, new_link in new_rows):
                is_duplicate = True

            if not is_duplicate:
                clean_title = title_text.replace('\n', ' ').strip()
                # 再次检查标题长度，过滤掉无效短文本
                if len(clean_title) > 2: 
                    new_rows.append([formatted_datetime, clean_title, href])
                    new_rows1.append(["DW", clean_title, href])

        print("-" * 40)
        if new_rows:
            print(f"✅ 统计报告: 本次共抓取到 {len(new_rows)} 条 DW 新闻！")
        else:
            print("⚠️ 统计报告: 本次未发现新内容 (0 条)。")
            print("  (调试提示: 如果数量少，可能是页面加载慢，请尝试增加滚动次数)")
        print("-" * 40)

    except Exception as e:
        print("抓取错误:", e)

    finally:
        driver.quit()

    # ================= 5. 文件写入 =================
    os.makedirs(os.path.dirname(NEW_HTML_PATH), exist_ok=True)
    
    # 写入站点文件
    try:
        with open(NEW_HTML_PATH, 'w', encoding='utf-8') as html_file:
            html_file.write("<html><body><table border='1'>\n")
            html_file.write("<tr><th>Date</th><th>Title</th></tr>\n")
            for row in new_rows:
                html_file.write(f"<tr><td>{row[0]}</td><td><a href='{row[2]}' target='_blank'>{row[1]}</a></td></tr>\n")
            for row in old_content:
                l = row[2] if row[2] else "#"
                html_file.write(f"<tr><td>{row[0]}</td><td><a href='{l}' target='_blank'>{row[1]}</a></td></tr>\n")
            html_file.write("</table></body></html>")
        print(f"已更新站点文件: {NEW_HTML_PATH}")
    except Exception as e:
        print(f"写入 Site HTML 出错: {e}")

    # 写入每日总表
    if new_rows1:
        try:
            mode = 'r+' if os.path.exists(TODAY_HTML_PATH) else 'w'
            if mode == 'r+':
                with open(TODAY_HTML_PATH, 'r', encoding='utf-8') as f:
                    c = f.read().replace("</table></body></html>", "").replace("</table>\n</body>\n</html>", "")
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as f:
                    f.write(c)
                    for r in new_rows1: f.write(format_html_row(r))
                    f.write("</table>\n</body>\n</html>")
            else:
                with open(TODAY_HTML_PATH, 'w', encoding='utf-8') as f:
                    f.write("<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><table border='1'>\n")
                    f.write("<tr><th>site</th><th>Title</th></tr>\n")
                    for r in new_rows1: f.write(format_html_row(r))
                    f.write("</table>\n</body>\n</html>")
            print(f"已追加到总表: {TODAY_HTML_PATH}")
        except Exception as e:
            print(f"写入总表出错: {e}")

if __name__ == "__main__":
    main()
