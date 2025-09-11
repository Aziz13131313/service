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
    file_id = None
    filename = "temp_file"

    # 👉 Ловим video, audio, voice и document с mp4/mp3/wav
    if "video" in message:
        file_id = message["video"]["file_id"]
        filename += ".mp4"
    elif "document" in message:
        doc_name = message["document"].get("file_name", "")
        if doc_name.endswith(".mp4") or doc_name.endswith(".mp3") or doc_name.endswith(".wav"):
            file_id = message["document"]["file_id"]
            filename += os.path.splitext(doc_name)[-1]
    elif "audio" in message:
        file_id = message["audio"]["file_id"]
        filename += ".mp3"
    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        filename += ".ogg"

    if file_id:
        try:
            file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]

            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_response = requests.get(file_url)

            with open(filename, "wb") as f:
                f.write(file_response.content)

            # 🎯 Если видео — конвертируем, если уже аудио — используем напрямую
            if filename.endswith(".mp4"):
                audio_path = convert_video_to_audio(filename)
            else:
                audio_path = filename

            transcript = transcribe_audio(audio_path)
            evaluation = evaluate_service(transcript)

            try:
                os.remove(filename)
            except OSError:
                pass
            try:
                os.remove(audio_path)
            except OSError:
                pass

            result_text = "\n".join(f"{k}: {v}" for k, v in evaluation.items())

            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"📊 *Оценка сервиса:*\n{result_text}",
                "parse_mode": "Markdown"
            })

        except Exception as e:
            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"⚠️ Ошибка при обработке: {str(e)}"
            })

    else:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "Пожалуйста, отправьте видео или аудио с записью общения с клиентом.",
        })

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
