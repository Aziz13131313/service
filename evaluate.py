# evaluate.py
import json
import os
import re
from typing import Any, Dict
from openai import OpenAI

def _zero_result() -> Dict[str, Any]:
    return {
        "Приветствие и представление": 0,
        "Приветствие": 0,
        "Представление": 0,
        "Опрос": "0/0/0",
        "Презентация договора": 0,
        "Прощание и отработка на возврат": 0,
    }

# ---------- «Опрос» (детерминированно 35/30/35) ----------
def _has_any(t: str, pats: list[str]) -> bool:
    return any(re.search(p, t, flags=re.I) for p in pats)

def _score_opros(transcript: str) -> str:
    t = (transcript or "").lower()

    was_before = _has_any(t, [
        r"\bвы\s+бывал[аи]?\s+раньше\b",
        r"\bвы\s+бывал[аи]?\s+ранее\b",
        r"\bбыли\s+раньше\b", r"\bраньше\s+у\s+нас\b", r"\bранее\s+у\s+нас\b",
    ])
    s1 = 35 if was_before else 0

    pledge_or_buy = _has_any(t, [
        r"\bзалог\s+или\s+скупк", r"\bзалог\s+или\s+выкуп",
        r"\bпод\s+залог\b", r"\bзайм\b", r"\bскупк[ау]\b", r"\bвыкуп\b",
    ])
    s2 = 30 if pledge_or_buy else 0

    ask_name = _has_any(t, [
        r"\bкак\s+я\s+могу\s+к\s+вам\s+обращаться\b",
        r"\bкак\s+к\s+вам\s+обращаться\b",
        r"\bкак\s+вас\s+зовут\b", r"\bваше\s+имя\b",
    ])
    s3 = 35 if ask_name else 0

    return f"{s1}/{s2}/{s3}"

# ---------- основная оценка ----------
def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    «Опрос» считаем локально. Остальное — через OpenAI.
    Без response_format (во многих сборках SDK он не поддерживается).
    Любая ошибка → нули + поле 'Ошибка', а «Опрос» оставляем рассчитанным.
    """
    base = _zero_result()
    base["Опрос"] = _score_opros(transcript)

    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY не задан в переменных окружения")

        client = OpenAI(api_key=api_key)

        system = (
            "Оцени разговор. Верни ТОЛЬКО JSON со строго такими ключами: "
            "'Приветствие и представление' (0|50|100), "
            "'Приветствие' (0|50), "
            "'Представление' (0|50), "
            "'Опрос' — верни строку 'DONT_CARE', "
            "'Презентация договора' (0|100), "
            "'Прощание и отработка на возврат' (0|50|100). Без пояснений."
        )

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": transcript or ""},
            ],
        )

        text = getattr(resp, "output_text", "") or "{}"
        # Страховка: выдёргиваем первую JSON-скобку
        if "{" in text and "}" in text:
            text = text[text.find("{"): text.rfind("}") + 1]

        data = json.loads(text)

        return {
            "Приветствие и представление": int(data.get("Приветствие и представление", 0)),
            "Приветствие": int(data.get("Приветствие", 0)),
            "Представление": int(data.get("Представление", 0)),
            "Опрос": _score_opros(transcript),
            "Презентация договора": int(data.get("Презентация договора", 0)),
            "Прощание и отработка на возврат": int(data.get("Прощание и отработка на возврат", 0)),
        }

    except Exception as e:
        base["Ошибка"] = str(e)
        return base
