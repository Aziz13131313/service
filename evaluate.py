# evaluate.py
import json
import os
import re
from typing import Any, Dict, Tuple

# ====== Настройки ======
# Хочешь — полностью rule-based (без OpenAI): оставь USE_OPENAI = False
# Если True и есть OPENAI_API_KEY — текст слегка нормализуем моделью,
# но скоринг всё равно делается правилами, чтобы результат был стабилен.
USE_OPENAI = False

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # noqa: N816


def _zero_result() -> Dict[str, Any]:
    return {
        "Приветствие и представление": 0,
        "Приветствие": 0,
        "Представление": 0,
        "Опрос": "0/0/0",
        "Презентация договора": 0,
        "Прощание и отработка на возврат": 0,
    }


# --- вспомогательные словари (ru+kz) ---
RU_GREETING = [
    "здравствуйте",
    "добрый день",
    "добрый вечер",
    "приветствую",
    "привет",
]
KZ_GREETING = [
    "сәлеметсіз бе",
    "салеметсиз бе",
    "сәлем",
    "салем",
    "ассалаумағалейкум",
    "ассаламу алейкум",
    "ассаламуғалейкум",
]

RU_INTRO_SELF = [
    "меня зовут",
    "это компания",
    "это филиал",
    "вас приветствует",
]
KZ_INTRO_SELF = [
    "менің атым",
    "бұл филиал",
    "сізді қарсы алады",
]

# 1) Возвратник (бывали ли ранее)
RU_RETURN = [
    "вы бывали ранее",
    "вы были ранее",
    "вы раньше приходили",
    "бывали у нас",
    "были у нас",
    "раньше были",
]
KZ_RETURN = [
    "бұрын болдыңыз ба",
    "бұрын келдіңіз бе",
    "алдыңызда келдіңіз бе",
    "бұрын келгенсіз бе",
]

# 2) Залог или скупка
RU_MODE = [
    "залог или скупка",
    "залог или выкуп",
    "у вас залог или скупка",
    "заложить или продать",
    "на выкуп или залог",
    "скупка",
    "выкуп",
    "залог",
]
KZ_MODE = [
    "залок па әлде скупка",
    "залок па",
    "скупка ма",
    "выкуп па",
    "кепілге қоясыз ба",
    "сатасыз ба",
]

# 3) Имя/как обращаться
RU_NAME = [
    "как к вам обращаться",
    "как могу к вам обращаться",
    "как к вам можно обращаться",
    "как вас зовут",
    "имя ваше",
]
KZ_NAME = [
    "қалай атайын",
    "сізді қалай атаймын",
    "атыңыз кім",
    "аты-жөніңіз",
]

# Прощание/отработка на возврат
RU_FAREWELL = [
    "ждём вас на выкупе",
    "ждем вас на выкупе",
    "приходите на выкуп",
    "ждём вас снова",
    "ждем вас снова",
    "будем рады видеть",
    "всего хорошего",
    "до свидания",
]
KZ_FAREWELL = [
    "келіңіз",
    "күтеміз",
    "тағымыз күтеміз",
    "қайта келіңіз",
    "сау болыңыз",
    "қош болыңыз",
]

# Доп. слова, усиливающие «возврат/выкуп» в прощании
RETURN_MARKERS = [
    "выкуп",
    "скупка",
    "залог",
    "залок",
    "выкупқа",
    "скупкаға",
    "кепіл",
]


def _norm_text(s: str) -> str:
    s = s.lower()
    # уберём лишние символы, сохраним кириллицу/латиницу/цифры/пробел
    s = re.sub(r"[^0-9a-zа-яёұүіқғңөһǵҩәіӊ\s]", " ", s, flags=re.IGNORECASE)
    # схлопнем пробелы
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _contains_any(txt: str, phrases: list[str]) -> bool:
    return any(p in txt for p in phrases)


