# telegram_bot.py
import os
import json
import tempfile
import mimetypes
import requests
from flask import Flask, request, jsonify

# наши модули
from recognize import ensure_wav, transcribe_audio
from evaluate import evaluate_service
try:
    from sheets import append_row
except Exception:
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
        pass  # не валим вебхук, если отправка не удалась

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

def guess_mime_from_name(name: str) -> str | None:
    # расширенные догадки, т.к. у телеграма часто пустой mime
    n = (name or "").lower()
    if n.endswith(".ogg") or n.endswith(".oga"):
        return "audio/ogg"
    if n.endswith(".mp3"):
        return "audio/mpeg"
    if n.endswith(".wav"):
        return "audio/wav"
    if n.endswith(".m4a"):
        return "audio/mp4"
    if n.endswith(".mp4"):
        return "video/mp4"
    if n.endswith(".webm"):
        return "video/webm"
    if n.endswith(".mov"):
        return "video/quicktime"
    if n.endswith(".mkv"):
        return "video/x-matroska"
    if n.endswith(".avi"):
        return "video/x-msvideo"
    return (mimetypes.guess_type(n)[0])  # может вернуть None

def pick_media(message: dict):
    """
    Возвращает (file_id, suggested_name, mime_hint) из message для:
    video, video_note, voice, audio, document (если это медиа), animation.
    Если ничего нет — (None, None, None).
    """
    # video
    if "video" in message:
        v = message["video"]
        name = v.get("file_name") or "input.mp4"
        return v["file_id"], name, "video/mp4"

    # video_note (кружок)
    if "video_note" in message:
        v = message["video_note"]
        return v["file_id"], "input.mp4", "video/mp4"

    # voice (голосовое ogg/opus)
    if "voice" in message:
        v = message["voice"]
        return v["file_id"], "input.ogg", "audio/ogg"

    # audio (музыка/запись)
    if "audio" in message:
        a = message["audio"]
        name = a.get("file_name") or "input.mp3"
        mime = (a.get("mime_type") or guess_mime_from_name(name) or "audio/mpeg")
        return a["file_id"], name, mime

    # document (часто сюда падают m4a/mp4/ogg)
    if "document" in message:
        d = message["document"]
        name = d.get("file_name") or "input.bin"
        mime = (d.get("mime_type") or guess_mime_from_name(name) or "")
        if any(x in (mime or "").lower() for x in ("video", "audio", "ogg", "mpeg", "mp4", "x-matroska")) or \
           name.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".ogg", ".oga", ".mp3", ".wav", ".m4a")):
            return d["file_id"], name, (mime or guess_mime_from_name(name) or "application/octet-stream")

    # gif/animation (редко полезно)
    if "animation" in message:
        a = message["animation"]
        name = a.get("file_name") or "input.mp4"
        return a["file_id"], name, "video/mp4"

    return None, None, None

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

    file_id, suggested_name, mime_hint = pick_media(message)
    if not file_id:
        tg_send_text(chat_id, "Пришлите видео/голос/аудио с диалогом.")
        return jsonify({"ok": True})

    try:
        # 1) путь к файлу в TG
        file_path = tg_get_file_path(file_id)

        # 2) скачиваем во временный файл
        with tempfile.TemporaryDirectory() as tmpd:
            src_name = os.path.basename(file_path) or suggested_name or "input.bin"
            src_path = os.path.join(tmpd, src_name)
            tg_download_by_path(file_path, src_path)

            # финальный mime (сначала hint из сообщения, если нет — по имени)
            mime_type = mime_hint or guess_mime_from_name(src_name) or "application/octet-stream"

            # 3) нормализуем в WAV 16kHz mono (ВАЖНО: передаём mime)
            wav_path = ensure_wav(src_path, mime_type)

            # 4) распознаём (язык autodetect; мягкий хинт по mime)
            # если аудио ogg/m4a/mp3 — оставляем autodetect, модель сама поймёт ru/kk
            transcript = transcribe_audio(wav_path, mime=mime_type)

        # 5) оцениваем
        score = evaluate_service(transcript)

        # 6) ответ пользователю
        head = transcript[:350].strip()
        dots = "…" if len(transcript) > 350 else ""
        lines = [
            "📝 Расшифровка (кратко): " + (head or "<пусто>") + dots,
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
    app.run(host="0.0.0.0", port=PORT)



