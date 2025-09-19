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


# --- Казахский и русский словари для fallback ---
RU_GREETING = [
    "здравствуйте", "добрый день", "добрый вечер", "приветствую", "привет"
]
KK_GREETING = [
    "сәлеметсіз бе", "салеметсиз бе", "сәлем", "салем",
    "ассалаумағалейкум", "ассаламу алейкум", "ассаламуғалейкум"
]

RU_INTRO = [
    "меня зовут", "это компания", "я консультант", "я оператор", "я азиз"
]
KK_INTRO = [
    "менің атым", "мен азиз", "аты-жөнім", "бұл компания", "мен кеңесші"
]

# Возврат/приглашение (закрытие, “ждём на выкупе”)
RU_RETURN = [
    "ждём вас на выкупе", "ждём вас", "приходите", "ждём снова", "ждем на выкуп"
]
KK_RETURN = [
    "сізді күтеміз", "қайта келіңіз", "сатып алу үшін күтеміз", "келіңіз",
    "күтеміз"
]


def _fallback_scoring(transcript: str) -> Dict[str, Any]:
    """
    Простая эвристика по ключевым словам для ru/kk.
    Ставит базовые баллы, если LLM вернула мусор/нули.
    """
    t = (transcript or "").lower()

    greet = 50 if any(w in t for w in RU_GREETING + KK_GREETING) else 0
    intro = 50 if any(w in t for w in RU_INTRO + KK_INTRO) else 0

    # "Опрос": 35/30/35 из трёх микрошагов
    # 1) Был ли ранее?
    was_here = any(p in t for p in [
        "бывали ранее", "вы были ранее", "бұрын болдыңыз", "бұрын келдіңіз"
    ])
    # 2) Залог или скупка?
    pledge_or_buy = any(p in t for p in [
        "залог или скупка", "залог", "скупка",
        "кепіл", "сатып алу"
    ])
    # 3) Уточнил имя?
    ask_name = any(p in t for p in [
        "как к вам обращаться", "как вас зовут",
        "атыңыз қалай", "аты-жөніңіз", "атыңыз кім"
    ])

    o1 = 35 if was_here else 0
    o2 = 30 if pledge_or_buy else 0
    o3 = 35 if ask_name else 0
    opros = f"{o1}/{o2}/{o3}"

    # Презентация договора (очень грубо: упоминание ставки/суммы/срока)
    contract = any(p in t for p in [
        "по договору", "ставка", "процент", "срок", "на месяц",
        "келісімшарт", "пайыз", "мерзім"
    ])
    contract_score = 100 if contract else 0

    # Прощание/отработка возврата
    ret = 100 if any(w in t for w in RU_RETURN + KK_RETURN) else \
          (50 if "спасибо" in t or "рахмет" in t else 0)

    total_greet = min(100, greet + intro)

    return {
        "Приветствие и представление": total_greet,
        "Приветствие": greet,
        "Представление": intro,
        "Опрос": opros,
        "Презентация договора": contract_score,
        "Прощание и отработка на возврат": ret,
    }


def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    Оценка разговора. Сначала пробуем LLM (ru/kk),
    затем страхуемся эвристикой _fallback_scoring.
    """
    base = _zero_result()
    text = transcript or ""

    # 1) Попытка через OpenAI (поддержка ru/kk)
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY не задан")

        client = OpenAI(api_key=api_key)

        system_prompt = (
            "Ты оцениваешь качество обслуживания на русском и казахском (может быть смешанная речь). "
            "Верни JSON с ключами ровно: "
            "'Приветствие' (0 или 50), "
            "'Представление' (0 или 50), "
            "'Опрос' (строка вида '35/30/35' — три числа: был ли ранее, залог/скупка, уточнил имя; если нет — 0), "
            "'Презентация договора' (0 или 100), "
            "'Прощание и отработка на возврат' (0, 50 или 100). "
            "НЕ включай дополнительных полей. "
            "Подсказки по казахскому: приветствие — 'сәлеметсіз бе', 'ассалаумағалейкум'; "
            "представление — 'менің атым ...'; "
            "приглашение/возврат — 'сізді күтеміз', 'қайта келіңіз'."
        )

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            # JSON-объект без лишних полей
            # (в новых SDK response_format поддерживается; если нет — просто парсим output_text)
            response_format={"type": "json_object"},
        )

        data = json.loads(resp.output_text)

        greet = int(data.get("Приветствие", 0)) or 0
        intro = int(data.get("Представление", 0)) or 0
        total_greet = min(100, greet + intro)

        result = {
            "Приветствие и представление": total_greet,
            "Приветствие": greet,
            "Представление": intro,
            "Опрос": str(data.get("Опрос", "0/0/0")),
            "Презентация договора": int(data.get("Презентация договора", 0)) or 0,
            "Прощание и отработка на возврат": int(data.get("Прощание и отработка на возврат", 0)) or 0,
        }

        # Если LLM дала совсем нули/пусто — подстелим соломку эвристикой
        if (
            result["Приветствие и представление"] == 0
            and result["Опрос"] in ("0/0/0", "0/0", "0")
            and result["Презентация договора"] == 0
            and result["Прощание и отработка на возврат"] == 0
        ):
            return _fallback_scoring(text)

        return result

    except Exception as e:
        # Если OpenAI не ответил/ошибся — делаем эвристику + прикрепим текст ошибки
        fb = _fallback_scoring(text)
        fb["Ошибка"] = str(e)
        return fb

