#!/bin/bash

PY="/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
SEL="/Users/yanzhang/Coding/python_code/Selenium_News/Selenium_Combined.py"
TITLE="/Users/yanzhang/Coding/ScriptEditor/Title_Engine.scpt"

echo "===== [1/2] Selenium_Combined 开始 $(date '+%H:%M:%S') ====="
"$PY" "$SEL"
rc=$?

if [ $rc -ne 0 ]; then
    echo "❌ Selenium_Combined 未完全成功（退出码 $rc），跳过标题翻译"
    osascript -e 'display notification "抓取未完全成功，已跳过标题翻译" with title "自动化中止"'
    exit $rc
fi

echo "===== [2/2] Title_Engine 开始 $(date '+%H:%M:%S') ====="
osascript "$TITLE"
rc=$?

echo "===== 全部结束 $(date '+%H:%M:%S')，退出码 $rc ====="
exit $rc