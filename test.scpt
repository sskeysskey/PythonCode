-- 定义基础文件路径
property pythonPath : "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
property scriptFolder : "/Users/yanzhang/Coding/python_code/"

-- <<<< 新增修改 1: 定义一个全局属性来记录连续错误次数
property consecutiveErrors : 0

-- 【新增开关】是否开启英文总结功能
-- true = 开启 (双语模式)
-- false = 关闭 (仅中文模式，节省点数)
property enableEnglishSummary : false 

on run argv
	-- ==================================================
	-- <<<< 新增修改 2: 每次脚本启动时，重置错误计数器
	-- ==================================================
	set consecutiveErrors to 0
	
	if (count of argv) > 2 then
		set methodType to item 1 of argv
		if methodType is equal to "" then
			set methodType to "----请用中文详细全面的总结这篇文章（保留所有数据）"
		end if
		
		-- ==================================================
		-- 新增修改 1: 添加一个新的提示语变量 methodType2
		-- ==================================================
		set methodType2 to "----请用中文完整翻译这篇文章"
		
		-- 新增：读取并校验第二个参数
		set poeMode to item 2 of argv as text
		set shouldRepeat to item 3 of argv as boolean
	else
		-- 处理参数不足的情况
		error "参数不足，需要至少三个参数。"
	end if
	
	if shouldRepeat then
		repeat
			-- ==================================================
			-- 新增修改 2: 在调用 NewsOperation 时传入 methodType2
			-- ==================================================
			set stopNow to my NewsOperation(methodType, poeMode, methodType2)
			if stopNow then exit repeat
		end repeat
	else
		-- ==================================================
		-- 新增修改 3: 在调用 NewsOperation 时传入 methodType2
		-- ==================================================
		-- 当第三个参数为 false 时，执行新的交互式循环模式
		repeat
			-- 执行一次新闻处理操作
			set stopNow to my NewsOperation(methodType, poeMode, methodType2)
			
			-- 如果 NewsOperation 返回 true，说明没有可处理的新闻了，直接退出循环
			if stopNow then
				exit repeat
			end if
			
			-- 如果成功处理了一个页面 (stopNow is false)，则弹窗询问用户是否继续
			set userResponse to display dialog "已成功处理一个页面。" & return & "是否继续处理下一个？" buttons {"终止", "继续"} default button "继续" cancel button "终止"
			
			-- 如果用户选择“终止”或关闭了对话框，则退出循环
			if button returned of userResponse is "终止" then
				exit repeat
			end if
			
			-- 如果用户选择“继续”，循环会自然进入下一次迭代
		end repeat
	end if
end run

