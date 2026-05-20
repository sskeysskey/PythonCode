-- 定义 Python 解释器路径，方便复用
set pythonBin to "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
-- 定义停止触发文件的路径（桌面上的 stop_scpt.txt）
set stopFilePath to POSIX path of (path to desktop) & "stop_scpt.txt"

repeat
	try
		-- ==========================================
		-- 0. 检查是否存在手动停止的触发文件
		-- ==========================================
		try
			do shell script "test -e " & quoted form of stopFilePath
			-- 如果上一句没报错，说明文件存在，执行停止逻辑
			do shell script "rm " & quoted form of stopFilePath -- 清理掉这个触发文件
			display notification "检测到桌面的 stop_scpt.txt，脚本已安全停止。" with title "自动化已手动停止"
			exit repeat
		end try
		delay 0.5
		
		-- ==========================================
		-- 1. 执行 read.py
		-- ==========================================
		# 默认：只扫第一个可用 channel，Drama 取末尾 5 条
		--python read.py
		
		# 想改成末尾 10 条
		--python read.py --drama-last-n 10
		
		# 想让 Drama 也扫全部
		--python read.py --drama-last-n 0
		
		# 扫所有 channel（Drama 依旧每个 channel 只取末尾 N 条）
		--python read.py --all-channels
		
		set pythonScriptPath to "/Users/yanzhang/Coding/python_code/OVideo/read.py"
		set readResult to do shell script pythonBin & " " & quoted form of pythonScriptPath
		
		-- 修改后的代码
		--set pythonScriptPath to "/Users/yanzhang/Coding/python_code/OVideo/read.py"
		-- 在路径后面拼接空格和参数
		--set cmd to pythonBin & " " & quoted form of pythonScriptPath & " --all-channels"
		--set readResult to do shell script cmd
		
		-- 检查 read.py 的输出，如果全部处理完毕，则退出循环
		if readResult contains "所有视频链接都已处理完毕" then
			display notification "所有链接已处理完毕，自动化结束。" with title "自动化完成"
			exit repeat
		end if
		delay 0.5
		
		-- ==========================================
		-- 2. 激活 Downie 4
		-- ==========================================
		tell application "/Applications/Downie 4.app"
			activate
		end tell
		
		tell application "System Events"
			tell process "Downie 4"
				set frontmost to true
			end tell
		end tell
		delay 0.5
		
		-- ==========================================
		-- 3. 执行截图点击流程 (screenshot.py)
		-- ==========================================
		set pythonScriptPath to "/Users/yanzhang/Coding/python_code/screenshot.py"
		set Opposite to "false"
		
		-- 3.0 检查剪贴板：是否包含 xb6v.com
		set isXb6v to false
		try
			set clipContent to (the clipboard as text)
			if clipContent contains "xb6v.com" then
				set isXb6v to true
				log "检测到剪贴板包含 xb6v.com，downie_add 后将直接跳到 downie_more 步骤。"
			end if
		on error clipErr
			log "读取剪贴板失败: " & clipErr
		end try
		
		-- 截图 1: downie_add.png
		set imageName to "downie_add.png"
		set clickValue to "true"
		set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
		if cmdResult contains "TIMEOUT" then exit repeat
		delay 0.5
		
		-- ==========================================
		-- 3.2 同时扫描 downie_addselect.png 和 downie_404.png
		-- （xb6v.com 分支整体跳过此检测与 select/none/Tab 流程）
		-- ==========================================
		set skipNormalFlow to false  -- 控制 more.png 之后的流程是否执行（仅 404 时置 true）
		
		if isXb6v then
			log "xb6v.com 简化流程：跳过 addselect/404 检测与选择步骤，直接进入 downie_more.png。"
		else
			set imageName to "downie_addselect.png,downie_404.png"
			set clickValue to "false"
			-- 参数: scroll=false, x_offset=0, y_offset=0, nth_match=1, timeout=3500
			set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite & " false 0 0 1 3500"
			
			if cmdResult contains "FOUND_IMAGE:downie_404.png" then
				-- -------- 404 分支 --------
				log "检测到 downie_404.png，执行 Cmd+W 并调用 b.py 将当前 URL 拉黑。"
				
				-- 1) 关闭当前的 404 子窗口
				tell application "System Events"
					keystroke "w" using command down
				end tell
				delay 0.5
				
				-- 模拟鼠标移动
				do shell script "/opt/homebrew/bin/cliclick m:187,504"
				delay 0.5
				
				-- 2) 调用 404_move.py
				try
					set bPyPath to "/Users/yanzhang/Coding/python_code/OVideo/404_move.py"
					set bResult to do shell script pythonBin & " " & quoted form of bPyPath
					log "404_move.py 输出: " & bResult
				on error bErr
					log "404_move.py 执行失败: " & bErr
				end try
				
				-- 跳过后续的 more/savemeta/savejson/write/close
				set skipNormalFlow to true
			else
				-- 15 秒内是否找到了 addselect
				if cmdResult does not contain "TIMEOUT" then
					delay 0.5
					
					set imageName to "downie_select.png"
					set clickValue to "true"
					set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
					if cmdResult contains "TIMEOUT" then exit repeat
					delay 0.5
					
					set imageName to "downie_none.png"
					set clickValue to "true"
					set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
					if cmdResult contains "TIMEOUT" then exit repeat
					delay 0.5
					
					tell application "System Events"
						key code 48 -- Tab
						delay 0.5
						key code 125 -- Down Arrow
						delay 0.5
						key code 49 -- Space
						delay 0.5
					end tell
					
					set imageName to "downie_addselect.png"
					set clickValue to "true"
					set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
					if cmdResult contains "TIMEOUT" then exit repeat
					delay 1
				else
					log "15秒内未出现 downie_addselect.png，跳过选择步骤。"
				end if
			end if
		end if
		
		-- ==========================================
		-- more.png 及以后的流程（xb6v.com 与 普通无 404 分支 共用）
		-- ==========================================
		if not skipNormalFlow then
			-- 截图 4: downie_more.png
			set imageName to "downie_more.png"
			set clickValue to "true"
			set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
			if cmdResult contains "TIMEOUT" then exit repeat
			delay 0.5
			
			-- 截图 5: downie_savemeta.png
			set imageName to "downie_savemeta.png"
			set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
			if cmdResult contains "TIMEOUT" then exit repeat
			delay 0.5
			
			-- 截图 6: downie_savejson.png
			set imageName to "downie_savejson.png"
			set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
			if cmdResult contains "TIMEOUT" then exit repeat
			delay 0.5
			
			-- ==========================================
			-- 4. 执行 write.py
			-- ==========================================
			set pythonScriptPath to "/Users/yanzhang/Coding/python_code/OVideo/write.py"
			do shell script pythonBin & " " & quoted form of pythonScriptPath
			delay 0.5
			
			-- ==========================================
			-- 5. 关闭操作 (screenshot.py)
			-- ==========================================
			set pythonScriptPath to "/Users/yanzhang/Coding/python_code/screenshot.py"
			set imageName to "downie_close.png"
			set clickValue to "true"
			
			set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite
			if cmdResult contains "TIMEOUT" then exit repeat
			delay 1
			
			-- 内层循环：清理残留的 close 按钮
			repeat
				set cmdResult to do shell script pythonBin & " " & quoted form of pythonScriptPath & " " & quoted form of imageName & " " & clickValue & " " & Opposite & " false 0 0 1 1"
				if cmdResult contains "TIMEOUT" then
					log "close 按钮已消失，继续下一轮循环。"
					exit repeat
				end if
				delay 0.5
			end repeat
		end if
	on error errMsg
		-- 如果任何 shell script 返回非 0 状态（例如 write.py 报错，或者找不到文件等），都会跳到这里
		display notification "发生异常，自动化已停止: " & errMsg with title "自动化异常"
		exit repeat
	end try
end repeat