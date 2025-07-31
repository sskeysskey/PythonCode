import sys
import argparse
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QTextCursor, QTextBlockFormat
from PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout

def copy_to_clipboard(text):
    clipboard = QApplication.clipboard()
    clipboard.setText(text)

def clear_clipboard():
    clipboard = QApplication.clipboard()
    clipboard.clear()

def set_line_height(text_edit, height_factor):
    cursor = QTextCursor(text_edit.document())
    block_format = QTextBlockFormat()
    block_format.setLineHeight(height_factor, QTextBlockFormat.FixedHeight)
    cursor.movePosition(QTextCursor.Start)
    while cursor.movePosition(QTextCursor.NextBlock):
        cursor.setBlockFormat(block_format)

class MyWindow(QWidget):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            copy_to_clipboard(self.text_edit.toPlainText())
            self.close()
        elif event.key() == Qt.Key_Escape:
            clear_clipboard()
            self.close()

class MyTextEdit(QTextEdit):
    def keyPressEvent(self, event):
        if event.modifiers() & Qt.AltModifier and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.insertPlainText('\n')
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            copy_to_clipboard(self.toPlainText())
            self.parent().close()
        else:
            super().keyPressEvent(event)
            
    def insertFromMimeData(self, source):
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
    text_edit.setStyleSheet("QTextEdit { color: gold; background-color: black; caret-color: white; }")
    text_edit.setCursorWidth(2)
    text_edit.setFont(QFont('', 22))
    text_edit.setMinimumHeight(300)
    layout.addWidget(text_edit)
    
    window.setLayout(layout)
    window.resize(900, 500)  # 设置窗口大小
    
    screen = app.primaryScreen().availableGeometry()
    window.move((screen.width() - window.width()) // 2, (screen.height() - window.height()) // 2 - 100)
    
    text_edit.paste()
    if args.select_all:
        text_edit.selectAll()
    
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()