# evaluate.py
import os
import re
import json
from typing import Dict, Any
from openai import OpenAI

# ======= Базовый нулевой ответ =======
def _zero() -> Dict[str, Any]:
    return {
        "Приветствие и представление": 0,
        "Приветствие": 0,
        "Представление": 0,
        "Опрос": "0/0/0",  # (бывал ранее / залог или скупка / уточнил имя)
        "Презентация договора": 0,
        "Прощание и отработка на возврат": 0,
    }

# ======= Нормализация и правила (ru + kk) =======
RU = lambda s: s.lower()
def norm(s: str) -> str:
    s = s or ""
    s = s.replace("ё","е").lower()
    # лёгкая нормализация казахских букв (лациница/кириллица могут мешаться)
    rep = {
        "қ":"к","ү":"у","ұ":"у","ө":"о","һ":"х","ә":"а","і":"и","ң":"н",
    }
    for a,b in rep.items():
        s = s.replace(a,b)
    return s

# паттерны
PAT_GREETING = [
    r"\bздравствуй", r"\bдобрый\s+(день|вечер|утро)", r"\bсалам", r"\bасс(с)?алам", r"\bсалем"
]
PAT_INTRO = [
    r"\bменя\s+зовут\s+\w+", r"\bэто\s+[\w\-]+\b", r"\bмен\s+аты(м)?" , r"\bмен(ін|ың)\s+аты(м)?", r"\bя\s+([а-яё\-]+)\b"
]
PAT_RETURNED = [  # бывал ранее?
    r"\bбывал(и)?\s+раньше", r"\bприходил(и)?\s+раньше", r"\bуже\s+был(и)?",
    r"\bбурын(?:\s+келдi| келген| келгенсiз| келдинiз)?", r"\bбуг(ан)?\s*дейiн\s+кел", r"\bалдын\s+кел",
]
PAT_PAWN_OR_BUY = [  # залог или скупка/выкуп?
    r"\bзалог|\bскупк|\bвыкуп", r"\bпод\s+залог", r"\bсдать\s+в\s+залог",
    r"\bкепiл", r"\bвыкуп(ка)?", r"\bсатып\s+алу", r"\bкепiлге",
]
PAT_NAME = [  # имя / как обращаться?
    r"\bкак\s+к\s+вам\s+обращаться", r"\bкак\s+вас\s+звать", r"\bваше\s+имя",
    r"\bаты(?:н|ңыз)\s*қалай", r"\bқалай\s+атай(ын|ық)", r"\bаты\-ж[оө]н",
]
PAT_CONTRACT = [  # презентация договора
    r"\bпо\s+договор", r"\bпроцент(?:а|ы)?\s+в\s+день", r"\bв\s+день\s+\d+",
    r"\bна\s+месяц\s+\d+", r"\bсумма\s+займ", r"\b\%\s*в\s*день",
]
PAT_WINBACK_STRONG = [  # отработка на возврат (100)
    r"\bжд[её]м\s+вас\s+на\s+выкуп", r"\bприходите\s+на\s+выкуп", r"\bобязательно\s+заберите",
    r"\bвыкуп(ите|ка)\b", r"\bк[үu]тем[iі]з\s+выкуп",
]
PAT_FAREWELL = [  # базовое прощание (50)
    r"\bспасибо\b", r"\bдо\s+свидан", r"\bвсего\s+добр", r"\bхорошего\s+дня",
    r"\braхмет\b", r"\bcау\s*болыңыз", r"\bк[өo]рiскенше",
]

def any_match(text: str, pats) -> bool:
    for p in pats:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False

def rule_based_scores(text: str) -> Dict[str, Any]:
    t = norm(text)
    res = _zero()

    greet = any_match(t, PAT_GREETING)
    intro = any_match(t, PAT_INTRO)
    res["Приветствие"] = 50 if greet else 0
    res["Представление"] = 50 if intro else 0
    res["Приветствие и представление"] = 100 if (greet and intro) else (50 if (greet or intro) else 0)

    s1 = 35 if any_match(t, PAT_RETURNED) else 0
    s2 = 35 if any_match(t, PAT_PAWN_OR_BUY) else 0
    s3 = 35 if any_match(t, PAT_NAME) else 0
    res["Опрос"] = f"{s1}/{s2}/{s3}"

    res["Презентация договора"] = 100 if any_match(t, PAT_CONTRACT) else 0

    if any_match(t, PAT_WINBACK_STRONG):
        res["Прощание и отработка на возврат"] = 100
    elif any_match(t, PAT_FAREWELL):
        res["Прощание и отработка на возврат"] = 50
    else:
        res["Прощание и отработка на возврат"] = 0

    return res

# ======= Опционально: LLM-подстраховка (если хочешь) =======
def llm_scores(text: str) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан")
    client = OpenAI(api_key=api_key)

    system = (
        "Ты оцениваешь диалог на русском/казахском в ломбарде. "
        "Верни JSON с точными ключами: "
        "'Приветствие и представление' (0,50,100), "
        "'Приветствие' (0 или 50), 'Представление' (0 или 50), "
        "'Опрос' как строку '35/30/35' (три позиции: бывал ранее / залог или скупка / уточнил имя; каждая либо 0, либо 35/30/35 соответственно: 35,35 и 35), "
        "'Презентация договора' (0 или 100), "
        "'Прощание и отработка на возврат' (0,50,100). "
        "Никаких комментариев вне JSON."
    )
    resp = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": text or ""},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.output_text)

    out = _zero()
    out["Приветствие и представление"] = int(data.get("Приветствие и представление", 0))
    out["Приветствие"] = int(data.get("Приветствие", 0))
    out["Представление"] = int(data.get("Представление", 0))
    out["Опрос"] = data.get("Опрос", "0/0/0")
    out["Презентация договора"] = int(data.get("Презентация договора", 0))
    out["Прощание и отработка на возврат"] = int(data.get("Прощание и отработка на возврат", 0))
    return out

# ======= Внешний интерфейс =======
def evaluate_service(transcript: str) -> Dict[str, Any]:
    """
    1) Правила (ru/kk) — быстрые и бесплатные.
    2) Если задан OPENAI_API_KEY и хочется — можем объединить с LLM (усреднить/перебить).
       Сейчас — используем только правила; LLM можно включить, выставив USE_LLM=1.
    """
    base = rule_based_scores(transcript or "")

    if os.getenv("USE_LLM", "").strip() == "1":
        try:
            llm = llm_scores(transcript or "")
            # пример объединения: при конфликте берём максимум
            for k in base:
                if k == "Опрос":
                    # если у LLM формат корректный — предпочтем его
                    if isinstance(llm.get("Опрос"), str) and llm["Опрос"].count("/") == 2:
                        base["Опрос"] = llm["Опрос"]
                else:
                    base[k] = max(int(base[k]), int(llm.get(k, 0)))
        except Exception as e:
            base["Ошибка"] = f"LLM недоступен: {e}"

    return base

