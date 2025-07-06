from flask import Flask, request
import requests
import os
from convert import convert_video_to_audio
from recognize import transcribe_audio
from evaluate import evaluate_service

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

    if "video" in message:
        file_id = message["video"]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]

        video_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        video_response = requests.get(video_url)

        with open("temp_video.mp4", "wb") as f:
            f.write(video_response.content)

        audio_path = convert_video_to_audio("temp_video.mp4")
        transcript = transcribe_audio(audio_path)
        evaluation = evaluate_service(transcript)
        result_text = "\n".join(f"{k}: {v}" for k, v in evaluation.items())

        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": f"📊 *Оценка сервиса:*\n{result_text}",
            "parse_mode": "Markdown"
        })

    else:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "Пожалуйста, отправьте видео с записью общения с клиентом.",
        })

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
