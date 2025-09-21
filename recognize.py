# recognize.py
import os
import tempfile
import subprocess
from typing import Optional

from openai import OpenAI

# --- Конвертация в WAV (16 кГц, моно) ---
def ensure_wav(src_path: str) -> str:
    """
    Возвращает путь к WAV 16kHz mono. Если вход уже WAV — возвращаем как есть.
    Иначе конвертируем через ffmpeg во временный файл.
    """
    low = src_path.lower()
    if low.endswith(".wav"):
        return src_path

    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    # ffmpeg -y -i <in> -ar 16000 -ac 1 <out>
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        out_path,
    ]
    # прячем шум ffmpeg, но если нужно — убери stdout/stderr
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path


# --- Распознавание речи (OpenAI Whisper-1) ---
def transcribe_audio(path_to_wav: str, language_hint: Optional[str] = None) -> str:
    """
    Распознать аудио через OpenAI Whisper-1.
    language_hint: можно передать 'ru' или 'kk' (казахский), чтобы помочь модели.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан")

    client = OpenAI(api_key=api_key)

    with open(path_to_wav, "rb") as f:
        # Модель принимает любые аудио форматы; мы заранее нормализовали в ensure_wav.
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            # Подсказка по языку: 'ru' или 'kk' (казахский), можно оставить None
            # тогда модель сама определит язык.
            # В текущей версии SDK это задаётся через 'language' в extra_params:
            # (если параметр не поддержан — просто игнорируется без ошибки)
            **({"language": language_hint} if language_hint else {}),
        )

    # SDK возвращает объект с текстом в .text
    return (resp.text or "").strip()
