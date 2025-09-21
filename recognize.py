# recognize.py
import io
import os
import subprocess
import tempfile
from typing import Tuple, Optional

from openai import OpenAI

ASR_MODEL = os.getenv("ASR_MODEL", "whisper-1")
LANG_PRIORITY = [s.strip() for s in os.getenv("LANG_PRIORITY", "kk,ru").split(",") if s.strip()]

# Лексика филиалов для подсказки (ru + kz)
DOMAIN_PROMPT = (
    "Сөздер/слова: сәлеметсіз бе, сәлем, ассалаумағалейкум, келіңіз, күтеміз, "
    "выкуп, скупка, залог, залок, кепіл, алтын, күміс, ай, күн, пайыз, шарт, "
    "Как к вам обращаться, как вас зовут, бывали ранее, залог или скупка."
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _run_ffmpeg_to_wav(in_bytes: bytes, in_mime: str) -> bytes:
    """
    Преобразуем любой вход (ogg/opus/mp4/m4a/mp3) в WAV 16kHz mono.
    """
    with tempfile.NamedTemporaryFile(suffix=".input", delete=False) as fin:
        fin.write(in_bytes)
        fin.flush()
        in_path = fin.name

    out_path = in_path + ".wav"

    cmd = [
        "ffmpeg", "-y",
        "-i", in_path,
        "-ac", "1",          # mono
        "-ar", "16000",      # 16 kHz
        "-vn",
        out_path,
    ]
    # глушим ffmpeg-лог, но если нужно — уберите stderr=subprocess.DEVNULL
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    with open(out_path, "rb") as f:
        data = f.read()

    try:
        os.remove(in_path)
    except Exception:
        pass
    try:
        os.remove(out_path)
    except Exception:
        pass

    return data


def ensure_wav(data: bytes, mime: Optional[str]) -> bytes:
    """
    Если уже WAV/PCM — вернём как есть, иначе перегоняем через ffmpeg.
    """
    mime = (mime or "").lower()
    if mime in ("audio/wav", "audio/x-wav", "audio/wave"):
        return data
    return _run_ffmpeg_to_wav(data, mime)


def _transcribe_wav_core(wav_bytes: bytes, language: Optional[str]) -> Tuple[str, str]:
    """
    Один вызов распознавания. Если language=None — даём модели самой определить.
    Возвращаем (text, detected_language).
    """
    # OpenAI API ждёт файловый поток
    file_obj = io.BytesIO(wav_bytes)
    file_obj.name = "audio.wav"

    resp = client.audio.transcriptions.create(
        model=ASR_MODEL,
        file=file_obj,
        language=language,          # 'kk' или 'ru' или None (auto)
        prompt=DOMAIN_PROMPT,       # доменная подсказка
        temperature=0,              # стабильнее для служебной речи
        response_format="verbose_json",
    )
    text = resp.text or ""
    detected = getattr(resp, "language", "") or (language or "")
    return text, detected


def transcribe_audio(data: bytes, mime: Optional[str]) -> Tuple[str, str]:
    """
    Главная функция: приводит звук к WAV и делает «каскад» языков.
    1) сначала 'kk', потом 'ru', затем auto (None). Берём лучший по длине/наполненности.
    """
    wav = ensure_wav(data, mime)

    candidates = []
    # явные попытки по приоритету
    for lang in LANG_PRIORITY:
        try:
            txt, det = _transcribe_wav_core(wav, lang)
            candidates.append((txt.strip(), det or lang))
        except Exception:
            pass

    # автоопределение — на случай смешанной речи
    try:
        txt_auto, det_auto = _transcribe_wav_core(wav, None)
        candidates.append((txt_auto.strip(), det_auto or "auto"))
    except Exception:
        pass

    # выбираем самый информативный (простой критерий — длина)
    best = max(candidates, key=lambda x: len(x[0]), default=("", ""))
    return best

