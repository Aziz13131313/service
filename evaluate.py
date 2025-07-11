import openai
import os
import json

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def evaluate_service(transcript: str) -> dict:
    prompt = f"""
Ты — профессиональный аудитор сервиса. Клиент отправил текстовую расшифровку разговора сотрудника с клиентом. 
Твоя задача — проверить, насколько выполнены 5 столпов сервиса. Оцени по смыслу, а не по фразам. Язык может быть любой: русский, казахский, английский и т.д.

Вот 5 столпов сервиса:
1. Приветствие — сотрудник поприветствовал клиента.
2. Выявление потребности — выяснил, что интересует клиента, какие у него цели, вопросы.
3. Аргументация — обосновал выгоды, предложил решение или объяснил преимущества.
4. Завершение сделки — подвел к действию (оформлению, оплате, финальному решению).
5. Прощание — попрощался, пожелал хорошего дня или аналогичное.

Вот транскрипт:
\"\"\"
{transcript}
\"\"\"

Проанализируй и выведи результат в JSON-формате вот так:
{{
    "1. Приветствие": "✅",
    "2. Выявление потребности": "❌",
    "3. Аргументация": "✅",
    "4. Завершение сделки": "❌",
    "5. Прощание": "✅"
}}
Только JSON, ничего лишнего.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    content = response.choices[0].message.content

    try:
        return json.loads(content)
    except Exception as e:
        return {
            "1. Приветствие": "❌",
            "2. Выявление потребности": "❌",
            "3. Аргументация": "❌",
            "4. Завершение сделки": "❌",
            "5. Прощание": "❌",
            "Ошибка": f"{e}\nGPT ответил:\n{content}"
        }

