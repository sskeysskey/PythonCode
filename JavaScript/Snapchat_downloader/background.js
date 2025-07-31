// 用于处理视频下载的后台脚本
let videoList = [];

// 监听来自内容脚本的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'FOUND_VIDEOS') {
        videoList = message.videos;
        // 更新扩展图标上的数字标志
        chrome.action.setBadgeText({ text: videoList.length.toString() });
        chrome.action.setBadgeBackgroundColor({ color: '#FF0000' });

        // 通知popup更新
        chrome.runtime.sendMessage({ type: 'UPDATE_VIDEOS', videos: videoList });
        sendResponse({ success: true });
    } else if (message.type === 'GET_VIDEOS') {
        sendResponse({ videos: videoList });
    } else if (message.type === 'DOWNLOAD_VIDEO') {
        // 下载视频，优先使用高分辨率URL
        const videoInfo = videoList.find(v =>
            v.url === message.url ||
            v.highResUrl === message.url ||
            v.downloadUrl === message.url
        );

        let downloadUrl = message.url;
        // 优先使用高分辨率URL
        if (videoInfo) {
            downloadUrl = videoInfo.highResUrl || videoInfo.downloadUrl || videoInfo.url;
        }

        let filename = 'snapchat_video.mp4';

        if (videoInfo && videoInfo.username) {
            filename = `snapchat_${videoInfo.username}_${Date.now()}.mp4`;
        } else {
            filename = `snapchat_video_${Date.now()}.mp4`;
        }

        chrome.downloads.download({
            url: downloadUrl,
            filename: filename,
            saveAs: false
        });
        sendResponse({ success: true });
    }
    return true;
});

// 当标签页更新时重置视频列表
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete' && tab.url.includes('snapchat.com')) {
        videoList = [];
        chrome.action.setBadgeText({ text: '' });
    }
});