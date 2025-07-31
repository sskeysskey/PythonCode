from openai import OpenAI
import os
from tkinter import Tk, simpledialog, messagebox, Label, Button, OptionMenu, StringVar

client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
)

def ask_gpt(question,model):
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": question}
        ]
    )
    return completion.choices[0].message

def main():
    root = Tk()
    root.withdraw()  # 隐藏主窗口

    # 弹出对话框让用户输入问题
    input_window = Tk()
    input_window.title("GPT-3 Question Prompt")

    # 设置模型选择变量
    model_var = StringVar(input_window)
    model_var.set("gpt-3.5-turbo-1106")  # 默认值

    # 创建下拉菜单让用户选择模型
    model_label = Label(input_window, text="请选择模型:")
    model_label.pack(side="top")

    model_menu = OptionMenu(input_window, model_var, "gpt-3.5-turbo-1106", "gpt-4-1106-preview")
    model_menu.pack(side="top")

    # 创建输入框让用户输入问题
    question_label = Label(input_window, text="请输入您的问题:")
    question_label.pack(side="top")

    question_entry = simpledialog.Entry(input_window, bg="black", fg="white")
    question_entry.pack(side="top")

    def submit_question():
        question = question_entry.get()
        model = model_var.get()
        if question:
            answer = ask_gpt(question, model)
            answer_content = answer.content if hasattr(answer, 'content') else "未能获取回答。"
            messagebox.showinfo("GPT-3 回答", answer_content)
        else:
            messagebox.showerror("错误", "问题不能为空。")
        input_window.destroy()

    submit_button = Button(input_window, text="提交", command=submit_question)
    submit_button.pack(side="bottom")

    input_window.mainloop()

if __name__ == "__main__":
    main()