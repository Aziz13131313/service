# evaluate.py
import re

def evaluate_service(transcript: str) -> dict:
    """
    Черновая оценка по 4 пунктам (0/50/100 и т.д.).
    """
    text = transcript.lower()

    # 1) Приветствие и представление
    greeting_score = 0
    if re.search(r"\b(здравствуй|здравствуйте|привет|добрый день|добрый вечер|доброе утро|салам)\b", text):
        greeting_score += 50
    if re.search(r"\bменя зовут|это (.+?) на линии|вас приветствует\b", text):
        greeting_score += 50

    # 2) Опрос (35/30/35) — был ли ранее, спросил имя, цель (залог/скупка)
    was_here = 35 if re.search(r"\bвы уже были|ранее обращались\b", text) else 0
    ask_name = 30 if re.search(r"\bкак к вам обращаться|ваше имя\b", text) else 0
    intent   = 35 if re.search(r"\bзалог|скупк[аи]\b", text) else 0

    # 3) Презентация договора
    presentation = 100 if re.search(r"\bдоговор|условия\s+договора|пункты\s+договора\b", text) else 0

    # 4) Прощание + возврат
    farewell_score = 0
    if re.search(r"\bспасибо|благодарю\b", text):
        farewell_score += 50
    if re.search(r"\bждём вас|заходите ещё|будем рады\b", text):
        farewell_score += 50

    return {
        "Приветствие и представление": greeting_score,
        "Опрос": f"{was_here}/{ask_name}/{intent}",
        "Презентация договора": presentation,
        "Прощание и отработка на возврат": farewell_score,
    }
