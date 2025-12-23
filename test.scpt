property pythonPath : "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
property scriptFolder : "/Users/yanzhang/Coding/python_code/"

-- ==================================================
-- <<<< 新增修改 1: 定义全局连续错误计数器
-- ==================================================
property consecutiveErrors : 0

-- ==================================================
-- <<<< 新增修改 2: 脚本启动时重置计数器
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
			set maxLoops to 3
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
				
				set finalMethodType to "---按照数字标号逐行翻译成精准地道的简体中文，保持行数不变，记住：只输出翻译内容，去除引号和解释文字。"
				
				-- 获取当前剪贴板的内容
				set clipboardContent to the clipboard
				
				-- 在内容前后添加指定的标签
				set newContent to "<document>" & clipboardContent & "</document>"
				set clipboardContent to newContent & finalMethodType
				
				set pythonScriptPath to "/Users/yanzhang/Coding/python_code/Modules/API_Poe_Close.py"
				set model to "Claude-Sonnet-3.5"
				
				-- 关键修正：对剪贴板内容做 shell 安全转义
				set quotedText to quoted form of clipboardContent
				set quotedModel to quoted form of model
				set quotedPython to "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
				set quotedScript to quoted form of pythonScriptPath
				
				-- 将文本作为单独参数传给 Python
				set commandString to quotedPython & " " & quotedScript & " " & quotedModel & " " & quotedText
				set pythonResult to do shell script commandString
				
				if pythonResult contains "POE_RESPONSE_COMPLETE" then
					-- API 调用成功：重置连续错误计数器
					set consecutiveErrors to 0
					
					set pythonScriptPath to "/Users/yanzhang/Coding/python_code/Poe_Title.py"
					-- 执行 Python 脚本
					do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 " & quoted form of pythonScriptPath
				else
					-- API 调用失败（返回 ERROR 或其他）：计数器加 1
					set consecutiveErrors to consecutiveErrors + 1
					log "API 调用失败。当前连续错误次数: " & consecutiveErrors
					
					-- 检查是否达到 5 次上限
					if consecutiveErrors is greater than or equal to 5 then
						-- 显示弹窗并强制退出
						display dialog "⚠️ 警告：API 已连续报错 5 次。" & return & return & "为防止系统崩溃或账号封禁，程序将强制终止。" buttons {"终止"} default button "终止" with icon stop
						error "API 连续报错达到上限，程序强制终止。" number -128
					end if
					
					-- 注意：如果 API 失败，原来的逻辑会继续向下执行，检查 diff.txt。
					-- 由于 Poe_Title.py 没跑，diff.txt 可能不存在，导致该文件被标记为 done 从而跳过。
					-- 但至少现在的逻辑保证了如果连续 5 个文件都失败，程序就会彻底停止。
				end if
				delay 0.1
				
				set targetFile to "/tmp/diff.txt"
				if exists file targetFile then
					try
						delete file targetFile
						set loopCount to loopCount + 1
						log "文件 " & targetFile & " 已成功删除。循环次数：" & loopCount
					on error errMsg
						log "删除文件 " & targetFile & " 时出错：" & errMsg & "。循环次数：" & loopCount
						-- 即使删除失败，也增加循环计数
					end try
				else
					log "文件 " & targetFile & " 不存在。退出内部循环。循环次数：" & loopCount
					exit repeat
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
			set pythonScriptPath to "/Users/yanzhang/Coding/python_code/Selenium_News/Title_Write.py"
			-- 执行 Python 脚本
			do shell script "/Library/Frameworks/Python.framework/Versions/Current/bin/python3 " & quoted form of pythonScriptPath
			exit repeat
		end if
	end tell
end repeat
