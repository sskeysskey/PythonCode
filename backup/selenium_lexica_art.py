import time
import os
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# 设置浏览器驱动路径和下载路径
chrome_driver_path = '/Users/yanzhang/Downloads/backup/chromedriver'  # 替换为你的chromedriver路径
download_path = '/Users/yanzhang/Downloads'

# 初始化浏览器
options = webdriver.ChromeOptions()
prefs = {'download.default_directory': download_path}
options.add_experimental_option('prefs', prefs)
service = Service(chrome_driver_path)
driver = webdriver.Chrome(service=service, options=options)

# 访问目标网站
driver.get("https://lexica.art/")

# 等待页面加载完成
time.sleep(5)

# 找到所有符合条件的链接
links = driver.find_elements(By.XPATH, "//a[starts-with(@href, '/prompt/')]")
links = links[:5]  # 取前10个链接

for link in links:
    url = link.get_attribute('href')
    
    # 打开新页面
    driver.execute_script(f"window.open('{url}');")
    driver.switch_to.window(driver.window_handles[-1])
    
    # 等待图片加载
    try:
        img_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//img[starts-with(@src, 'https://image.lexica.art/full_webp/')]")))
        img_url = img_element.get_attribute('src')
        
        # 下载图片
        img_data = requests.get(img_url).content
        img_name = os.path.join(download_path, img_url.split('/')[-1] + ".webp")
        with open(img_name, 'wb') as handler:
            handler.write(img_data)
        
        print(f"Downloaded {img_name}")
    except Exception as e:
        print(f"Failed to download image from {url}: {e}")
    
    # 关闭当前标签页并回到主页面
    driver.close()
    driver.switch_to.window(driver.window_handles[0])

# 关闭浏览器
driver.quit()