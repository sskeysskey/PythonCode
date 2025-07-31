// 监听来自popup的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'extractData') {
        try {
            const data = extractScoreData();
            sendResponse({ success: true, data: data });
        } catch (error) {
            sendResponse({ success: false, message: error.message });
        }
    }
    return true; // 保持消息通道开放
});

function extractScoreData() {
    const results = [];

    // 查找表格行
    const tableRows = document.querySelectorAll('.el-table__body tbody tr');

    if (tableRows.length === 0) {
        throw new Error('未找到成绩表格，请确保在正确的页面上执行');
    }

    tableRows.forEach(row => {
        try {
            // 提取科目名称 - 从固定列表格中获取
            const subjectCell = row.querySelector('.el-table_1_column_1 .cell');
            if (!subjectCell) return;

            const subject = subjectCell.textContent.trim();
            if (!subject || subject === '') return;

            // 提取得分 - 查找带链接的得分
            const scoreLink = row.querySelector('.el-table_1_column_3 .el-link--inner');
            let score = '';

            if (scoreLink) {
                // 如果有链接，从链接中提取分数
                score = scoreLink.textContent.trim();
            } else {
                // 如果没有链接，直接从单元格提取（比如总分行）
                const scoreCell = row.querySelector('.el-table_1_column_3 .cell');
                if (scoreCell) {
                    score = scoreCell.textContent.trim();
                }
            }

            if (score && score !== '') {
                results.push({
                    subject: subject,
                    score: score
                });
            }
        } catch (error) {
            console.warn('提取行数据时出错:', error);
        }
    });

    if (results.length === 0) {
        throw new Error('未能提取到任何成绩数据，请检查页面结构');
    }

    return results;
}

// 添加一个测试函数，可以在控制台中调用来调试
window.testExtraction = function () {
    try {
        const data = extractScoreData();
        console.log('提取到的数据:', data);
        return data;
    } catch (error) {
        console.error('提取数据失败:', error);
        return null;
    }
};