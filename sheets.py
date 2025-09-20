# sheets.py
import os

def append_row(score: dict, transcript: str, extra: dict | None = None):
    """
    Заглушка. Если нужно — подключим gspread.
    Сейчас выбрасывает понятную ошибку, если не настроено.
    """
    creds_json = os.getenv("GSHEET_CREDENTIALS_JSON")
    if not creds_json:
        raise RuntimeError("GSHEET_CREDENTIALS_JSON is not set")
    # TODO: тут подключение к gspread и запись; пока опустим
    return True