-- ==================================================
-- 新增修改 4: 修改 NewsOperation 的定义，使其可以接收 methodType2
-- ==================================================
on NewsOperation(methodType, poeMode, methodType2)
	-- 定义一个列表包含需要检查的网站
	set targetWebsites to {"nytimes.com", "nikkei.com", "bloomberg.com", "technologyreview.com", "economist.com", "hbr.org", "ft.com", "wsj.com", "reuters.com", "washingtonpost.com", "asia.nikkei.com"}
	
	-- 定义一个变量来保存找到的网站名称
	set foundWebsiteName to ""
	-- 定义一个变量来保存找到的标签页的ID
	set foundTabId to -1
	set containsTargetWebsite to false
	set currentTabURL to ""
	
	tell application "Google Chrome"
		activate
		delay 0.2
		set tabList to every tab of front window
		
		-- 遍历所有标签页
		repeat with i from 1 to the count of tabList
			set tabURL to URL of item i of tabList
			-- 检查URL是否包含目标网站之一
			repeat with website in targetWebsites
				if tabURL contains website then
					-- 提取网站顶级域名的最后三个字符
					set tld to text -3 thru -1 of website
					set pos to offset of tld in tabURL
					if pos ≠ 0 then
						set domainLength to length of website
						set startOfPostDomain to pos + domainLength - 3
						if length of tabURL ≥ startOfPostDomain + 7 then -- 检查.com后面至少还有两个字符
							set currentTabURL to tabURL
							set containsTargetWebsite to true
							set foundWebsiteName to website
							set active tab index of front window to i -- 激活找到的标签页
							exit repeat
						end if
					end if
				end if
			end repeat
			if containsTargetWebsite then exit repeat
		end repeat
	end tell
	
	if containsTargetWebsite then
		my handlename(foundWebsiteName, currentTabURL)
		set the clipboard to currentTabURL
		
		if currentTabURL contains "www.wsj.com/video/" then
			tell application "System Events"
				key code 13 using command down
			end tell
			return false -- 直接结束本轮循环
		end if
		
		if currentTabURL contains "ft.com" or currentTabURL contains "technologyreview.com" or currentTabURL contains "economist.com" or currentTabURL contains "www.wsj.com" or currentTabURL contains "reuters.com" or currentTabURL contains "washingtonpost.com" or currentTabURL contains "asia.nikkei.com" or currentTabURL contains "bloomberg.com" or currentTabURL contains "nytimes.com" then
			if currentTabURL contains "reuters.com/pictures/" then
				my Scroll(15)
				delay 1
			else if currentTabURL contains "wsj.com" then
				my Scroll(2)
			else
				my Scroll(4)
			end if
			delay 0.2
			
			if currentTabURL contains "ft.com" then
				my OperationForFT()
			else
				my Operation()
			end if
			delay 0.2
			
			my runPythonScript("Article_Copier.py", {currentTabURL})
			my runPythonScript("Clipboard_count_news.py", {})
			set filePathsuperlong to "/tmp/superlongarticle.txt"
			set filePathlong to "/tmp/longarticle.txt"
			set filePathshort to "/tmp/shortarticle.txt"
			set CopyFailurePath to "/Users/yanzhang/Coding/News/copy_failure.txt"
			
			set finalMethodType to methodType
			set finalPoeMode to poeMode
			
			-- 使用System Events来检查文件是否存在
			tell application "System Events"
				if exists file filePathshort then
					delete file filePathshort
					
					-- 因为是短文章，所以我们将最终提示语改为翻译
					set finalMethodType to methodType2
					-- ==================================================
					-- 新增修改 2: 如果是短文章，强制使用 "cheap" 模式 (Haiku)
					-- ==================================================
					set finalPoeMode to "cheap"
					set model to my API_Model(finalPoeMode)
				else if exists file filePathlong then
					delete file filePathlong
					-- 如果只有 longarticle.txt 存在，执行Poe导航
					set model to my API_Model(poeMode)
				else if exists file filePathsuperlong then
					delete file filePathsuperlong
					set finalPoeMode to "cheap"
					set model to my API_Model(finalPoeMode)
				else
					try
						-- 记录超长文章的URL，此部分逻辑保留
						do shell script "printf '%s\\n\\n' " & quoted form of currentTabURL & " >> " & quoted form of CopyFailurePath
					on error errMsg
						--如果写入文件失败，可以显示一个对话框提示错误
						display dialog "无法将URL写入短文章日志：" & return & errMsg buttons {"好的"} default button "好的"
					end try
					key code 13 using command down
					return false -- 直接结束本轮循环
				end if
			end tell
			
			-- ==================================================
			-- 步骤 A: 在格式化成中文Prompt之前，先保存原始文章内容到变量
			-- ==================================================
			set rawArticleContent to the clipboard
			
			-- 1. 准备中文 Prompt
			my Format(finalMethodType)
			set clipboardContent to the clipboard
			
			-- 2. 调用 API 生成中文
			set pythonResult to my runPythonScript("Modules/API_Poe_Close.py", {model, clipboardContent})
			
			-- 逻辑修改：只有中文成功，才进行英文；只有全部成功，才关闭 Tab
			
			if pythonResult contains "POE_RESPONSE_COMPLETE" then
				-- 【中文成功】
				
				-- 3. 保存中文结果 (Poe_News.py 已修改为不自动关闭 Tab)
				my runPythonScript("Poe_News.py", {currentTabURL})
				
				-- ==================================================
				-- 逻辑分支：检查是否开启了英文总结开关
				-- ==================================================
				if enableEnglishSummary is true then
					-- >>>>> 分支 1: 开启了英文总结 (双语模式) <<<<<
					
					set englishMethodType to "----Please summarize this article in English detailedly (retain key data)."
					set englishInput to "<document>" & rawArticleContent & "</document>" & englishMethodType
					
					-- 4. 调用 API 生成英文
					set pythonResultEnglish to my runPythonScript("Modules/API_Poe_Close.py", {model, englishInput})
					
					if pythonResultEnglish contains "POE_RESPONSE_COMPLETE" then
						-- 【英文也成功】
						set consecutiveErrors to 0 -- 重置计数器
						my runPythonScript("Append_English_News.py", {}) -- 保存英文
						
						-- 关闭标签页
						tell application "Google Chrome"
							close active tab of front window
						end tell
						delay 0.5
						
					else
						-- 【英文失败】
						set consecutiveErrors to consecutiveErrors + 1
						log "中文成功，但英文 API 失败。累计错误: " & consecutiveErrors
						
						-- 检查阈值
						if consecutiveErrors is greater than or equal to 5 then
							display dialog "⚠️ 警告：API (英文阶段) 已连续报错 5 次。" & return & return & "程序将强制终止。" buttons {"终止"} default button "终止" with icon stop
							error "API 连续报错达到上限，程序强制终止。"
						end if
						-- 注意：失败时不关闭标签页，保留现场
					end if
					
				else
					-- >>>>> 分支 2: 关闭了英文总结 (省钱模式) <<<<<
					
					-- 既然中文已经成功，且用户不需要英文，那么本次任务算作圆满成功
					set consecutiveErrors to 0 -- 重置计数器
					
					-- 直接关闭标签页
					tell application "Google Chrome"
						close active tab of front window
					end tell
					delay 0.5
					
					-- log "已跳过英文总结，仅处理中文"
				end if
				
			else
				-- 中文失败！计数器加 1
				set consecutiveErrors to consecutiveErrors + 1
				log "中文 API 失败。累计错误: " & consecutiveErrors
				
				-- 检查是否达到阈值 (5次)
				if consecutiveErrors is greater than or equal to 5 then
					display dialog "⚠️ 警告：API (中文阶段) 已连续报错 5 次。" & return & return & "程序将强制终止。" buttons {"终止"} default button "终止" with icon stop
					error "API 连续报错达到上限，程序强制终止。"
				end if
			end if
			
		else if currentTabURL contains "cn.wsj.com" then
			my Operation()
			my runPythonScript("Article_Copier.py", {currentTabURL})
			set myMessage to "等待下载图片...."
			do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 /Users/yanzhang/Coding/python_code/Modules/notification.py " & quoted form of myMessage & " -d 5000 --bg 'blue' --fg white"
			my runPythonScript("CN_copy_News.py", {currentTabURL})
			delay 1
		end if
		
		return false
	else
		-- 如果没有找到任何目标网站，显示弹窗
		tell application "Google Chrome"
			set currentURL to URL of active tab of front window
		end tell
		
		--if currentURL contains "Claude-3.5-Sonnet" then
		--my runPythonScript("screenshot.py", {"poe_recall.png", "true", "false"})
		--end if
		set myMessage to "没有可供总结的新闻页面了"
		do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 /Users/yanzhang/Coding/python_code/Modules/notification.py " & quoted form of myMessage & " -d 2000 --bg 'green' --fg white"
		return true
	end if
