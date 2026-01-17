import sys
import argparse
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor, QTextBlockFormat, QKeySequence
from PyQt6.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout

def copy_to_clipboard(text):
    clipboard = QApplication.clipboard()
    clipboard.setText(text)

def clear_clipboard():
    clipboard = QApplication.clipboard()
    clipboard.clear()

def set_line_height(text_edit, height_factor):
    """设置行高"""
    cursor = QTextCursor(text_edit.document())
    block_format = QTextBlockFormat()
    # 使用 FixedHeight (像素值) 还是 ProportionalHeight (百分比) 取决于你的需求
    # 这里保持原逻辑：使用固定高度 (35px)
    block_format.setLineHeight(height_factor, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    
    # 3. 修改 MoveOperation 的引用方式
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    while cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
        cursor.setBlockFormat(block_format)

class MyWindow(QWidget):
    def keyPressEvent(self, event):
        # 响应 Enter / Return 键进行复制并关闭
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            copy_to_clipboard(self.text_edit.toPlainText())
            self.close()
        # 响应 ESC 键清空并以错误码退出
        elif event.key() == Qt.Key.Key_Escape:
            clear_clipboard()
            self.close()
            # 添加这一行，使程序返回状态码 1
            sys.exit(1)

# MyTextEdit 类也需要添加 ESC 处理
class MyTextEdit(QTextEdit):
    def keyPressEvent(self, event):
        # 1. 处理 ESC 退出
        if event.key() == Qt.Key.Key_Escape:
            clear_clipboard()
            # 使用 window() 获取顶层窗口比 parent() 更稳健
            self.window().close()
            sys.exit(1)
            
        # 2. 处理 Alt + Enter (Mac上是 Option + Enter) 换行
        # 必须先判断组合键，否则会被下面的 Enter 逻辑拦截
        elif (event.modifiers() & Qt.KeyboardModifier.AltModifier) and \
             event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.insertPlainText('\n')
            
        # 3. 处理 Enter 提交
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            copy_to_clipboard(self.toPlainText())
            self.window().close()
            
        # 4. 默认行为
        else:
            super().keyPressEvent(event)
            
    def insertFromMimeData(self, source):
        # 粘贴时仅获取纯文本，去除格式
        super().insertPlainText(source.text())

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--select_all", help="选择是否全选文本", action="store_true")
    return parser.parse_args()

def main():
    args = parse_args()
    app = QApplication(sys.argv)
    
    window = MyWindow()
    window.setWindowTitle('请输入要查询的内容')
    
    layout = QVBoxLayout()
    
    text_edit = MyTextEdit()
    window.text_edit = text_edit
    
    set_line_height(text_edit, 35)
    
    # <--- 跨平台样式优化 --->
    # 1. 增加 font-family 定义，确保 Windows 显示微软雅黑/Segoe UI，Mac 显示系统字体
    # 2. 保持 Gold on Black 的配色
    text_edit.setStyleSheet("""
        QTextEdit {
            color: gold; 
            background-color: black; 
            caret-color: white;
            font-family: "Segoe UI", "Microsoft YaHei", -apple-system, sans-serif;
            font-size: 22pt;
        }
    """)
    
    text_edit.setCursorWidth(2)
    # setFont 在这里主要作为 fallback，样式表通常优先级更高
    # text_edit.setFont(QFont('Microsoft YaHei', 22)) 
    text_edit.setMinimumHeight(300)
    
    layout.addWidget(text_edit)
    
    window.setLayout(layout)
    window.resize(900, 500)  # 设置窗口大小
    
    # 窗口居中逻辑
    screen = app.primaryScreen().availableGeometry()
    window.move(
        (screen.width() - window.width()) // 2, 
        (screen.height() - window.height()) // 2 - 100
    )
    
    # 执行粘贴
    text_edit.paste()
    
    # 确保焦点在输入框，这样可以直接开始打字
    text_edit.setFocus()
    
    if args.select_all:
        text_edit.selectAll()
    
    window.show()
    # 8. 修改 exec_() 为 exec()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
