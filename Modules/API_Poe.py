import openai
import argparse
import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QTextCursor, QFont, QGuiApplication, QColor

# ================= 跨平台样式定义 =================

# 字体栈：Windows 优先 Segoe UI/微软雅黑，Mac 优先 San Francisco
FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", -apple-system, sans-serif'

MODERN_STYLESHEET = f"""
    /* 全局窗口样式 */
    QMainWindow {{
        background-color: #2d2d2d; /* 深灰色背景 */
    }}
    /* 文本显示区域样式 */
    QTextEdit {{
        background-color: #222222; /* 更深的背景色 */
        color: #e0e0e0; /* 明亮的灰色字体 */
        border: 1px solid #444; /* 边框颜色 */
        border-radius: 5px; /* 圆角边框 */
        padding: 10px; /* 内部边距 */
        font-family: {FONT_FAMILY}; /* <--- 跨平台字体 */
        font-size: 20pt; /* 增大了字体大小 */
    }}
    /* 按钮样式 */
    QPushButton {{
        background-color: #007acc; /* 蓝色背景 */
        color: white; /* 白色字体 */
        border: none;
        border-radius: 5px;
        padding: 10px 15px; /* 按钮的垂直和水平内边距 */
        font-family: {FONT_FAMILY};
        font-size: 11pt;
        font-weight: bold; /* 字体加粗 */
    }}
    
    /* 按钮悬停效果 */
    QPushButton:hover {{
        background-color: #0095ff;
    }}
    
    /* 按钮按下效果 */
    QPushButton:pressed {{
        background-color: #005c99;
    }}
    /* 滚动条整体样式 */
    QScrollBar:vertical {{
        border: none;
        background: #2d2d2d;
        width: 12px;
        margin: 15px 0 15px 0;
        border-radius: 6px;
    }}
    /* 滚动条滑块样式 */
    QScrollBar::handle:vertical {{
        background-color: #555;
        min-height: 30px;
        border-radius: 6px;
    }}
    
    QScrollBar::handle:vertical:hover {{
        background-color: #666; /* 悬停时变亮 */
    }}
    /* 滚动条上下箭头样式 */
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
        height: 15px;
    }}
"""

SUCCESS_MARKER = "---POE_RESPONSE_COMPLETE---"
ERROR_MARKER = "---POE_RESPONSE_ERROR---"

