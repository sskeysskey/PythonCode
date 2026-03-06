-- 定义基础文件路径
property pythonPath : "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
property scriptFolder : "/Users/yanzhang/Coding/python_code/"

-- ==================================================
-- <<<< 定义全局连续错误计数器
-- ==================================================
property consecutiveErrors : 0

-- ==================================================
-- <<<< 脚本启动时重置计数器
-- ==================================================
set consecutiveErrors to 0

-- 设置文件夹路径
set downloadsFolder to "/private/tmp/"
set segmentFileName to "segment_"
set doneFileName to "done_"
set newsFilePath to "/Users/yanzhang/Coding/News/today_chn.txt"

-- 检查Segments文件夹中是否存在包含"segment"的txt文件
tell application "System Events"
	set segmentFileExists to false
	set filesList to files of folder downloadsFolder whose name contains segmentFileName and name extension is "txt"
	if (count of filesList) > 0 then
		set segmentFileExists to true
	end if
end tell

tell application "System Events"
	set doneFileExists to false
	set filesList to files of folder downloadsFolder whose name contains doneFileName and name extension is "txt"
	if (count of filesList) > 0 then
		set doneFileExists to true
	end if
end tell

-- 检查今天的新闻文件是否存在
tell application "System Events"
	set newsFileExists to false
	if exists file newsFilePath then
		set newsFileExists to true
	end if
end tell

if segmentFileExists then
	delay 0.1
else
	if doneFileExists then
		if newsFileExists then
			delay 0.1
		else
			set pythonScriptPath to "/Users/yanzhang/Coding/python_code/Selenium_News/Title_Read.py"
			-- 执行 Python 脚本并检查结果
			set pythonResult to ""
			try
				set pythonResult to do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 " & quoted form of pythonScriptPath
			on error errMsg number errNum
				display dialog "Python 脚本执行时发生错误：" & return & return & errMsg & return & "(错误码: " & errNum & ")" with title "脚本错误" buttons {"终止"} default button "终止"
				error number -128
			end try
			
			if pythonResult contains "USE_FALLBACK_AND_TERMINATE" then
				display dialog "未找到 today_eng.html，但检测到备用文件 today_wsjcn.html，可直接使用。" & return & return & "脚本将按要求终止。" with title "文件提示" buttons {"好的"} default button "好的"
				error "脚本根据指令正常终止。" number -128
			end if
		end if
	else
		set pythonScriptPath to "/Users/yanzhang/Coding/python_code/Selenium_News/Title_Read.py"
		-- 执行 Python 脚本并检查结果
		set pythonResult to ""
		try
			set pythonResult to do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 " & quoted form of pythonScriptPath
		on error errMsg number errNum
			display dialog "Python 脚本执行时发生错误：" & return & return & errMsg & return & "(错误码: " & errNum & ")" with title "脚本错误" buttons {"终止"} default button "终止"
			error number -128
		end try
		
		if pythonResult contains "USE_FALLBACK_AND_TERMINATE" then
			display dialog "未找到 today_eng.html，但检测到备用文件 today_wsjcn.html，可直接使用。" & return & return & "脚本将按要求终止。" with title "文件提示" buttons {"好的"} default button "好的"
			error "脚本根据指令正常终止。" number -128
		end if
	end if
end if

