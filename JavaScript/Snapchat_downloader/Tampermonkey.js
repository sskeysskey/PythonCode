// ==UserScript==
// @name         Snapchat 视频下载器
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  在Snapchat视频上添加下载按钮，支持下载最高分辨率视频
// @author       Your Name
// @match        https://*.snapchat.com/*
// @grant        GM_download
// @grant        GM_addStyle
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    // 添加样式
    GM_addStyle(`
        .sc-download-btn {
            position: absolute;
            bottom: 20px;
            right: 20px;
            background-color: rgba(0, 0, 0, 0.6);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 8px 12px;
            cursor: pointer;
            font-size: 14px;
            display: flex;
            align-items: center;
            z-index: 9999;
            transition: all 0.2s ease;
        }
        
        .sc-download-btn:hover {
            background-color: rgba(0, 0, 0, 0.8);
        }
        
        .sc-download-btn svg {
            margin-right: 5px;
            width: 16px;
            height: 16px;
        }
        
        .sc-toast {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background-color: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px 20px;
            border-radius: 4px;
            z-index: 10000;
            font-size: 14px;
            transition: opacity 0.3s ease;
            opacity: 0;
        }
        
        .sc-toast.show {
            opacity: 1;
        }
    `);

    // 用于存储已处理的视频元素
    const processedVideos = new Set();

    // 用于存储视频URL和相关信息
    const videoMap = new Map();

    // 显示通知toast
    function showToast(message, duration = 3000) {
        // 检查是否已有toast元素
        let toast = document.querySelector('.sc-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'sc-toast';
            document.body.appendChild(toast);
        }

        toast.textContent = message;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
        }, duration);
    }

    // 下载视频函数
    function downloadVideo(url, videoName) {
        try {
            // 尝试获取blob内容以确保获取最高质量
            fetch(url)
                .then(response => response.blob())
                .then(blob => {
                    const blobUrl = URL.createObjectURL(blob);
                    const filename = `snapchat_${videoName || 'video'}_${Date.now()}.mp4`;

                    // 使用GM_download下载
                    GM_download({
                        url: blobUrl,
                        name: filename,
                        onload: function () {
                            showToast('下载完成！');
                            URL.revokeObjectURL(blobUrl);
                        },
                        onerror: function (error) {
                            console.error('下载失败:', error);
                            showToast('下载失败，请重试');

                            // 如果GM_download失败，尝试使用普通下载方法
                            const a = document.createElement('a');
                            a.href = blobUrl;
                            a.download = filename;
                            a.style.display = 'none';
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                            setTimeout(() => URL.revokeObjectURL(blobUrl), 100);
                        }
                    });
                })
                .catch(error => {
                    console.error('获取视频内容失败:', error);
                    showToast('获取视频内容失败，请重试');
                });
        } catch (error) {
            console.error('下载过程出错:', error);
            showToast('下载过程出错，请重试');
        }
    }

    // 添加下载按钮到视频元素
    function addDownloadButton(videoElement) {
        // 防止重复添加
        if (processedVideos.has(videoElement)) {
            return;
        }

        // 标记此视频已处理
        processedVideos.add(videoElement);

        // 找到视频容器
        let videoContainer = videoElement.parentElement;

        // 继续向上查找，直到找到一个有定位的容器
        let searchDepth = 0;
        while (videoContainer &&
            getComputedStyle(videoContainer).position === 'static' &&
            searchDepth < 5) {
            videoContainer = videoContainer.parentElement;
            searchDepth++;
        }

        // 安全检查
        if (!videoContainer) {
            videoContainer = videoElement.parentElement;
        }

        // 查找关联的用户名
        let username = extractUsername(videoElement);

        // 创建下载按钮
        const downloadBtn = document.createElement('button');
        downloadBtn.className = 'sc-download-btn';
        downloadBtn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 16l-5-5h3V4h4v7h3l-5 5zm-5 2v2h10v-2H7z"/>
            </svg>
            下载
        `;

        // 设置容器为相对定位，如果不是的话
        if (getComputedStyle(videoContainer).position === 'static') {
            videoContainer.style.position = 'relative';
        }

        // 添加点击事件
        downloadBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();

            // 显示正在处理的toast
            showToast('正在准备下载...');

            // 获取最高质量的视频URL
            let videoUrl = videoElement.src;
            const videoId = videoElement.src; // 以视频src作为ID

            // 如果之前已分析过此视频，使用存储的高质量URL
            if (videoMap.has(videoId)) {
                const videoInfo = videoMap.get(videoId);
                videoUrl = videoInfo.highResUrl || videoUrl;
                username = videoInfo.username || username;
            }

            // 启动下载
            downloadVideo(videoUrl, username);
        });

        // 将按钮添加到视频容器
        videoContainer.appendChild(downloadBtn);

        // 存储视频URL
        if (!videoMap.has(videoElement.src)) {
            videoMap.set(videoElement.src, {
                url: videoElement.src,
                username: username
            });

            // 尝试查找该视频的流媒体清单
            analyzeVideoSources(videoElement);
        }
    }

    // 从视频元素中提取用户名
    function extractUsername(videoElement) {
        let username = "";
        let element = videoElement;
        const maxDepth = 10;
        let depth = 0;

        while (element && depth < maxDepth) {
            element = element.parentElement;
            depth++;

            if (element) {
                // 尝试查找用户名元素
                const userNameElement = element.querySelector('.VonaH.nonIntl h3');
                if (userNameElement && userNameElement.textContent) {
                    username = userNameElement.textContent.trim();
                    break;
                }

                // 尝试从链接中提取用户名
                const profileLink = element.querySelector('a.gtry');
                if (profileLink) {
                    const href = profileLink.getAttribute('href');
                    if (href && href.includes('/add/')) {
                        const usernameFromUrl = href.split('/add/').pop();
                        if (usernameFromUrl) {
                            username = usernameFromUrl;
                            break;
                        }
                    }
                }
            }
        }

        return username;
    }

    // 分析视频源，尝试查找最高质量的版本
    function analyzeVideoSources(videoElement) {
        // 检查视频元素的当前源
        const videoUrl = videoElement.src;

        // 如果是blob URL，尝试获取blob内容
        if (videoUrl && videoUrl.startsWith('blob:')) {
            // 我们已经有了blob URL，这通常已经是最高质量的版本
            // 但我们需要获取其内容以确保可以下载
            fetch(videoUrl)
                .then(response => response.blob())
                .then(blob => {
                    const blobDownloadUrl = URL.createObjectURL(blob);
                    // 存储下载URL
                    if (videoMap.has(videoUrl)) {
                        const videoInfo = videoMap.get(videoUrl);
                        videoInfo.highResUrl = blobDownloadUrl;
                        videoInfo.isHighestResolution = true;
                    }
                })
                .catch(error => {
                    console.error('无法获取视频Blob内容:', error);
                });
        }

        // 尝试监听网络请求以查找相关的流媒体清单
        // 这个在油猴脚本中比较困难，因为我们没有网络请求拦截权限
        // 但我们可以通过分析页面中的资源和请求来尝试
    }

    // 监听新添加的视频元素
    function observeVideoElements() {
        // 首先处理当前页面上的视频
        document.querySelectorAll('video').forEach(video => {
            // 只添加按钮到有效的视频元素
            if (video.src) {
                addDownloadButton(video);
            }
        });

        // 创建一个MutationObserver来监视DOM变化
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                // 检查新添加的节点
                if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                    mutation.addedNodes.forEach(node => {
                        // 检查是否是视频元素
                        if (node.nodeName === 'VIDEO') {
                            if (node.src) {
                                addDownloadButton(node);
                            } else {
                                // 如果视频元素刚创建可能还没有src，稍后再检查
                                setTimeout(() => {
                                    if (node.src) {
                                        addDownloadButton(node);
                                    }
                                }, 500);
                            }
                        }

                        // 检查子元素是否有视频
                        if (node.querySelectorAll) {
                            node.querySelectorAll('video').forEach(video => {
                                if (video.src) {
                                    addDownloadButton(video);
                                } else {
                                    // 延迟检查
                                    setTimeout(() => {
                                        if (video.src) {
                                            addDownloadButton(video);
                                        }
                                    }, 500);
                                }
                            });
                        }
                    });
                }

                // 检查属性变化
                if (mutation.type === 'attributes' &&
                    mutation.attributeName === 'src' &&
                    mutation.target.nodeName === 'VIDEO') {

                    const video = mutation.target;
                    if (video.src) {
                        addDownloadButton(video);
                    }
                }
            });
        });

        // 配置观察器
        const observerConfig = {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['src']
        };

        // 启动观察
        observer.observe(document.body, observerConfig);
    }

    // 初始化函数
    function init() {
        console.log('Snapchat视频下载器已启动');

        // 等待页面加载完毕
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', observeVideoElements);
        } else {
            observeVideoElements();
        }

        // 也监听页面变化，Snapchat是单页应用
        window.addEventListener('load', observeVideoElements);
        window.addEventListener('popstate', () => {
            setTimeout(observeVideoElements, 1000);
        });

        // 额外的页面变化检测，使用定时器
        // 可能不是最优解，但对于SPA通常有效
        let lastUrl = location.href;
        setInterval(() => {
            if (location.href !== lastUrl) {
                lastUrl = location.href;
                setTimeout(observeVideoElements, 1000);
            }
        }, 2000);
    }

    // 监控Blob URL创建
    // 这是一个hack，通过重写URL.createObjectURL来捕获blob URLs
    const originalCreateObjectURL = URL.createObjectURL;
    URL.createObjectURL = function (blob) {
        const blobUrl = originalCreateObjectURL(blob);

        // 检查是否是视频blob
        if (blob.type && blob.type.includes('video')) {
            // 存储blob URL以供下载
            const blobDownloadUrl = originalCreateObjectURL(blob);
            videoMap.set(blobUrl, {
                url: blobUrl,
                highResUrl: blobDownloadUrl,
                isHighestResolution: true,
                username: ""
            });

            // 查找相关的视频元素
            setTimeout(() => {
                document.querySelectorAll('video').forEach(video => {
                    if (video.src === blobUrl && !processedVideos.has(video)) {
                        const username = extractUsername(video);
                        if (videoMap.has(blobUrl)) {
                            videoMap.get(blobUrl).username = username;
                        }
                        addDownloadButton(video);
                    }
                });
            }, 500);
        }

        return blobUrl;
    };

    // 启动脚本
    init();
})();