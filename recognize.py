# recognize.py
import os
import subprocess
from openai import OpenAI

# Требуется OPENAI_API_KEY в переменных окружения
client = OpenAI()

def ensure_wav(path: str, mime: str | None = None) -> str:
    """
    Конвертирует любой медиа-файл в WAV 16kHz mono.
    Параметр mime оставлен для совместимости, но НЕ обязателен.
    """
    dst_path = os.path.splitext(path)[0] + ".wav"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", path,
                "-ac", "1", "-ar", "16000",
                dst_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        raise RuntimeError(f"ffmpeg convert error: {e}")
    return dst_path


def transcribe_audio(path: str, mime: str | None = None, lang: str | None = None) -> str:
    """
    Расшифровка аудио через OpenAI.
    path — путь к локальному файлу (обычно WAV).
    mime — для совместимости (не обязателен).
    lang — 'ru' или 'kk' (если None — автоопределение).
    """
    with open(path, "rb") as f:
        params = {
            "model": "gpt-4o-mini-transcribe",
            "file": f,
        }
        # OpenAI сам делает autodetect. Если хочется подсказать:
        if lang in ("ru", "kk"):
            params["language"] = lang

        result = client.audio.transcriptions.create(**params)

    return (result.text or "").strip()

