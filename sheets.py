# sheets.py
import json
import os
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials

ALMATY_TZ = timezone(timedelta(hours=6))  # Asia/Almaty (UTC+6)

def _get_ws():
    creds_json = os.getenv("GSHEET_CREDENTIALS_JSON")
    if not creds_json:
        raise RuntimeError("GSHEET_CREDENTIALS_JSON is not set")
    info = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.getenv("GSHEET_ID"))
    ws = sh.worksheet(os.getenv("GSHEET_WORKSHEET", "Лист1"))
    return ws

def append_row(evaluation: dict, transcript: str, extra: dict | None = None):
    """
    Склеиваем словарь под фактические заголовки листа и дописываем строку.
    Работает с одной суммарной колонкой "Приветствие и представление" (0/50/100).
    Если в листе присутствуют "Приветствие"/"Представление" — тоже заполним.
    Поддерживает колонки "Дата" и "Время".
    """
    ws = _get_ws()
    headers = ws.row_values(1)
    header_idx = {h.strip(): i for i, h in enumerate(headers, start=1) if h.strip()}

    # База времени (два поля — если есть соответствующие колонки)
    now = datetime.now(ALMATY_TZ)
    base = {
        "Дата": now.strftime("%Y-%m-%d"),
        "Время": now.strftime("%H:%M:%S"),
        # краткий транскрипт — если такая колонка есть
        "Транскрипт(кратко)": (transcript[:250] + "…") if transcript and len(transcript) > 250 else (transcript or ""),
    }

    # Оценка
    base.update(evaluation)

    # Доп-поля (например: Сессия, Филиал, Продукт, Клиент, Файл, Длительность(с), Комментарии)
    if extra:
        base.update({k: ("" if v is None else v) for k, v in extra.items()})

    # Собираем строку строго в порядке заголовков
    row = []
    for h in headers:
        row.append(base.get(h, ""))

    ws.append_row(row, value_input_option="USER_ENTERED")