def _score_greeting_and_intro(txt: str) -> Tuple[int, int, int]:
    """Возвращает: (суммарно 0/50/100, приветствие 0/50, представление 0/50)"""
    greeted = _contains_any(txt, RU_GREETING) or _contains_any(txt, KZ_GREETING)
    introduced = _contains_any(txt, RU_INTRO_SELF) or _contains_any(txt, KZ_INTRO_SELF)

    greet_score = 50 if greeted else 0
    intro_score = 50 if introduced else 0
    total = greet_score + intro_score  # 0 / 50 / 100
    return total, greet_score, intro_score


def _score_survey(txt: str) -> str:
    """Опрос: '35/30/35' по трём пунктам."""
    # 1) Возвратник
    has_return = _contains_any(txt, RU_RETURN) or _contains_any(txt, KZ_RETURN)
    s1 = 35 if has_return else 0

    # 2) Залог/скупка
    has_mode = _contains_any(txt, RU_MODE) or _contains_any(txt, KZ_MODE)
    s2 = 30 if has_mode else 0

    # 3) Имя
    has_name = _contains_any(txt, RU_NAME) or _contains_any(txt, KZ_NAME)
    s3 = 35 if has_name else 0

    return f"{s1}/{s2}/{s3}"


def _score_contract_presentation(txt: str) -> int:
    """
    Простая эвристика: если есть речь про условия/процент/срок/сумму —
    считаем, что презентовал договор. (0 или 100)
    """
    markers = [
        "по договору",
        "процент",
        "процента",
        "ставка",
        "срок",
        "месяц",
        "дней",
        "сумма",
        "тенге",
        "по шарт",
        "келісім",
        "пайыз",
        "мөлшерлеме",
        "мерзім",
        "ай",
        "күн",
        "сомасы",
    ]
    return 100 if _contains_any(txt, markers) else 0


def _score_farewell_return(txt: str) -> int:
    """
    0/50/100:
    - 100: есть прощание И явная отработка на возврат (ждем/приходите + выкуп/залок/скупка)
    - 50: есть прощание, но без явного возвратного акцента
    - 0: нет прощания
    """
    has_farewell = _contains_any(txt, RU_FAREWELL) or _contains_any(txt, KZ_FAREWELL)
    has_return_push = _contains_any(txt, RETURN_MARKERS)

    if has_farewell and has_return_push:
        return 100
    if has_farewell:
        return 50
    return 0


def _maybe_openai_normalize(text: str) -> str:
    """
    Не обязательно. Если USE_OPENAI=True и есть ключ — чуть сгладим текст:
    попросим модель переписать фразы с ошибками распознавания (ru/kz),
    но без изменения смысла. Если что-то пойдёт не так — вернём исходник.
    """
    if not USE_OPENAI:
        return text
    if not OpenAI:
        return text
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return text

    try:
        client = OpenAI(api_key=api_key)
        system = (
            "Нормализуй транскрипт (ru+kz), поправь опечатки, "
            "сохрани исходный смысл. Выведи только текст."
        )
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": text[:6000]},
            ],
        )
        return getattr(resp, "output_text", text) or text
    except Exception:
        return text


def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    Семантическая оценка разговора по шагам сервиса (ru+kz).
    Возвращает словарь со значениями колонок Google Sheets.
    При любой ошибке — поля-нолики + 'Ошибка'.
    """
    base = _zero_result()
    try:
        raw = transcript or ""
        if not raw.strip():
            return base

        # 1) при желании — нормализуем моделью (опционально)
        normalized = _maybe_openai_normalize(raw)

        # 2) нормализуем для правил (нижний регистр, очистка)
        txt = _norm_text(normalized)

        # 3) скоринг по правилам
        greeting_total, greet, intro = _score_greeting_and_intro(txt)
        survey = _score_survey(txt)
        contract = _score_contract_presentation(txt)
        farewell = _score_farewell_return(txt)

        result = {
            "Приветствие и представление": greeting_total,
            "Приветствие": greet,
            "Представление": intro,
            "Опрос": survey,  # формат '35/30/35'
            "Презентация договора": contract,  # 0 или 100
            "Прощание и отработка на возврат": farewell,  # 0/50/100
        }
        return result
    except Exception as e:
        base["Ошибка"] = str(e)
        return base

