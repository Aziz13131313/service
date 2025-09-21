# telegram_bot.py
import os
import json
import tempfile
import requests
from flask import Flask, request, jsonify

# наши модули
from recognize import ensure_wav, transcribe_audio
from evaluate import evaluate_service
try:
    from sheets import append_row
except Exception:
    # если sheets пока не настроен — просто заглушка
    def append_row(*args, **kwargs):
        return None

# --- Конфиг ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN (или TELEGRAM_BOT_TOKEN) не задан")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "8080"))

# --- Flask приложение (ВАЖНО: переменная должна называться app) ---
app = Flask(__name__)

# --- Вспомогалки ---

def tg_send_text(chat_id: int | str, text: str):
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except Exception:
        # не валим вебхук, если ответить пользователю не получилось
        pass

def tg_get_file_path(file_id: str) -> str:
    r = requests.get(
        f"{TELEGRAM_API_URL}/getFile",
        params={"file_id": file_id},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok") or "result" not in data or "file_path" not in data["result"]:
        raise RuntimeError(f"Telegram getFile вернул неожиданный ответ: {data}")
    return data["result"]["file_path"]

def tg_download_by_path(file_path: str, dst_path: str):
    url = f"{TELEGRAM_FILE_URL}/{file_path}"
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def pick_media(message: dict):
    """
    Возвращает (file_id, suggested_name) из message для типов:
    video, video_note, voice, audio, document (если это медиа), animation.
    Если ничего нет — (None, None).
    """
    if "video" in message:
        v = message["video"]
        return v["file_id"], v.get("file_name") or "input.mp4"
    if "video_note" in message:
        v = message["video_note"]
        return v["file_id"], "input.mp4"
    if "voice" in message:
        v = message["voice"]
        return v["file_id"], "input.ogg"
    if "audio" in message:
        a = message["audio"]
        return a["file_id"], a.get("file_name") or "input.mp3"
    if "document" in message:
        d = message["document"]
        mime = (d.get("mime_type") or "").lower()
        name = d.get("file_name") or "input.bin"
        if any(x in mime for x in ("video", "audio", "ogg", "mp4", "mpeg", "x-matroska")) or \
           name.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".ogg", ".oga", ".mp3", ".wav")):
            return d["file_id"], name
    if "animation" in message:
        a = message["animation"]
        return a["file_id"], a.get("file_name") or "input.mp4"
    return None, None

# --- Роуты ---

@app.get("/")
def index():
    return jsonify({"ok": True, "service": "telegram-bot"})

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/telegram/webhook")
def webhook():
    # проверка секрета вебхука
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "invalid webhook secret"}), 401

    update = request.get_json(silent=True) or {}
    # печать апдейта в логи
    try:
        print("[TG UPDATE]", json.dumps(update, ensure_ascii=False))
    except Exception:
        print("[TG UPDATE] <unserializable>")

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return jsonify({"ok": True})

    # команды
    text = (message.get("text") or "").strip()
    if text in ("/start", "/help"):
        tg_send_text(
            chat_id,
            "Пришлите видео/голос/аудио (или документ с медиа). Я расшифрую и оценю по шагам сервиса.",
        )
        return jsonify({"ok": True})

    file_id, suggested_name = pick_media(message)
    if not file_id:
        tg_send_text(chat_id, "Пришлите видео/голос/аудио с диалогом.")
        return jsonify({"ok": True})

    try:
        # 1) путь к файлу в TG
        file_path = tg_get_file_path(file_id)

        # 2) скачиваем во временный файл
        with tempfile.TemporaryDirectory() as tmpd:
            src_path = os.path.join(tmpd, os.path.basename(file_path) or suggested_name)
            tg_download_by_path(file_path, src_path)

            # 3) нормализуем в WAV 16kHz mono
            wav_path = ensure_wav(src_path)

            # 4) распознаём (язык autodetect; можно подсказать 'ru'/'kk')
            transcript = transcribe_audio(wav_path)

        # 5) оцениваем
        score = evaluate_service(transcript)

        # 6) ответ пользователю
        head = transcript[:350]
        dots = "…" if len(transcript) > 350 else ""
        lines = [
            "📝 Расшифровка (кратко): " + head + dots,
            "📊 Оценка:",
        ]
        for k, v in score.items():
            lines.append(f"• {k}: {v}")
        tg_send_text(chat_id, "\n".join(lines))

        # 7) попытка записать в таблицу (не критично)
        try:
            append_row(transcript, score, {"chat_id": chat_id, "message_id": message.get("message_id")})
        except Exception as e_sheet:
            tg_send_text(chat_id, f"ℹ️ Данные оценок будут записаны позже (таблица недоступна: {e_sheet})")

    except requests.HTTPError as http_err:
        tg_send_text(chat_id, f"⚠️ HTTP ошибка при работе с Telegram API: {http_err}")
    except Exception as e:
        tg_send_text(chat_id, f"⚠️ Ошибка: {e}")

    return jsonify({"ok": True})


if __name__ == "__main__":
    # локальный запуск (на Render всё запускается через gunicorn)
    app.run(host="0.0.0.0", port=PORT)



