import os
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")  # ← обязательно для Render

def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as audio_file:
        transcript = openai.Audio.transcribe("whisper-1", audio_file, language="ru")
        return transcript["text"]
