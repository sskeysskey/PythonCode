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
    QMainWindow {{
        background-color: #2d2d2d;
    }}
    QTextEdit {{
        background-color: #222222;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 5px;
        padding: 10px;
        font-family: {FONT_FAMILY}; /* <--- 跨平台字体 */
        font-size: 20pt;
    }}
    QPushButton {{
        background-color: #007acc;
        color: white;
        border: none;
        border-radius: 5px;
        padding: 10px 15px;
        font-family: {FONT_FAMILY};
        font-size: 11pt;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: #0095ff;
    }}
    QPushButton:pressed {{
        background-color: #005c99;
    }}
    QScrollBar:vertical {{
        border: none;
        background: #2d2d2d;
        width: 12px;
        margin: 15px 0 15px 0;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical {{
        background-color: #555;
        min-height: 30px;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: #666;
    }}
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
        
        # 启动 API 请求
        QTimer.singleShot(100, self.start_api_request)
        
        # 等待动画定时器
        self.waiting_timer = QTimer()
        self.waiting_timer.timeout.connect(self.update_waiting_animation)
        self.waiting_timer.start(500)

    def init_ui(self):
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
        # PyQt6 中枚举值需要完整路径
        self.text_area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        # 设置初始颜色
        self.text_area.setTextColor(QColor("lightgray"))
        self.text_area.setText("请稍候...")
        layout.addWidget(self.text_area)

    def keyPressEvent(self, event):
        # PyQt6 中 Qt.Key_Escape 变为 Qt.Key.Key_Escape
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def update_waiting_animation(self):
        if self.is_first_chunk:
            self.waiting_dots = (self.waiting_dots + 1) % 4
            dots = "." * self.waiting_dots
            self.text_area.setText(f"正在等待服务器响应{dots.ljust(3)}")

    def start_api_request(self):
        try:
            # 注意：确保已安装 openai 库
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
                            # PyQt6 使用 Qt.GlobalColor
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
                    QApplication.instance().quit()
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
        """PyQt6 居中方式：移除 QDesktopWidget，改用 QGuiApplication"""
        frame_geometry = self.frameGeometry()
        # 获取主屏幕
        screen = QGuiApplication.primaryScreen()
        if screen:
            screen_center = screen.availableGeometry().center()
            frame_geometry.moveCenter(screen_center)
            offset_y = 80
            self.move(frame_geometry.topLeft().x(), frame_geometry.topLeft().y() + offset_y)

    def stream_in_text(self, text):
        self.text_area.moveCursor(QTextCursor.MoveOperation.End)
        self.text_area.insertPlainText(text)
        self.text_area.ensureCursorVisible()

    def display_error(self, text):
        if self.waiting_timer:
            self.waiting_timer.stop()
        
        if self.is_first_chunk:
            self.text_area.clear()
            self.is_first_chunk = False
            
        self.text_area.setTextColor(QColor("red"))
        self.stream_in_text(f"\n\n❌ {text}")
        self.text_area.setTextColor(QColor("white"))
        print(ERROR_MARKER, flush=True)
        print(f"Error details: {text}", file=sys.stderr, flush=True)
        QTimer.singleShot(3000, QApplication.instance().quit)

def main():
    parser = argparse.ArgumentParser(description='与 POE API 交互的程序 (PyQt6)')
    parser.add_argument('model', help='模型名称')
    parser.add_argument('content', help='消息内容')
    
    args = parser.parse_args()
    app = QApplication(sys.argv)
    
    # <--- 修改：跨平台字体设置 --->
    font = QFont()
    font.setFamilies(["Segoe UI", "Microsoft YaHei", ".AppleSystemUIFont"])
    font.setPointSize(11)
    app.setFont(font)
    
    app.setStyleSheet(MODERN_STYLESHEET)
    window = ResponseWindow(args.model, args.content)
    window.show()
    # PyQt6 中 exec_() 已弃用，直接使用 exec()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