class ResponseWindow(QMainWindow):
    def __init__(self, model, content):
        super().__init__()
        self.is_first_chunk = True
        self.model = model
        self.content = content
        self.waiting_dots = 0
        self.waiting_timer = None
        self.full_response = ""
        self.init_ui()
        
        # 创建一个定时器来启动API请求
        QTimer.singleShot(100, self.start_api_request)
        
        # 创建并启动等待动画定时器
        self.waiting_timer = QTimer()
        self.waiting_timer.timeout.connect(self.update_waiting_animation)
        self.waiting_timer.start(500)

    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("POE API (PyQt6)")
        self.resize(800, 600)
        self.center_on_screen()
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        # PyQt6: 枚举值需要完整路径
        self.text_area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        # 设置初始颜色
        self.text_area.setTextColor(QColor("lightgray"))
        self.text_area.setText("请稍候...")
        layout.addWidget(self.text_area)

    def keyPressEvent(self, event):
        """处理按键事件"""
        # PyQt6: Qt.Key_Escape -> Qt.Key.Key_Escape
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def update_waiting_animation(self):
        """更新等待动画"""
        if self.is_first_chunk:
            self.waiting_dots = (self.waiting_dots + 1) % 4
            dots = "." * self.waiting_dots
            self.text_area.setText(f"正在等待服务器响应{dots.ljust(3)}")

    def start_api_request(self):
        """启动API请求"""
        try:
            client = openai.OpenAI(
                api_key="pjn9pS-BMSBpXmZYs3OoH2gqWw11SxttCm9E47J07SE",
                base_url="https://api.poe.com/v1"
            )
            
            stream = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": self.content}],
                stream=True
            )
            self.stream_timer = QTimer(self)
            self.stream_iter = iter(stream)
            def process_stream():
                try:
                    chunk = next(self.stream_iter)
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        if self.is_first_chunk:
                            self.waiting_timer.stop()
                            self.text_area.clear()
                            # PyQt6: 使用 QColor
                            self.text_area.setTextColor(QColor("white"))
                            self.is_first_chunk = False
                        text = chunk.choices[0].delta.content
                        self.full_response += text
                        self.stream_in_text(text)
                except StopIteration:
                    self.stream_timer.stop()
                    clipboard = QApplication.clipboard()
                    clipboard.setText(self.full_response)
                    print(SUCCESS_MARKER, flush=True)
                    # 如果需要完成后自动退出，可以取消下面注释
                    # QApplication.instance().quit()
                except Exception as e:
                    self.stream_timer.stop()
                    detailed_error = traceback.format_exc()
                    self.display_error(f"流处理错误：{str(e)}\n\n详细信息:\n{detailed_error}")
                    
            self.stream_timer.timeout.connect(process_stream)
            self.stream_timer.start(10)
            
        except Exception as e:
            detailed_error = traceback.format_exc()
            self.display_error(f"启动API请求时出错：{str(e)}\n\n详细信息:\n{detailed_error}")

    def center_on_screen(self):
        """PyQt6: 移除 QDesktopWidget，使用 QGuiApplication 获取屏幕尺寸"""
        frame_geometry = self.frameGeometry()
        screen = QGuiApplication.primaryScreen()
        if screen:
            center_point = screen.availableGeometry().center()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())

    def stream_in_text(self, text):
        """将流式文本块插入到文本区域，并保持当前视口位置不变"""
        # 记录当前滚动位置
        vbar = self.text_area.verticalScrollBar()
        current_value = vbar.value()

        # 在文末插入文本
        cursor = self.text_area.textCursor()
        # PyQt6: QTextCursor.End -> QTextCursor.MoveOperation.End
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_area.setTextCursor(cursor)
        self.text_area.insertPlainText(text)

        # 恢复滚动条原位置，避免自动滚动到末尾
        vbar.setValue(current_value)

    def display_error(self, text):
        """用于显示错误信息，并发送错误标记，然后退出"""
        if self.waiting_timer:
            self.waiting_timer.stop()
        
        if self.is_first_chunk:
            self.text_area.clear()
            self.is_first_chunk = False
            
        self.text_area.setTextColor(QColor("red"))
        
        # 显示错误时同样保持视口不动
        vbar = self.text_area.verticalScrollBar()
        current_value = vbar.value()
        
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_area.setTextCursor(cursor)
        self.text_area.insertPlainText(f"\n\n❌ {text}")
        
        vbar.setValue(current_value)
        self.text_area.setTextColor(QColor("white"))
        print(ERROR_MARKER, flush=True)
        print(f"Error details: {text}", file=sys.stderr, flush=True)
        # 设置一个短暂的延迟后退出
        QTimer.singleShot(3000, QApplication.instance().quit)

def main():
    parser = argparse.ArgumentParser(description='与 POE API 交互的程序 (PyQt6)')
    parser.add_argument('model', help='模型名称')
    parser.add_argument('content', help='消息内容')
    
    args = parser.parse_args()
    app = QApplication(sys.argv)
    
    # <--- 修改：跨平台字体设置 --->
    # 不再强制只使用 Microsoft YaHei
    font = QFont()
    font.setFamilies(["Segoe UI", "Microsoft YaHei", ".AppleSystemUIFont"])
    font.setPointSize(11)
    app.setFont(font)
    
    # 应用现代化样式
    app.setStyleSheet(MODERN_STYLESHEET)
    window = ResponseWindow(args.model, args.content)
    window.show()
    
    # PyQt6: exec_() 已弃用，使用 exec()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
