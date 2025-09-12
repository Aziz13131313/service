# recognize.py
import os
from openai import OpenAI

_api_key = os.getenv("OPENAI_API_KEY")
if not _api_key:
    raise RuntimeError("OPENAI_API_KEY не задан в переменных окружения")

client = OpenAI(api_key=_api_key)

def transcribe_audio(audio_path: str) -> str:
    """Расшифровка аудио через OpenAI Whisper API."""
    with open(audio_path, "rb") as f:
        tr = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
        )
    return (tr.text or "").strip()