end NewsOperation

on API_Model(poeMode)
	if poeMode is "cheap" then
		set model to "Claude-Haiku-3.5"
	else
		set model to "Claude-Sonnet-3.5"
		--set model to "Claude-Haiku-4.5"
	end if
	return (model)
end API_Model

on Scroll(scrollCount)
	-- 确保 scrollCount 是一个整数，如果不是，可以添加错误处理或转换
	if class of scrollCount is not integer then
		-- 可以选择报错或者使用一个默认值
		log "错误：Scroll 函数需要一个整数参数。"
		set scrollCount to 4 -- 设置一个默认值以防出错
	end if
	
	-- 执行 cliclick 命令
	do shell script "/opt/homebrew/bin/cliclick m:672,457"
	
	-- 构建 Python 命令字符串
	-- 注意：我们将 scrollCount 变量的值直接插入到 Python 的 range() 函数中
	set pythonScript to "import pyautogui
import time
for _ in range(" & scrollCount & "):
    pyautogui.scroll(-30)
    time.sleep(0.5)
"
	-- 执行 Python 脚本
	-- 使用 'quoted form of' 来确保 pythonScript 字符串被正确传递给 shell
	do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -c " & quoted form of pythonScript
end Scroll

-- 保留原来的Operation函数，但不执行Clipboard_removal.py
on Operation()
	tell application "System Events"
		delay 0.5
		key code 7 using {option down} -- 'x' key with option
		delay 0.5
	end tell
end Operation

-- 新增一个专门处理FT网站的Operation函数
on OperationForFT()
	tell application "System Events"
		delay 0.5
		key code 7 using {option down} -- 'x' key with option
		delay 0.5
		my runPythonScript("Clipboard_removal.py", {})
	end tell
end OperationForFT

on handlename(foundWebsiteName, currentTabURL)
	-- 处理网站名称并写入文件
	set AppleScript's text item delimiters to "."
	set siteName to first text item of foundWebsiteName
	set AppleScript's text item delimiters to ""
	
	-- 写入到/tmp/website.txt文件
	set filePath to "/tmp/segment.txt"
	do shell script "echo " & quoted form of siteName & " > " & quoted form of filePath
	
	set sitePath to "/tmp/site.txt"
	do shell script "echo " & quoted form of currentTabURL & " > " & quoted form of sitePath
end handlename

on runPythonScript(scriptName, args)
	set scriptPath to scriptFolder & scriptName
	set argString to ""
	repeat with arg in args
		set argString to argString & " " & quoted form of arg
	end repeat
	set pythonResult to do shell script pythonPath & " " & quoted form of scriptPath & argString
	delay 0.5
	return pythonResult
end runPythonScript

on Format(finalMethodType)
	-- 获取当前剪贴板的内容
	set clipboardContent to the clipboard
	
	-- 在内容前后添加指定的标签
	set newContent to "<document>" & clipboardContent & "</document>"
	
	set clipboardContent to newContent & finalMethodType
	set the clipboard to clipboardContent
end Format
