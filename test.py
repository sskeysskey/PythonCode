import openai
import os

client = openai.OpenAI(
    # api_key=os.getenv("POE_API_KEY"),
    api_key="F9SywF8ZA8B3Ju-1Swd7ooD3uMLSlc6EjBU3nP8IDmM",  # 替换成你的实际API密钥
    base_url="https://api.poe.com/v1"
)

chat = client.chat.completions.create(
    model="Claude-Sonnet-3.5",
    messages=[{"role": "user", "content": "Man waters pigeons during heatwave——完整翻译成地道的中文"}],
)

print(chat.choices[0].message.content)