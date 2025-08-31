import openai
import argparse
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QPushButton, QVBoxLayout, QWidget, QDesktopWidget
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QTextCursor, QFont

# =============================================================================
# 现代化的界面样式表 (QSS - 类似于 CSS)
# 我们在这里定义了整个应用的深色主题外观
# =============================================================================
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

class ResponseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.is_first_chunk = True  # 新增标志位，用于判断是否是第一个数据块
        self.init_ui()

    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("POE API 响应")
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
        self.text_area.setText("⏳ 正在连接到 POE API，请稍候...")
        layout.addWidget(self.text_area)
        
        # 创建关闭按钮
        close_button = QPushButton("关闭窗口")
        close_button.setCursor(Qt.PointingHandCursor) # 鼠标悬停时显示手型
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

    def center_on_screen(self):
        """【新增】将窗口在屏幕上居中显示"""
        frame_geometry = self.frameGeometry()
        center_point = QDesktopWidget().availableGeometry().center()
        frame_geometry.moveCenter(center_point)
        self.move(frame_geometry.topLeft())

    def stream_in_text(self, text):
        """将流式文本块插入到文本区域"""
        # 【优化】如果是第一个数据块，先清空等待信息
        if self.is_first_chunk:
            self.text_area.clear()
            self.text_area.setTextColor(Qt.white) # 恢复正常文本颜色
            self.is_first_chunk = False

        self.text_area.moveCursor(QTextCursor.End)
        # 插入纯文本
        self.text_area.insertPlainText(text)
        # 确保光标可见，这会自动将滚动条滚动到底部
        self.text_area.ensureCursorVisible()

    def display_error(self, text):
        """用于显示错误信息"""
        # 如果是第一次显示，同样需要清空等待信息
        if self.is_first_chunk:
            self.text_area.clear()
            self.is_first_chunk = False
            
        self.text_area.setTextColor(Qt.red) # 用红色显示错误
        self.stream_in_text(f"\n\n❌ {text}") # 换行并添加错误图标
        self.text_area.setTextColor(Qt.white) # 恢复默认颜色

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

    # 【优化】先创建并显示窗口
    window = ResponseWindow()
    window.show()

    # 在窗口显示后，再开始执行API请求
    try:
        # 【安全提示】直接在代码中写入API密钥是不安全的。
        # 推荐使用环境变量、配置文件或更安全的密钥管理方式。
        client = openai.OpenAI(
            api_key="F9SywF8ZA8B3Ju-1Swd7ooD3uMLSlc6EjBU3nP8IDmM",  # 替换成你的实际API密钥
            base_url="https://api.poe.com/v1"
        )
        
        # 使用流式API
        stream = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": args.content}],
            stream=True  # 启用流式传输
        )

        timer = QTimer()
        stream_iter = iter(stream)

        def process_stream():
            try:
                chunk = next(stream_iter)
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    # 【已修改】调用新的方法来处理流式文本
                    window.stream_in_text(text)
            except StopIteration:
                # 流结束，停止定时器
                timer.stop()
            except Exception as e:
                window.display_error(f"流处理错误：{str(e)}")
                timer.stop()

        timer.timeout.connect(process_stream)
        timer.start(10)  # 每10毫秒检查一次新内容
        
    except Exception as e:
        # 在启动API请求时就发生错误
        window.display_error(f"启动API请求时出错：{str(e)}")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()