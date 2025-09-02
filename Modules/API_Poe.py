import openai
import argparse
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget, QDesktopWidget
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QTextCursor, QFont
import traceback # 【新增】导入traceback模块用于打印详细错误

MODERN_STYLESHEET = """
    /* 全局窗口样式 */
    QMainWindow {
        background-color: #2d2d2d; /* 深灰色背景 */
    }

    /* 文本显示区域样式 */
    QTextEdit {
        background-color: #222222; /* 更深的背景色 */
        color: #e0e0e0; /* 明亮的灰色字体 */
        border: 1px solid #444; /* 边框颜色 */
        border-radius: 5px; /* 圆角边框 */
        padding: 10px; /* 内部边距 */
        font-size: 20pt; /* 增大了字体大小 */
    }

    /* 按钮样式 */
    QPushButton {
        background-color: #007acc; /* 蓝色背景 */
        color: white; /* 白色字体 */
        border: none;
        border-radius: 5px;
        padding: 10px 15px; /* 按钮的垂直和水平内边距 */
        font-size: 11pt;
        font-weight: bold; /* 字体加粗 */
    }
    
    /* 按钮悬停效果 */
    QPushButton:hover {
        background-color: #0095ff;
    }
    
    /* 按钮按下效果 */
    QPushButton:pressed {
        background-color: #005c99;
    }

    /* 滚动条整体样式 */
    QScrollBar:vertical {
        border: none;
        background: #2d2d2d;
        width: 12px;
        margin: 15px 0 15px 0;
        border-radius: 6px;
    }

    /* 滚动条滑块样式 */
    QScrollBar::handle:vertical {
        background-color: #555;
        min-height: 30px;
        border-radius: 6px;
    }
    
    QScrollBar::handle:vertical:hover {
        background-color: #666; /* 悬停时变亮 */
    }

    /* 滚动条上下箭头样式 */
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        border: none;
        background: none;
        height: 15px;
    }
"""

# 【新增】定义一个常量作为结束标记
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
        # 添加一个变量来存储完整的响应文本
        self.full_response = ""
        self.init_ui()
        
        # 创建一个定时器来启动API请求
        QTimer.singleShot(100, self.start_api_request)
        
        # 创建并启动等待动画定时器
        self.waiting_timer = QTimer()
        self.waiting_timer.timeout.connect(self.update_waiting_animation)
        self.waiting_timer.start(500)  # 每500毫秒更新一次

    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("POE API")
        self.setGeometry(0, 0, 800, 600)  # 初始尺寸
        self.center_on_screen()  # 将窗口居中

        # 创建中心部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(15, 15, 15, 15) # 增加窗口外边距
        layout.setSpacing(10) # 控件之间的间距

        # 创建文本编辑框
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        # 设置自动换行，确保文本在达到窗口宽度时能正确换行
        self.text_area.setLineWrapMode(QTextEdit.WidgetWidth)
        # 【优化】程序启动时显示的等待信息
        self.text_area.setTextColor(Qt.lightGray)
        self.text_area.setText("请稍候...")
        layout.addWidget(self.text_area)

    def keyPressEvent(self, event):
        """处理按键事件"""
        if event.key() == Qt.Key_Escape:
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
                api_key="F9SywF8ZA8B3Ju-1Swd7ooD3uMLSlc6EjBU3nP8IDmM",
                base_url="https://api.poe.com/v1"
            )
            
            stream = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": self.content}],
                stream=True
            )

            # 【修改】将timer和stream_iter设为实例变量，以便在其他方法中访问
            self.stream_timer = QTimer(self)
            self.stream_iter = iter(stream)

            def process_stream():
                try:
                    chunk = next(self.stream_iter)
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        if self.is_first_chunk:
                            self.waiting_timer.stop()  # 停止等待动画
                            self.text_area.clear()
                            self.text_area.setTextColor(Qt.white)
                            self.is_first_chunk = False
                        text = chunk.choices[0].delta.content
                        self.full_response += text  # 累积完整响应
                        self.stream_in_text(text)
                except StopIteration:
                    # 【修改】流结束时的处理逻辑
                    self.stream_timer.stop()
                    # 1. 将完整响应复制到剪贴板
                    clipboard = QApplication.clipboard()
                    clipboard.setText(self.full_response)
                    
                    # 2. 打印成功标记到标准输出
                    # flush=True 确保信息被立即发送，而不是被缓冲
                    print(SUCCESS_MARKER, flush=True)

                except Exception as e:
                    self.stream_timer.stop()
                    # 【修改】使用 traceback 打印更详细的错误到 stderr
                    detailed_error = traceback.format_exc()
                    self.display_error(f"流处理错误：{str(e)}\n\n详细信息:\n{detailed_error}")
                    
            self.stream_timer.timeout.connect(process_stream)
            self.stream_timer.start(10)
            
        except Exception as e:
            # 【修改】使用 traceback 打印更详细的错误到 stderr
            detailed_error = traceback.format_exc()
            self.display_error(f"启动API请求时出错：{str(e)}\n\n详细信息:\n{detailed_error}")

    def center_on_screen(self):
        """【新增】将窗口在屏幕上居中显示"""
        frame_geometry = self.frameGeometry()
        center_point = QDesktopWidget().availableGeometry().center()
        frame_geometry.moveCenter(center_point)
        self.move(frame_geometry.topLeft())

    def stream_in_text(self, text):
        """将流式文本块插入到文本区域"""
        self.text_area.moveCursor(QTextCursor.End)
        # 插入纯文本
        self.text_area.insertPlainText(text)
        # 确保光标可见，这会自动将滚动条滚动到底部
        self.text_area.ensureCursorVisible()

    def display_error(self, text):
        """【修改】用于显示错误信息，并发送错误标记，然后退出"""
        # 停止可能仍在运行的定时器
        if self.waiting_timer:
            self.waiting_timer.stop()
        
        # 如果是第一次显示，同样需要清空等待信息
        if self.is_first_chunk:
            self.text_area.clear()
            self.is_first_chunk = False
            
        self.text_area.setTextColor(Qt.red) # 用红色显示错误
        self.stream_in_text(f"\n\n❌ {text}") # 换行并添加错误图标
        self.text_area.setTextColor(Qt.white) # 恢复默认颜色

        # 打印错误标记到标准输出
        print(ERROR_MARKER, flush=True)
        
        # 打印详细错误到标准错误流，方便调试
        print(f"Error details: {text}", file=sys.stderr, flush=True)

        # 设置一个短暂的延迟后退出，以便用户能看到错误信息
        QTimer.singleShot(3000, QApplication.instance().quit) # 延迟3秒后退出

def main():
    parser = argparse.ArgumentParser(description='与 POE API 交互的程序')
    parser.add_argument('model', help='模型名称，例如: Claude-Sonnet-3.5')
    parser.add_argument('content', help='要发送给模型的消息内容')
    
    args = parser.parse_args()

    app = QApplication(sys.argv)
    
    # 【优化】设置全局字体
    font = QFont("微软雅黑", 11) # 选用更美观的字体
    app.setFont(font)

    # 【优化】应用我们定义的现代化样式
    app.setStyleSheet(MODERN_STYLESHEET)

    window = ResponseWindow(args.model, args.content)
    window.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()