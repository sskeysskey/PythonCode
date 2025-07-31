import cv2

# 鼠标点击事件的回调函数
def click_event(event, x, y, flags, param):
    global points, img
    # 如果是左键点击事件
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x, y))
        cv2.circle(img, (x, y), 5, (0, 0, 255), -1)
        cv2.putText(img, f"({x},{y})", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        cv2.imshow("Frame", img)
        
        # 如果点击了两个点，计算并显示矩形框
        if len(points) == 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.imshow("Frame", img)
            print(f"ROI: ({x1}, {y1}, {x2 - x1}, {y2 - y1})")  # 输出 ROI 值

# 读取视频的第一帧
video_path = '/Users/yanzhang/Downloads/RPReplay_Final1719361160.mov'
cap = cv2.VideoCapture(video_path)
ret, img = cap.read()
# 获取视频帧的宽度和高度
frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"视频宽度: {frame_width}, 视频高度: {frame_height}")
cap.release()

if ret:
    points = []  # 用于存储点击的点
    cv2.imshow("Frame", img)
    cv2.setMouseCallback("Frame", click_event)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
else:
    print("无法读取视频帧")