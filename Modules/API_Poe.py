import openai
import argparse
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QPushButton, QVBoxLayout, QWidget
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QTextCursor

class ResponseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("POE API 响应")
        self.setGeometry(100, 100, 600, 400)
        
        # 创建中心部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建文本编辑框
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        # 设置自动换行，确保文本在达到窗口宽度时能正确换行
        self.text_area.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self.text_area)
        
        # 创建关闭按钮
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

    def stream_in_text(self, text):
        """
        【已修改】将流式文本块插入到文本区域的末尾。
        这个方法不会在每个文本块后添加换行符，从而实现连续文本显示。
        """
        # 移动光标到文本末尾
        self.text_area.moveCursor(QTextCursor.End)
        # 插入纯文本
        self.text_area.insertPlainText(text)
        # 确保光标可见，这会自动将滚动条滚动到底部
        self.text_area.ensureCursorVisible()

    def display_error(self, text):
        """用于显示错误信息，可以添加一些格式化，比如红色字体"""
        self.text_area.setTextColor(Qt.red)
        self.stream_in_text(text)
        self.text_area.setTextColor(Qt.black) # 恢复默认颜色

def main():
    parser = argparse.ArgumentParser(description='与 POE API 交互的程序')
    parser.add_argument('model', help='模型名称，例如: Claude-Sonnet-3.5')
    parser.add_argument('content', help='要发送给模型的消息内容')
    
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = ResponseWindow()
    window.show()

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

        # 创建定时器来处理流式响应
        response_buffer = ""
        timer = QTimer()
        stream_iter = iter(stream)

        def process_stream():
            nonlocal response_buffer
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
                # 发生其他错误，显示错误信息并停止
                window.display_error(f"\n\n流处理错误：{str(e)}")
                timer.stop()

        timer.timeout.connect(process_stream)
        timer.start(10)  # 每10毫秒检查一次新内容
        
    except Exception as e:
        # 在启动API请求时就发生错误
        window.display_error(f"启动API请求时出错：{str(e)}")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()