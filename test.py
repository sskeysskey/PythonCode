from transformers import pipeline
import torch
import kagglehub


model = kagglehub.model_download("google/translategemma/transformers/translategemma-12b-it")


pipe = pipeline(
    "image-text-to-text",
    model=model,
    device="cuda",
    dtype=torch.bfloat16
)

# ---- Text Translation ----
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "source_lang_code": "cs",
                "target_lang_code": "de-DE",
                "text": "The release of TranslateGemma provides researchers and developers with powerful and adaptable tools for a wide array of translation-related tasks. We are excited to see how the community will build upon and utilize these models to break down language barriers and foster greater understanding across cultures. Here’s how to try it:",
            }
        ],
    }
]

output = pipe(text=messages, max_new_tokens=200)
print(output[0]["generated_text"][-1]["content"])

# ---- Text Extraction and Translation ----
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source_lang_code": "cs",
                "target_lang_code": "de-DE",
                "url": "https://c7.alamy.com/comp/2YAX36N/traffic-signs-in-czech-republic-pedestrian-zone-2YAX36N.jpg",
            },
        ],
    }
]

output = pipe(text=messages, max_new_tokens=200)
print(output[0]["generated_text"][-1]["content"])
