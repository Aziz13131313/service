from flask import Flask, request
import requests
import os
from convert import video_to_audio
from recognize import transcribe_audio
from evaluate import evaluate_transcript

# Конфигурация из переменных окружения Render
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" not in data:
        return "ok"

    message = data["message"]
    chat_id = message["chat"]["id"]

    # Проверка: это видео?
    if "video" in message:
        file_id = message["video"]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]

        # Скачиваем видео
        video_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        video_response = requests.get(video_url)

        with open("temp_video.mp4", "wb") as f:
            f.write(video_response.content)

        # Конвертация видео в аудио
        audio_path = video_to_audio("temp_video.mp4")

        # Распознавание речи
        transcript = transcribe_audio(audio_path)

        # Оценка сервиса
        result = evaluate_transcript(transcript)

        # Ответ в Telegram
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"📊 *Оценка сервиса:*\n{result}",
            "parse_mode": "Markdown"
        })

    else:
        # Ответ на не-видео
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "Пожалуйста, отправьте видео с записью общения с клиентом.",
        })

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

