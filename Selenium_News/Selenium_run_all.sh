#!/bin/bash

PY="/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
SEL="/Users/yanzhang/Coding/python_code/Selenium_News/Selenium_Combined.py"
TITLE="/Users/yanzhang/Coding/ScriptEditor/Title_Engine.scpt"
KARING="/Users/yanzhang/Coding/ScriptEditor/Karing_Shift.scpt"

# 运行 Karing_Shift；失败不中断主流程
run_karing() {
    local stage="$1"
    echo "===== [Karing] $stage 开始 $(date '+%H:%M:%S') ====="
    if osascript "$KARING"; then
        echo "✅ Karing 切换完成（$stage）"
    else
        echo "⚠️ Karing 切换失败（$stage），继续执行"
        osascript -e "display notification \"Karing 切换失败（$stage）\" with title \"Karing\""
    fi
}

# ===== 0. 前置：抓取前先运行 Karing_Shift =====
run_karing "前置"

# ===== 1. Selenium_Combined =====
echo "===== [1/2] Selenium_Combined 开始 $(date '+%H:%M:%S') ====="
"$PY" "$SEL"
rc=$?

if [ $rc -ne 0 ]; then
    echo "❌ Selenium_Combined 未完全成功（退出码 $rc），跳过标题翻译"
    osascript -e 'display notification "抓取未完全成功，已跳过标题翻译" with title "自动化中止"'
    # 即使中止，也恢复 Karing 状态
    run_karing "收尾"
    exit $rc
fi

# ===== 2. Title_Engine =====
echo "===== [2/2] Title_Engine 开始 $(date '+%H:%M:%S') ====="
osascript "$TITLE"
rc=$?

# ===== 3. 收尾：Title_Engine 结束后运行 Karing_Shift =====
run_karing "收尾"

echo "===== 全部结束 $(date '+%H:%M:%S')，退出码 $rc ====="
exit $rc