repeat
	set folderPath to "/tmp/"
	set fileIndex to 1
	set fileFound to false
	
	tell application "System Events"
		repeat until fileFound or fileIndex > 15
			set posixFilePath to folderPath & "segment_" & fileIndex & ".txt"
			if exists file posixFilePath then
				set fileFound to true
				exit repeat
			else
				set fileIndex to fileIndex + 1
			end if
		end repeat
		
		if fileFound then
			set loopCount to 0
			set maxLoops to 1
			repeat while loopCount < maxLoops
				set appleScriptFilePath to POSIX file posixFilePath as alias
				tell application "TextEdit"
					open appleScriptFilePath
					activate
					delay 0.2
					-- 模拟全选 Command + A
					tell application "System Events"
						key code 0 using command down
						delay 0.5
						keystroke "c" using command down
						delay 0.5
						-- Command + Q
						key code 12 using command down
						delay 0.5
					end tell
				end tell
				
				-- ==================================================
				-- 步骤 1: 准备 Prompt
				-- ==================================================
				set finalMethodType to "---按照数字标号逐行翻译成精准地道的中文，保持行数不变，只输出翻译内容即可"
				
				-- 获取当前剪贴板的内容
				set clipboardContent to the clipboard
				
				-- 在内容前后添加指定的标签 (参考 Doubao 脚本的格式，或者保持原有的 document 格式)
				-- 这里采用直接拼接的方式，确保 Doubao 能理解
				set newContent to "<document>" & clipboardContent & "</document>"
				set finalInput to newContent & finalMethodType
				set the clipboard to finalInput
				
				set successFlag to false -- 1. 设置一个成功标志位
				
				-- ==================================================
				-- 步骤 2: 调用千问进行自动化处理
				-- ==================================================
				try
					-- 2.1 激活千问标签页并发送
					my qianwen() -- ← 改动1: doubao() → qianwen()
					
					do shell script "/opt/homebrew/bin/cliclick m:852,806" -- ← 改动2: 坐标换成千问的
					
					-- 2.3 等待生成 (标题通常较短，5-8秒应该足够，根据网络调整)
					delay 6
					
					-- 2.4 运行 Qianwen_auto.py 提取网页上的回答到剪贴板
					my runPythonScript("Qianwen_auto.py", {"50"}) -- ← 改动3: Doubao_auto.py → Qianwen_auto.py
					
					-- ==================================================
					-- 步骤 3: 处理提取到的结果
					-- ==================================================
					
					-- 只要脚本没报错，就认为成功，重置错误计数
					set consecutiveErrors to 0
					
					-- 运行 Doubao_Title.py 对剪贴板中的翻译结果进行清洗/保存
					-- 如果发现内容不对也会报错
					-- 如果 Python 检测到“单行+抱歉”，会报错并输出 "FATAL_REFUSAL"
					my runPythonScript("Qianwen_Title.py", {}) -- ← 改动4: Doubao_Title.py → Qianwen_Title.py
					
					-- 如果能走到这里，说明 Python 脚本都执行成功了
					set successFlag to true -- 标记成功
				on error errMsg
					if errMsg contains "FATAL_REFUSAL" or errMsg contains "没有被正确翻译" then
						display dialog "⛔️ 程序终止：检测到千问拒绝回答或剪贴内容不正确。" -- ← 改动5: 提示文字更新
						error number -128
					end if
					
					-- 普通错误处理 (自动化失败、未找到复制按钮等)
					set consecutiveErrors to consecutiveErrors + 1
					log "Qianwen 自动化失败 (" & errMsg & ")。当前连续错误次数: " & consecutiveErrors -- ← 改动6: 日志文字更新
					
					if consecutiveErrors is greater than or equal to 2 then
						display dialog "⚠️ 警告：千问自动化已连续报错 2 次，将强制终止" -- ← 改动7: 提示文字更新
						error "API/自动化连续报错达到上限，程序强制终止。" number -128
					end if
					-- 出错后，强制刷新一下网页或者等待更久，为下一次重试做准备
					delay 2
				end try
				
				delay 0.1
				
				
				-- 逻辑修改：只有在 successFlag 为 true 时，才去检查 diff.txt 决定是否退出
				if successFlag is true then
					-- 检查 diff.txt
					set targetFile to "/tmp/diff.txt"
					if exists file targetFile then
						try
							delete file targetFile
							set loopCount to loopCount + 1
							log "行数不匹配 (diff.txt)，重试。循环次数：" & loopCount
						on error
							-- 删除失败忽略
						end try
					else
						log "执行成功且无 diff 文件。退出内部循环。"
						exit repeat -- 只有成功且没有行数差异时，才退出循环，处理下一个文件
					end if
				else
					-- 如果 successFlag 是 false (即 Python 报错了)
					set loopCount to loopCount + 1
					log "Python 脚本报错，触发重试。循环次数：" & loopCount
				end if
				
				-- 在每次迭代结束时检查循环计数
				if loopCount ≥ maxLoops then
					log "达到最大循环次数。退出内部循环。"
					exit repeat
				end if
			end repeat
			
			-- 处理完当前segment文件后，将其重命名为done文件
			try
				set oldName to name of file posixFilePath
				set newName to "done_" & text 9 thru -1 of oldName -- 假设 "segment_" 总是前8个字符
				set newPath to (container of file posixFilePath as text) & newName
				
				tell application "Finder"
					set name of file posixFilePath to newName
				end tell
				log "已处理并重命名文件：" & posixFilePath & " 到 " & newPath
			on error errMsg
				log "重命名文件 " & posixFilePath & " 时出错：" & errMsg
			end try
		else
			-- 所有分段文件处理完毕，进行写入
			my runPythonScript("Selenium_News/Title_Write.py", {})
			exit repeat
		end if
	end tell
