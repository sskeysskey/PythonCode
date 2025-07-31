chrome.runtime.onInstalled.addListener(function () {
    console.log('News Scraper 已安装');
});

// 处理来自content script的下载请求
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "downloadHTML") {
        chrome.downloads.download({
            url: request.url,
            filename: request.filename
        });
    }
});