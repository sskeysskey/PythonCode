document.addEventListener('DOMContentLoaded', function () {
    const extractBtn = document.getElementById('extractBtn');
    const statusDiv = document.getElementById('status');
    const videoLinksDiv = document.getElementById('videoLinks');

    // 添加状态显示函数
    function updateStatus(message, type) {
        statusDiv.textContent = message;
        statusDiv.className = type || '';
    }

    // 添加视频链接到界面
    function addVideoLink(url) {
        // 清除之前的链接
        videoLinksDiv.innerHTML = '';

        // 创建新链接元素
        const linkContainer = document.createElement('div');
        linkContainer.className = 'video-link-container';

        // 添加下载按钮
        const downloadBtn = document.createElement('button');
        downloadBtn.textContent = '下载视频';
        downloadBtn.className = 'download-btn';
        downloadBtn.addEventListener('click', function () {
            downloadVideo(url);
        });

        // 添加视频信息
        const infoDiv = document.createElement('div');
        infoDiv.className = 'video-info';
        infoDiv.innerHTML = `
            <p>已找到视频!</p>
            <p class="url-text">${url.substring(0, 50)}...</p>
        `;

        // 将元素添加到容器
        linkContainer.appendChild(infoDiv);
        linkContainer.appendChild(downloadBtn);
        videoLinksDiv.appendChild(linkContainer);
    }

    // 下载视频函数
    // 在popup.js中修改downloadVideo函数
    function downloadVideo(url) {
        updateStatus('开始下载...', 'loading');

        // 如果是blob URL，使用内容脚本中的直接下载方法
        if (url.startsWith('blob:')) {
            chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
                chrome.tabs.sendMessage(tabs[0].id, {
                    action: "directBlobDownload",
                    blobUrl: url
                }, function (response) {
                    if (response && response.success) {
                        updateStatus('下载已开始！', 'success');
                    } else {
                        // 提供替代选项
                        updateStatus('通过blob URL下载失败', 'error');
                        videoLinksDiv.innerHTML = `
                        <div class="alternative-options">
                            <p>无法直接下载blob视频，请尝试以下方法：</p>
                            <button id="captureVideoBtn">录制视频</button>
                            <button id="openPlayerBtn">在播放器中打开</button>
                            <p>或在视频上右键选择"另存为..."</p>
                        </div>
                    `;

                        // 绑定按钮事件
                        document.getElementById('captureVideoBtn').addEventListener('click', function () {
                            chrome.tabs.sendMessage(tabs[0].id, { action: "captureVideo" });
                            updateStatus('正在录制视频...', 'loading');
                        });

                        document.getElementById('openPlayerBtn').addEventListener('click', function () {
                            chrome.tabs.sendMessage(tabs[0].id, { action: "openVideoInPlayer" });
                        });
                    }
                });
            });
        } else {
            // 原有的非blob URL处理代码
            chrome.runtime.sendMessage({
                action: "downloadVideo",
                videoUrl: url
            }, function (response) {
                // 原有的处理逻辑
            });
        }
    }

    // 提取视频函数
    function extractVideo() {
        updateStatus('正在提取视频...', 'loading');
        videoLinksDiv.innerHTML = '';

        chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
            if (!tabs || !tabs[0] || !tabs[0].id) {
                updateStatus('无法获取当前标签页信息', 'error');
                return;
            }

            try {
                chrome.tabs.sendMessage(tabs[0].id, { action: "extractVideo" }, function (response) {
                    if (chrome.runtime.lastError) {
                        console.error("发送消息错误:", chrome.runtime.lastError);

                        // 如果内容脚本未响应，可能是未在Facebook页面上
                        if (chrome.runtime.lastError.message.includes("Could not establish connection")) {
                            updateStatus('请确保您在Facebook视频页面上', 'error');
                        } else {
                            updateStatus('通信错误: ' + chrome.runtime.lastError.message, 'error');
                        }
                        return;
                    }

                    if (response && response.success) {
                        console.log("找到视频URL:", response.videoUrl);
                        updateStatus('已找到视频!', 'success');
                        addVideoLink(response.videoUrl);
                    } else {
                        console.error("未找到视频:", response ? response.error : "未知错误");
                        updateStatus('未找到视频: ' + (response ? response.error : "未找到视频"), 'error');

                        // 尝试获取视频ID，提供替代选项
                        tryGetVideoId();
                    }
                });
            } catch (error) {
                console.error("执行错误:", error);
                updateStatus('执行错误: ' + error.message, 'error');
            }
        });
    }

    // 如果无法直接获取视频URL，尝试获取视频ID
    function tryGetVideoId() {
        chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
            if (!tabs || !tabs[0] || !tabs[0].id) return;

            chrome.tabs.sendMessage(tabs[0].id, { action: "getVideoId" }, function (response) {
                if (chrome.runtime.lastError) return;

                if (response && response.success && response.videoId) {
                    // 提供替代选项
                    videoLinksDiv.innerHTML = `
                        <div class="alternative-options">
                            <p>无法直接下载视频，但找到了视频ID: ${response.videoId}</p>
                            <p>您可以尝试以下方法：</p>
                            <button id="openVideoBtn">在新标签页中打开视频</button>
                        </div>
                    `;

                    // 添加打开视频按钮的事件监听
                    document.getElementById('openVideoBtn').addEventListener('click', function () {
                        chrome.tabs.create({ url: `https://www.facebook.com/watch/?v=${response.videoId}` });
                    });
                }
            });
        });
    }

    // 绑定提取按钮事件
    extractBtn.addEventListener('click', extractVideo);
});