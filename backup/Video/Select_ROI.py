import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication, QFileDialog
import threading
import time

class VideoPlayer:
    def __init__(self, video_path):
        self.cap = cv2.VideoCapture(video_path)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        self.playing = False
        self.current_frame = 0
        self.lock = threading.Lock()
        
        self.start_point = None
        self.end_point = None
        self.selecting = False
        self.running = True
        self.frame = None  # 当前帧

        # 启动视频读取线程
        self.read_thread = threading.Thread(target=self.read_frames)
        self.read_thread.start()

    @staticmethod
    def choose_video():
        app = QApplication([])  # 创建一个应用程序实例
        video_path, _ = QFileDialog.getOpenFileName(None, "选择视频文件", "/Users/yanzhang/Downloads", "Video Files (*.mp4 *.avi *.mov)")
        app.quit()  # 文件选择完成后退出应用程序
        return video_path

    def read_frames(self):
        while self.running:
            if self.playing:
                ret, frame = self.cap.read()
                if not ret:
                    self.playing = False
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.current_frame = 0
                    continue
                with self.lock:
                    self.frame = frame.copy()
                    self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            else:
                time.sleep(0.01)  # 减少CPU占用

    def play(self):
        cv2.namedWindow('Video Player')
        cv2.createTrackbar('Progress', 'Video Player', 0, self.frame_count - 1, self.on_trackbar)
        cv2.setMouseCallback('Video Player', self.mouse_callback)

        while True:
            with self.lock:
                if self.frame is not None:
                    frame_display = self.draw_roi(self.frame.copy())
                else:
                    frame_display = np.zeros((self.frame_height, self.frame_width, 3), dtype=np.uint8)

            cv2.imshow('Video Player', frame_display)

            key = cv2.waitKey(int(1000 / self.fps)) & 0xFF
            if key == 27:  # ESC 键
                break
            elif key == ord(' '):
                self.playing = not self.playing
                if self.playing:
                    print("播放")
                else:
                    print("暂停")

        self.running = False
        self.read_thread.join()
        self.cap.release()
        cv2.destroyAllWindows()

    def on_trackbar(self, value):
        with self.lock:
            self.current_frame = value
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, value)
            ret, frame = self.cap.read()
            if ret:
                self.frame = frame.copy()

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start_point = (x, y)
            self.selecting = True
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.selecting:
                self.end_point = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self.end_point = (x, y)
            self.selecting = False
            self.print_roi()

    def draw_roi(self, frame):
        if self.start_point and self.end_point:
            cv2.rectangle(frame, self.start_point, self.end_point, (0, 255, 0), 2)
        return frame

    def print_roi(self):
        if self.start_point and self.end_point:
            x1, y1 = self.start_point
            x2, y2 = self.end_point
            x = min(x1, x2)
            y = min(y1, y2)
            w = abs(x2 - x1)
            h = abs(y2 - y1)
            roi = (x, y, w, h)
            print(f"ROI = {roi}")

# 使用文件选择对话框选择视频
video_path = VideoPlayer.choose_video()

if video_path:
    # 获取视频帧的宽度和高度
    cap = cv2.VideoCapture(video_path)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"视频宽度: {frame_width}, 视频高度: {frame_height}")
    cap.release()

    player = VideoPlayer(video_path)
    player.play()