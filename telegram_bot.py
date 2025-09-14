# telegram_bot.py (DEBUG версия)
import os
import json
import tempfile
import requests
from flask import Flask, request, jsonify

from convert import convert_video_to_audio
from recognize import transcribe_audio
from evaluate import evaluate_service
from sheets import append_row  # если не настроено — просто пропустит запись

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN (или TELEGRAM_BOT_TOKEN) не задан")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "8080"))

app = Flask(__name__)

@app.get("/")
def index():
    return jsonify({"ok": True, "hint": "POST / for Telegram webhook, /health for Render"})

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})

def download_by_file_id(file_id: str, fallback_name: str) -> str:
    """Скачиваем файл по file_id → возвращаем локальный путь."""
    try:
        r = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}, timeout=30)
        # Диагностика: печатаем, если не ок
        if r.status_code != 200:
            print(f"[GETFILE] status={r.status_code} body={r.text}")
            r.raise_for_status()
        res = r.json()
        file_path = res["result"]["file_path"]
        url = f"{TELEGRAM_FILE_URL}/{file_path}"
        print(f"[GETFILE] OK path={file_path}")

        # Скачиваем контент во временный файл
        fr = requests.get(url, timeout=180)
        if fr.status_code != 200:
            print(f"[FILE-DOWNLOAD] status={fr.status_code} body={fr.text}")
            fr.raise_for_status()

        fd, stable_path = tempfile.mkstemp(suffix="_" + (os.path.basename(file_path) or fallback_name))
        os.close(fd)
        with open(stable_path, "wb") as f:
            f.write(fr.content)
        return stable_path
    except Exception as e:
        print(f"[GETFILE][EXC] {e}")
        raise

def pick_media_and_name(message: dict):
    """
    Возвращаем (file_id, file_name, media_type) для поддерживаемых типов.
    """
    # video
    if "video" in message:
        v = message["video"]
        return v["file_id"], v.get("file_name") or "input.mp4", "video"
    # кругляш
    if "video_note" in message:
        v = message["video_note"]
        return v["file_id"], "input.mp4", "video"
    # voice
    if "voice" in message:
        v = message["voice"]
        return v["file_id"], "input.ogg", "voice"
    # audio
    if "audio" in message:
        v = message["audio"]
        return v["file_id"], v.get("file_name") or "input.mp3", "audio"
    # документы (могут быть видео/аудио в виде документа)
    if "document" in message:
        d = message["document"]
        return d["file_id"], d.get("file_name") or "input.bin", "document"
    # gif/анимация
    if "animation" in message:
        a = message["animation"]
        return a["file_id"], a.get("file_name") or "input.mp4", "animation"
    return None, None, None

@app.post("/")
def webhook():
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "invalid webhook secret"}), 401

    data = request.get_json(silent=True) or {}
    # Логируем полный апдейт (убедись, что секретов тут нет)
    try:
        print("[TG UPDATE]", json.dumps(data, ensure_ascii=False))
    except Exception as _:
        print("[TG UPDATE] <unserializable>")

    message = data.get("message") or data.get("edited_message") or {}
    chat = (message.get("chat") or {})
    chat_id = chat.get("id")
    if not chat_id:
        return jsonify({"ok": True})

    try:
        file_id, file_name, media_type = pick_media_and_name(message)
        if not file_id:
            # Подсказываем, какие типы ждём
            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": "Пришлите видео/голос/аудио/документ (видео или аудио файлом)."
            })
            return jsonify({"ok": True})

        # Скачиваем файл
        src_path = download_by_file_id(file_id, file_name)

        # Если это видео — конвертируем в WAV, иначе используем как есть
        lower = src_path.lower()
        if lower.endswith((".mp4", ".mov", ".mkv", ".avi", ".webm")) or media_type in ("video", "animation"):
            audio_path = convert_video_to_audio(src_path, output_format="wav")
        else:
            audio_path = src_path

        # Расшифровка и оценка
        transcript = transcribe_audio(audio_path)
        score = evaluate_service(transcript)

        # Пишем в Google Sheet (если настроено)
        extra = {
            "Сессия": str(message.get("message_id", "")),
            "Файл": file_name,
        }
        try:
            append_row(score, transcript, extra)
        except Exception as e:
            print(f"[GSHEET] append error: {e}")

        # Ответ в чат
        lines = [
            f"📝 Расшифровка (кратко): {transcript[:250]}{'…' if len(transcript) > 250 else ''}",
            "📊 Оценка:",
        ]
        for k, v in score.items():
            lines.append(f"• {k}: {v}")

        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id, "text": "\n".join(lines)
        })

    except Exception as e:
        # Печатаем исключение в логи и сообщаем в чат
        print(f"[WEBHOOK][EXC] {e}")
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id, "text": f"⚠️ Ошибка: {e}"
        })

    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
