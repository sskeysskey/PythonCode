console.log("Facebook视频下载器后台服务已启动");

// 单个消息监听器
chrome.runtime.onMessage.addListener(function (request, sender, sendResponse) {
    console.log("后台服务收到消息:", request);

    if (request.action === "downloadBlobVideo") {
        chrome.downloads.download({
            url: request.dataUrl,
            filename: `facebook_video_${Date.now()}.mp4`,
            saveAs: true
        });
        return true;
    }

    if (request.action === "downloadVideo") {
        // 验证URL是否是有效的视频URL
        const videoUrl = request.videoUrl;
        console.log("准备下载视频URL:", videoUrl);

        // 检查URL是否有效
        if (!videoUrl || typeof videoUrl !== 'string') {
            console.error("无效的视频URL: URL为空或不是字符串");
            sendResponse({ success: false, error: "无效的视频URL: URL为空或不是字符串" });
            return true;
        }

        if (!videoUrl.startsWith('http')) {
            console.error("无效的视频URL: 不是HTTP链接");
            sendResponse({ success: false, error: "无效的视频URL: 不是HTTP链接" });
            return true;
        }

        console.log("开始下载视频:", videoUrl);

        // 根据URL类型确定文件名后缀
        let fileExtension = '.mp4';
        if (videoUrl.includes('.mp4')) {
            fileExtension = '.mp4';
        } else if (videoUrl.includes('.webm')) {
            fileExtension = '.webm';
        }

        // 尝试下载视频
        if (videoUrl.startsWith('blob:')) {
            // For blob URLs, we need to fetch the content first
            chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
                chrome.scripting.executeScript({
                    target: { tabId: tabs[0].id },
                    function: fetchBlobContent,
                    args: [videoUrl]
                });
            });
        } else {
            chrome.downloads.download({
                url: videoUrl,
                filename: `facebook_video_${Date.now()}${fileExtension}`,
                saveAs: true
            }, function (downloadId) {
                if (chrome.runtime.lastError) {
                    console.error("下载出错:", chrome.runtime.lastError);
                    // 尝试用其他方式下载
                    tryAlternativeDownload(videoUrl, sendResponse);
                } else {
                    console.log("下载已开始，ID:", downloadId);
                    sendResponse({ success: true, downloadId: downloadId });
                }
            });
        }

        return true; // 保持消息通道打开以进行异步响应
    }
});

// Add this function to be injected into the page
function fetchBlobContent(blobUrl) {
    fetch(blobUrl)
        .then(response => response.blob())
        .then(blob => {
            // Convert blob to data URL
            const reader = new FileReader();
            reader.onloadend = function () {
                const dataUrl = reader.result;
                // Send back to extension
                chrome.runtime.sendMessage({
                    action: "downloadBlobVideo",
                    dataUrl: dataUrl
                });
            };
            reader.readAsDataURL(blob);
        });
}

// 如果正常下载失败，尝试替代下载方法
function tryAlternativeDownload(videoUrl, sendResponse) {
    if (videoUrl.includes('facebook.com/watch')) {
        // 如果是watch页面URL，先尝试获取实际视频URL
        chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
            chrome.scripting.executeScript({
                target: { tabId: tabs[0].id },
                function: () => {
                    return document.querySelector('video')?.src;
                }
            }, (results) => {
                if (results && results[0] && results[0].result) {
                    const directUrl = results[0].result;
                    chrome.downloads.download({
                        url: directUrl,
                        filename: `facebook_video_${Date.now()}.mp4`,
                        saveAs: true
                    });
                }
            });
        });
    }

    // 如果是Facebook的特定URL格式，可能需要先打开标签页
    if (videoUrl.includes('facebook.com/watch') && !videoUrl.includes('.mp4')) {
        chrome.tabs.create({ url: videoUrl, active: false }, function (tab) {
            // 等待标签页加载
            setTimeout(() => {
                // 发送消息到新标签页，尝试提取直接视频URL
                chrome.tabs.sendMessage(tab.id, { action: "extractVideo" }, function (response) {
                    if (response && response.success) {
                        // 找到直接URL，尝试再次下载
                        chrome.downloads.download({
                            url: response.videoUrl,
                            filename: `facebook_video_${Date.now()}.mp4`,
                            saveAs: true
                        }, function (downloadId) {
                            if (chrome.runtime.lastError) {
                                console.error("替代下载出错:", chrome.runtime.lastError);
                                sendResponse({ success: false, error: "无法下载视频，请尝试右键视频并选择'另存为'" });
                            } else {
                                console.log("替代下载已开始，ID:", downloadId);
                                sendResponse({ success: true, downloadId: downloadId });
                            }
                            // 关闭临时标签页
                            chrome.tabs.remove(tab.id);
                        });
                    } else {
                        // 仍然无法找到直接URL
                        chrome.tabs.update(tab.id, { active: true });
                        sendResponse({
                            success: false,
                            error: "已在新标签页打开视频，请尝试在视频上右键并选择'另存为'"
                        });
                    }
                });
            }, 3000);
        });
    } else {
        // 对于非Facebook特定URL，仍尝试直接下载
        chrome.downloads.download({
            url: videoUrl,
            filename: `facebook_video_${Date.now()}.mp4`,
            saveAs: true
        }, function (downloadId) {
            if (chrome.runtime.lastError) {
                console.error("替代下载出错:", chrome.runtime.lastError);
                sendResponse({ success: false, error: "无法下载视频: " + chrome.runtime.lastError.message });
            } else {
                console.log("替代下载已开始，ID:", downloadId);
                sendResponse({ success: true, downloadId: downloadId });
            }
        });
    }
}