# evaluate.py
import re

def evaluate_service(transcript: str) -> dict:
    """
    Оценка по твоим критериям.
    ВАЖНО: колонка "Приветствие и представление" = 0/50/100.
    Параллельно считаем "Приветствие" (0/50) и "Представление" (0/50) — если в листе есть такие столбцы, тоже заполним.
    """
    text = (transcript or "").lower()

    # --- Приветствие / Представление ---
    greet = 50 if re.search(r"\b(здравствуй|здравствуйте|привет|добрый\s+(день|вечер|утро))\b", text) else 0
    intro = 50 if re.search(r"\b(меня\s+зовут|это\s+[\w\-]+|на\s+связи|вас\s+приветствует)\b", text) else 0
    greet_intro_total = greet + intro   # 0/50/100

    # --- Опрос (35/30/35) ---
    was_here = 35 if re.search(r"\b(вы\s+уже\s+были|ранее\s+обращались)\b", text) else 0
    ask_name = 30 if re.search(r"\b(как\s+к\s+вам\s+обращаться|ваше\s+имя)\b", text) else 0
    intent   = 35 if re.search(r"\b(залог|скупк[аи])\b", text) else 0
    survey = f"{was_here}/{ask_name}/{intent}"

    # --- Презентация договора ---
    contract = 100 if re.search(r"\b(договор|условия\s+договора|пункты\s+договора)\b", text) else 0

    # --- Прощание + возврат ---
    thanks = 50 if re.search(r"\b(спасибо|благодарю)\b", text) else 0
    return_back = 50 if re.search(r"\b(жд[её]м\s+вас|заходите\s+ещ[её]|будем\s+рады)\b", text) else 0
    farewell = thanks + return_back   # 0/50/100

    return {
        # суммарная колонка (именно её ты хочешь видеть как одну)
        "Приветствие и представление": greet_intro_total,

        # опционально — если есть отдельные столбцы, тоже заполним
        "Приветствие": greet,            # 0/50
        "Представление": intro,          # 0/50

        # как в твоей таблице
        "Опрос": survey,                 # "35/30/35"
        "Презентация договора": contract,               # 0/100
        "Прощание и отработка на возврат": farewell,    # 0/100
    }
