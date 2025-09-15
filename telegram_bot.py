# telegram_bot.py
import os
import json
import tempfile
import requests
from flask import Flask, request, jsonify

# ваши модули
from convert import convert_video_to_audio
from recognize import transcribe_audio
from evaluate import evaluate_service
from sheets import append_row  # использую сигнатуру append_row(score, transcript, extra_dict)

# --- Конфиг ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN (или TELEGRAM_BOT_TOKEN) не задан")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "8080"))

# --- Flask ---
app = Flask(__name__)

# --- Утилиты Telegram ---
def tg_send_text(chat_id: int, text: str):
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except Exception:
        # не роняем вебхук из-за ошибки отправки ответа
        pass


def tg_get_file_path(file_id: str) -> str:
    """
    Шаг 1: /getFile -> вернуть file_path (может бросить HTTPError)
    """
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
    """
    Шаг 2: /file/bot<token>/<file_path> -> скачать в dst_path
    """
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
    video, video_note, animation, voice, audio, document(медиа).
    Если ничего нет — (None, None).
    """
    if "video" in message:
        v = message["video"]
        return v["file_id"], v.get("file_name") or "input.mp4"

    if "video_note" in message:
        v = message["video_note"]
        return v["file_id"], "input.mp4"

    if "animation" in message:
        a = message["animation"]
        return a["file_id"], a.get("file_name") or "input.mp4"

    if "voice" in message:
        v = message["voice"]
        return v["file_id"], "input.ogg"

    if "audio" in message:
        a = message["audio"]
        return a["file_id"], a.get("file_name") or "input.mp3"

    # иногда камеры/клиенты присылают видео/аудио как документ
    if "document" in message:
        d = message["document"]
        mime = (d.get("mime_type") or "").lower()
        name = d.get("file_name") or "input.bin"
        is_media = any(x in mime for x in ("video", "audio", "ogg", "mp4", "mpeg", "x-matroska")) \
            or name.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".ogg", ".oga", ".mp3", ".wav"))
        if is_media:
            return d["file_id"], name

    return None, None


# --- Роуты состояния/подсказки ---
@app.get("/")
def index():
    return jsonify({"ok": True, "hint": "POST / (webhook для Telegram), /health for Render, /healthz for Render"})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


# --- Основной вебхук ---
@app.post("/")
def webhook():
    # защитный секрет для вебхука
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "invalid webhook secret"}), 401

    update = request.get_json(silent=True) or {}
    try:
        print("[TG UPDATE]", json.dumps(update, ensure_ascii=False))
    except Exception:
        print("[TG UPDATE] <unserializable>")

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return jsonify({"ok": True})

    # выбираем медиа
    file_id, file_name = pick_media(message)
    if not file_id:
        tg_send_text(chat_id, "Пришлите видео/голос/аудио с диалогом.")
        return jsonify({"ok": True})

    try:
        # 1) получаем file_path (ВАЖНО: сначала getFile, потом скачиваем)
        file_path = tg_get_file_path(file_id)

        # 2) скачиваем во временный файл (каталог сам очистится)
        with tempfile.TemporaryDirectory() as tmpd:
            local_name = os.path.basename(file_path) or file_name
            src_path = os.path.join(tmpd, local_name)
            tg_download_by_path(file_path, src_path)

            # 3) если это видео — конвертим в WAV, иначе используем как есть
            lower = src_path.lower()
            if lower.endswith((".mp4", ".mov", ".mkv", ".avi", ".webm")):
                audio_path = convert_video_to_audio(src_path, output_format="wav")
            else:
                audio_path = src_path

            # 4) распознаём и оцениваем
            transcript = transcribe_audio(audio_path)
            score = evaluate_service(transcript)

        # 5) короткий ответ в чат
        head = transcript[:250]
        dots = "…" if len(transcript) > 250 else ""
        lines = [
            f"📝 Расшифровка (кратко): {head}{dots}",
            "📊 Оценка:",
        ]
        for k, v in score.items():
            lines.append(f"• {k}: {v}")
        tg_send_text(chat_id, "\n".join(lines))

        # 6) запись в Google Sheets (не валим поток, если таблица недоступна)
        try:
            extra = {
                "Сессия": str(message.get("message_id", "")),
                "Файл": file_name,
                "Чат": str(chat_id),
                "ДатаUnix": str(message.get("date", "")),
            }
            # важная сигнатура: append_row(score, transcript, extra)
            append_row(score, transcript, extra)
        except Exception as e_sheet:
            tg_send_text(chat_id, f"ℹ️ Данные оценок будут записаны позже (таблица недоступна: {e_sheet})")

    except requests.HTTPError as http_err:
        tg_send_text(chat_id, f"⚠️ HTTP ошибка при работе с Telegram API: {http_err}")
    except Exception as e:
        tg_send_text(chat_id, f"⚠️ Ошибка: {e}")

    return jsonify({"ok": True})


if __name__ == "__main__":
    # локальный запуск; на Render используется gunicorn
    app.run(host="0.0.0.0", port=PORT)
