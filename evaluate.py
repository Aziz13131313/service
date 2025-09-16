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


# --- Жёсткое правило для «Опрос: 35/30/35» ---
def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.I) for p in patterns)

def _score_opros(transcript: str) -> str:
    t = (transcript or "").lower()

    # 1) Бывал ли ранее? (35)
    was_before = _has_any(t, [
        r"\bбывал[аи]?\s+раньше\b", r"\bбыли\s+раньше\b",
        r"\bприходил[аи]?\s+раньше\b", r"\bу\s+нас\s+раньше\b",
        r"\bранее\s+были\b",
    ])
    s1 = 35 if was_before else 0

    # 2) Залог или скупка? (30)
    # Варианты формулировок: «залог или скупка / выкуп / займ» и т.п.
    pledge_or_buy = _has_any(t, [
        r"\bзалог\s+или\s+скупк", r"\bзалог\s+или\s+выкуп",
        r"\bскупк[ау]\b", r"\bвам\s+залог\s+или\s+выкуп\b",
        r"\bпод\s+залог\b", r"\bзайм\b",
        r"\bскупаете\b", r"\bпокупаем\b",
    ])
    s2 = 30 if pledge_or_buy else 0

    # 3) Уточнил имя? (35)
    ask_name = _has_any(t, [
        r"\bкак\s+к\s+вам\s+обращаться\b",
        r"\bкак\s+вас\s+зовут\b",
        r"\bваше\s+имя\b",
        r"\bкак\s+могу\s+к\s+вам\s+обращаться\b",
        r"\bимя\s+ваше\b",
    ])
    s3 = 35 if ask_name else 0

    return f"{s1}/{s2}/{s3}"


def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    Оцениваем разговор. «Опрос» считаем детерминированно (35/30/35),
    остальное — через модель OpenAI. При ошибке вернём нули,
    но «Опрос» оставим по нашему правилу.
    """
    base = _zero_result()
    base["Опрос"] = _score_opros(transcript)

    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY не задан в переменных окружения")

        client = OpenAI(api_key=api_key)

        system_prompt = (
            "Ты оцениваешь качество обслуживания. Верни JSON со строго такими ключами: "
            "'Приветствие и представление' (0, 50 или 100), "
            "'Приветствие' (0 или 50), "
            "'Представление' (0 или 50), "
            # ВАЖНО: «Опрос» мы считаем в коде, поэтому здесь просим вернуть заглушку.
            "'Опрос' — верни строку 'DONT_CARE', "
            "'Презентация договора' (0 или 100), "
            "'Прощание и отработка на возврат' (0, 50 или 100). "
            "Никаких пояснений не добавляй."
        )

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript or ""},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.output_text)

        result = {
            "Приветствие и представление": int(data.get("Приветствие и представление", 0)),
            "Приветствие": int(data.get("Приветствие", 0)),
            "Представление": int(data.get("Представление", 0)),
            # Перезаписываем «Опрос» по правилу 35/30/35.
            "Опрос": _score_opros(transcript),
            "Презентация договора": int(data.get("Презентация договора", 0)),
            "Прощание и отработка на возврат": int(data.get("Прощание и отработка на возврат", 0)),
        }
        return result

    except Exception as e:
        base["Ошибка"] = str(e)
        return base


