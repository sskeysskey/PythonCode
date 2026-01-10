-- ==================================================
-- Trans_Selection_Doubao.scpt
-- 移植版：划词/选中文本 -> Doubao 网页版翻译 -> 结果存入剪贴板
-- ==================================================

-- 定义基础文件路径
property pythonPath : "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
property scriptFolder : "/Users/yanzhang/Coding/python_code/Modules/"
-- 注意：这里假设 screenshot.py 和 Doubao_auto.py 都在 scriptFolder 或者其父目录下
-- 根据你之前的脚本，screenshot.py 似乎在 "/Users/yanzhang/Coding/python_code/"
-- 为了兼容，我们定义一个 rootScriptFolder
property rootScriptFolder : "/Users/yanzhang/Coding/python_code/"

-- 获取当前激活应用的名称
tell application "System Events"
	set activeApp to name of first application process whose frontmost is true
end tell

-- 根据应用名称执行不同的代码
if activeApp is "Google Chrome" then
	-- 当前激活程序是 Google Chrome
	tell application "Google Chrome"
		try
			set currentTab to active tab of window 1
			set theScript to "window.getSelection().toString()"
			set selectedText to execute currentTab javascript theScript
		on error
			set selectedText to ""
		end try
	end tell
	
	if selectedText is not "" then
		set the clipboard to selectedText
		my Format()
		my TransDoubao()
	else
		-- 如果 JS 获取失败，尝试格式化剪贴板现有内容（或你可以恢复之前的 popup 逻辑）
		my Format()
		my TransDoubao()
	end if
else
	-- 当前激活程序不是 Google Chrome
	-- 保存当前剪贴板内容
	set originalClipboard to the clipboard
	
	-- 执行复制操作 (Cmd+C)
	tell application "System Events"
		keystroke "c" using {command down}
	end tell
	delay 0.5
	
	-- 获取新的剪贴板内容
	set newClipboard to the clipboard
	
	-- 比较剪贴板内容
	if newClipboard is equal to originalClipboard then
		-- 剪贴板内容相同（可能没选中文字），直接处理当前剪贴板
		my Format()
		my TransDoubao()
	else
		-- 剪贴板内容不同（复制成功），处理新内容
		my Format()
		my TransDoubao()
	end if
end if

-- ===================================================================
-- 核心处理函数
-- ===================================================================

on Format()
	-- 这里保留你原脚本的提示词
	set appendText to return & return & "——将以上内容完整翻译成地道的中文"
	set clipboardContent to the clipboard
	set clipboardContent to my trimWhitespace(clipboardContent)
	set newContent to clipboardContent & appendText
	set the clipboard to newContent
end Format

on TransDoubao()
	set foundMapsTab to false
	set mapsTabIndex to 0
	
	-- 1. 寻找或打开 Doubao
	tell application "Google Chrome"
		set windowList to every window
		repeat with aWindow in windowList
			set tabList to every tab of aWindow
			set tabIndex to 0
			repeat with aTab in tabList
				set tabIndex to tabIndex + 1
				set tabURL to URL of aTab
				if tabURL contains "doubao.com" then
					set foundMapsTab to true
					set mapsTabIndex to tabIndex
					set index of aWindow to 1
					set active tab index of aWindow to tabIndex
					exit repeat
				end if
			end repeat
			if foundMapsTab then exit repeat
		end repeat
	end tell
	
	-- 2. 导航到聊天界面
	if foundMapsTab then
		tell application "System Events"
			key code 37 using command down -- ⌘L
			delay 0.2
			keystroke "doubao.com/chat/"
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
			keystroke "doubao.com/chat/"
			delay 0.5
			key code 36
		end tell
	end if
	
	-- 激活 Chrome 窗口
	tell application "Google Chrome" to activate
	delay 0.5
	
	-- 点击页面空白处确保焦点
	do shell script "/opt/homebrew/bin/cliclick m:852,854"
	
	-- 3. 截图校验页面加载
	-- 注意：这里路径指向 rootScriptFolder (python_code/) 而不是 Modules/
	set pythonScriptPath to rootScriptFolder & "screenshot.py"
	
	-- 校验 doubao_share.png
	set imageName to "doubao_share.png"
	set clickValue to "false"
	set Opposite to "true"
	set commandString to pythonPath & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
	do shell script commandString
	delay 0.5
	
	-- 校验 doubao_launch.png 并点击输入框
	set imageName to "doubao_launch.png"
	set clickValue to "true"
	set Opposite to "false"
	set x_offset to "0"
	set y_offset to "-47"
	set commandString to pythonPath & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite & " " & x_offset & " " & y_offset
	do shell script commandString
	delay 0.5
	
	-- 4. 提交内容 (剪贴板此时已经是 Format 过的 "原文+提示词")
	my Submit()
	
	-- 5. 等待生成并复制结果
	do shell script "/opt/homebrew/bin/cliclick m:852,854"
	delay 2
	
	-- 使用 Doubao_auto.py 等待生成结束并复制
	-- 注意：Doubao_auto.py 应该也在 rootScriptFolder
	my runPythonScript("Doubao_auto.py", {})
	
	-- 6. 通知用户完成
	display notification "翻译内容已复制到剪贴板" with title "Doubao 翻译完成"
	
end TransDoubao

on Submit()
	-- 粘贴 + 回车
	tell application "System Events"
		keystroke "v" using {command down}
		delay 0.5
		key code 36 -- ↩︎
	end tell
	
	-- 移动鼠标防止遮挡
	do shell script "/opt/homebrew/bin/cliclick m:740,616"
end Submit

on trimWhitespace(theText)
	-- 清理文本前后的空白字符
	repeat while theText begins with space or theText begins with return or theText begins with tab
		set theText to text 2 thru -1 of theText
	end repeat
	repeat while theText ends with space or theText ends with return or theText ends with tab
		set theText to text 1 thru -2 of theText
	end repeat
	return theText
end trimWhitespace

-- 辅助函数：运行 Python 脚本
on runPythonScript(scriptName, args)
	-- 这里的 scriptName 假设是在 rootScriptFolder 下
	set scriptPath to rootScriptFolder & scriptName
	set argString to ""
	repeat with arg in args
		set argString to argString & " " & quoted form of arg
	end repeat
	
	try
		set pythonResult to do shell script pythonPath & " " & quoted form of scriptPath & argString
		delay 0.5
		return pythonResult
	on error errMsg number errNum
		error "Python 脚本 " & scriptName & " 执行失败：" & errMsg number errNum
	end try
end runPythonScript