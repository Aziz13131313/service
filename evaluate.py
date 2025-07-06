# evaluate.py

def evaluate_service(text: str) -> dict:
    # Пример логики — ты можешь заменить на свою
    pillars = {
        "1. Приветствие": "✅" if "здравствуйте" in text.lower() else "❌",
        "2. Выявление потребности": "✅" if "что вас интересует" in text.lower() else "❌",
        "3. Аргументация": "✅" if "у нас лучшее предложение" in text.lower() else "❌",
        "4. Завершение сделки": "✅" if "готовы оформить" in text.lower() else "❌",
        "5. Прощание": "✅" if "всего доброго" in text.lower() else "❌"
    }
    return pillars
