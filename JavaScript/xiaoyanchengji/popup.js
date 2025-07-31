document.addEventListener('DOMContentLoaded', function () {
    const extractBtn = document.getElementById('extractBtn');
    const status = document.getElementById('status');

    extractBtn.addEventListener('click', async function () {
        try {
            status.textContent = '正在抓取数据...';
            status.className = 'status';

            // 获取当前活动标签页
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

            // 向内容脚本发送消息
            const response = await chrome.tabs.sendMessage(tab.id, { action: 'extractData' });

            if (response && response.success) {
                // 创建CSV内容
                const csvContent = createCSV(response.data);

                // 生成文件名（包含当前时间）
                const now = new Date();
                const filename = `成绩数据_${now.getFullYear()}${(now.getMonth() + 1).toString().padStart(2, '0')}${now.getDate().toString().padStart(2, '0')}_${now.getHours().toString().padStart(2, '0')}${now.getMinutes().toString().padStart(2, '0')}.csv`;

                // 下载文件
                await downloadCSV(csvContent, filename);

                status.textContent = `成功抓取${response.data.length}条数据！`;
                status.className = 'status success';
            } else {
                throw new Error(response?.message || '未找到数据');
            }
        } catch (error) {
            status.textContent = `错误: ${error.message}`;
            status.className = 'status error';
        }
    });
});

function createCSV(data) {
    // CSV头部
    const headers = ['科目', '得分'];

    // 转换数据为CSV格式
    const csvRows = [headers.join(',')];

    data.forEach(item => {
        const row = [item.subject, item.score];
        csvRows.push(row.join(','));
    });

    // 添加BOM以支持中文
    return '\uFEFF' + csvRows.join('\n');
}

async function downloadCSV(csvContent, filename) {
    // 创建Blob
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);

    // 使用Chrome下载API
    await chrome.downloads.download({
        url: url,
        filename: filename,
        saveAs: true
    });

    // 清理URL
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}