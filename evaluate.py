# evaluate.py
import json
import os
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


def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    Семантическая оценка разговора по четырём шагам сервиса через OpenAI.

    Возвращает словарь со значениями колонок Google Sheets. При ошибке все поля
    заполняются нулями и добавляется поле "Ошибка" с текстом исключения.
    """
    base = _zero_result()
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY не задан в переменных окружения")

        client = OpenAI(api_key=api_key)

        system_prompt = (
            "Ты оцениваешь качество обслуживания по четырём пунктам. "
            "Верни JSON с ключами: 'Приветствие и представление' (0,50,100), "
            "'Приветствие' (0 или 50), 'Представление' (0 или 50), "
            "'Опрос' (строка вида '35/30/35', где каждое значение либо указанное, либо 0), "
            "'Презентация договора' (0 или 100), 'Прощание и отработка на возврат' (0,50,100). "
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
            "Опрос": data.get("Опрос", "0/0/0"),
            "Презентация договора": int(data.get("Презентация договора", 0)),
            "Прощание и отработка на возврат": int(data.get("Прощание и отработка на возврат", 0)),
        }
        return result
    except Exception as e:  # noqa: BLE001
        base["Ошибка"] = str(e)
        return base