end repeat

-- ==================================================
-- 以下为新增/移植的 Handler 函数
-- ==================================================

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

-- ← 改动8: 整个 doubao() handler 替换为从 a.scpt 移植过来的 qianwen() handler
on qianwen()
	set foundMapsTab to false
	set mapsTabIndex to 0
	tell application "Google Chrome"
		delay 0.3
		activate
		set windowList to every window
		
		-- 遍历每一个窗口
		repeat with aWindow in windowList
			set tabList to every tab of aWindow
			set tabIndex to 0
			
			-- 遍历每一个标签页
			repeat with aTab in tabList
				set tabIndex to tabIndex + 1
				set tabURL to URL of aTab
				
				if tabURL contains "qianwen.com" then
					set foundMapsTab to true
					set mapsTabIndex to tabIndex
					set index of aWindow to 1
					set active tab index of aWindow to tabIndex
					exit repeat
				end if
			end repeat
			
			if foundMapsTab then
				exit repeat
			end if
		end repeat
	end tell
	
	if foundMapsTab then
		tell application "System Events"
			key code 37 using command down -- L键: 定位地址栏
			delay 0.2
			keystroke "qianwen.com/chat"
			delay 0.5
			key code 36 -- Enter
		end tell
	else
		tell application "Google Chrome"
			activate
			delay 0.5
		end tell
		
		tell application "System Events"
			keystroke "t" using command down
			delay 0.5
			keystroke "qianwen.com/chat"
			delay 0.5
			key code 36
		end tell
	end if
	
	do shell script "/opt/homebrew/bin/cliclick m:862,839"
	
	-- 截图校验逻辑（保留原逻辑，如果你不需要截图校验可以注释掉）
	set pythonScriptPath to "/Users/yanzhang/Coding/python_code/screenshot.py"
	set imageName to "qianwen_pc.png"
	set clickValue to "false"
	set Opposite to "false"
	
	set commandString to "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
	do shell script commandString
	delay 0.5
	
	-- 截图校验逻辑（保留原逻辑，如果你不需要截图校验可以注释掉）
	set pythonScriptPath to "/Users/yanzhang/Coding/python_code/screenshot.py"
	set imageName to "qianwen_launch.png"
	set clickValue to "true"
	set Opposite to "false"
	set x_offset to "0"
	set y_offset to "-70"
	
	set commandString to "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite & " " & x_offset & " " & y_offset
	do shell script commandString
	delay 0.5
	
	my Submit()
end qianwen

-- ← 改动9: Submit() 中的 cliclick 坐标换成千问对应的
on Submit()
	-- 粘贴 + 回车
	tell application "System Events"
		keystroke "v" using {command down}
		delay 0.1
		key code 36 -- Enter
	end tell
	
	do shell script "/opt/homebrew/bin/cliclick m:862,839"
end Submit