# telegram_bot.py
import os
import tempfile
import requests
from flask import Flask, request, jsonify

from convert import convert_video_to_audio
from recognize import transcribe_audio
from evaluate import evaluate_service

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN (или TELEGRAM_BOT_TOKEN) не задан в переменных окружения")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")  # опционально
PORT = int(os.getenv("PORT", "8080"))

app = Flask(__name__)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/")
def webhook():
    # если используешь секрет Telegram webhook header:
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            return jsonify({"ok": False, "error": "invalid webhook secret"}), 401

    data = request.get_json(silent=True) or {}
    message = data.get("message") or data.get("edited_message") or {}
    chat = (message.get("chat") or {})
    chat_id = chat.get("id")

    # Ничего не прислали — подскажем формат
    if not chat_id:
        return jsonify({"ok": True})

    try:
        # 1) Вытащим file_id из видео/голоса/аудио
        file_id = None
        file_name = "input"

        if "video" in message:
            file_id = message["video"]["file_id"]
            file_name = message["video"].get("file_name") or "input.mp4"
        elif "voice" in message:
            file_id = message["voice"]["file_id"]
            file_name = "input.ogg"
        elif "audio" in message:
            file_id = message["audio"]["file_id"]
            file_name = message["audio"].get("file_name") or "input.mp3"
        else:
            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": "Пожалуйста, пришлите видео/голос/аудио с диалогом клиента."
            })
            return jsonify({"ok": True})

        # 2) Узнаём путь к файлу у Telegram
        r = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}, timeout=30)
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]

        # 3) Скачиваем во временную папку
        with tempfile.TemporaryDirectory() as tmpd:
            src_path = os.path.join(tmpd, os.path.basename(file_path) or file_name)
            file_url = f"{TELEGRAM_FILE_URL}/{file_path}"
            fr = requests.get(file_url, timeout=120)
            fr.raise_for_status()
            with open(src_path, "wb") as f:
                f.write(fr.content)

            # 4) Если видео — конвертируем в wav, иначе используем как есть
            lower = src_path.lower()
            if any(lower.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".avi", ".webm")):
                audio_path = convert_video_to_audio(src_path, output_format="wav")
            else:
                audio_path = src_path

            # 5) Расшифровка и оценка
            transcript = transcribe_audio(audio_path)
            score = evaluate_service(transcript)

        # 6) Собираем читаемый ответ
        lines = [f"📝 Расшифровка (кратко): {transcript[:250]}{'…' if len(transcript) > 250 else ''}",
                 "📊 Оценка:"]
        for k, v in score.items():
            lines.append(f"• {k}: {v}")

        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "\n".join(lines)
        })

    except Exception as e:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"⚠️ Ошибка: {e}"
        })

    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
