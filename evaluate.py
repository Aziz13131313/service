# evaluate.py
import json
import os
import re
from typing import Any, Dict

from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM = (
    "Ты оцениваешь качество обслуживания по правилам:\n"
    "- 'Приветствие' только 0 или 50.\n"
    "- 'Представление' только 0 или 50.\n"
    "- 'Приветствие и представление' = сумма двух (0/50/100).\n"
    "- 'Опрос' — строка 'X/Y/Z' (каждое — целое 0..100; если нет данных, 0).\n"
    "- 'Презентация договора' только 0, 50 или 100.\n"
    "- 'Прощание и отработка на возврат' только 0, 50 или 100.\n"
    "Верни строго JSON-объект без комментариев и текста вокруг с ключами:\n"
    "  'Приветствие и представление', 'Приветствие', 'Представление',\n"
    "  'Опрос', 'Презентация договора', 'Прощание и отработка на возврат'."
)

def _zero_result() -> Dict[str, Any]:
    return {
        "Приветствие и представление": 0,
        "Приветствие": 0,
        "Представление": 0,
        "Опрос": "0/0/0",
        "Презентация договора": 0,
        "Прощание и отработка на возврат": 0,
    }

def _clamp_to(values: set[int], x: Any, default: int) -> int:
    try:
        xi = int(x)
        return xi if xi in values else default
    except Exception:
        return default

def _parse_poll(s: Any) -> str:
    """Ожидаем строку 'x/y/z'. Любые сбои -> '0/0/0'."""
    if not isinstance(s, str):
        return "0/0/0"
    m = re.findall(r"-?\d+", s)
    if len(m) >= 3:
        try:
            a, b, c = (max(0, int(m[0])), max(0, int(m[1])), max(0, int(m[2])))
            return f"{a}/{b}/{c}"
        except Exception:
            pass
    return "0/0/0"

def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    Возвращает словарь со значениями колонок. При любой ошибке — нули + поле 'Ошибка'.
    """
    base = _zero_result()
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY не задан")

        client = OpenAI(api_key=api_key)

        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Расшифровка диалога:\n{transcript or ''}\n\nВерни только JSON."},
            ],
        )
        content = resp.choices[0].message.content
        data = json.loads(content)

        # Нормализация значений под жёсткие правила
        greet = _clamp_to({0, 50}, data.get("Приветствие"), 0)
        intro = _clamp_to({0, 50}, data.get("Представление"), 0)

        total = data.get("Приветствие и представление")
        # если модель дала мусор — пересчитаем как сумму
        try:
            total = int(total)
        except Exception:
            total = greet + intro
        # принудительно приводим к 0/50/100 на основе суммы
        total = 100 if greet + intro >= 100 else 50 if greet + intro >= 50 else 0

        contract = _clamp_to({0, 50, 100}, data.get("Презентация договора"), 0)
        bye     = _clamp_to({0, 50, 100}, data.get("Прощание и отработка на возврат"), 0)
        poll    = _parse_poll(data.get("Опрос"))

        return {
            "Приветствие и представление": total,
            "Приветствие": greet,
            "Представление": intro,
            "Опрос": poll,
            "Презентация договора": contract,
            "Прощание и отработка на возврат": bye,
        }

    except Exception as e:
        base["Ошибка"] = str(e)
        return base

