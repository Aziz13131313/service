# telegram_bot.py
import os
import io
import json
import shutil
import tempfile
import requests
from pathlib import Path

from recognize import ensure_wav, transcribe_audio
from evaluate import evaluate_service

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN (или TELEGRAM_BOT_TOKEN) не задан")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TG_FILE = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"

# ===================== Вспомогалки =====================

def tg_send_text(chat_id: int, text: str):
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except Exception:
        pass

def tg_get_file_path(file_id: str) -> str:
    r = requests.get(f"{TG_API}/getFile", params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok") or "result" not in data or "file_path" not in data["result"]:
        raise RuntimeError(f"Telegram getFile returned: {data}")
    return data["result"]["file_path"]

def tg_download_to(file_path: str, dst_path: str):
    url = f"{TG_FILE}/{file_path}"
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)

def pick_media(message: dict):
    """
    Возвращает (file_id, suggested_name) из message.
    Поддерживаем video, voice, audio, document (медиа).
    """
    if "video" in message:
        v = message["video"];    return v["file_id"], (v.get("file_name") or "input.mp4")
    if "voice" in message:
        v = message["voice"];    return v["file_id"], "input.ogg"
    if "audio" in message:
        a = message["audio"];    return a["file_id"], (a.get("file_name") or "input.mp3")
    if "document" in message:
        d = message["document"]
        name = d.get("file_name") or "input.bin"
        mime = (d.get("mime_type") or "").lower()
        if any(x in mime for x in ("video", "audio", "ogg", "mp4", "mpeg", "x-matroska")) \
           or name.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".ogg", ".oga", ".mp3", ".wav", ".m4a")):
            return d["file_id"], name
    return None, None

def chat_dir(chat_id: int) -> Path:
    p = Path(tempfile.gettempdir()) / f"tg_{chat_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p

# ===================== Основная логика =====================

def handle_update(update: dict):
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return

    text = (message.get("text") or "").strip()

    # Команды управления батчем кусочков
    if text.lower() in ("/start", "start"):
        shutil.rmtree(chat_dir(chat_id), ignore_errors=True)
        tg_send_text(chat_id, "🎙 Отправляйте аудио/видео частями (до 5 минут каждая). Когда закончите — напишите /finish.")
        return

    if text.lower() in ("/finish", "finish"):
        do_finish(chat_id, message)
        return

    # Приём медиа-файлов (частями)
    file_id, filename = pick_media(message)
    if not file_id:
        if text:
            # Просто игнорируем текст/стикеры
            return
        tg_send_text(chat_id, "Пришлите аудио/видео (можно частями до 5 минут). Завершите — командой /finish.")
        return

    try:
        cdir = chat_dir(chat_id)
        file_path = tg_get_file_path(file_id)
        dst = cdir / f"part_{len(list(cdir.glob('part_*')))+1}_{os.path.basename(filename)}"
        tg_download_to(file_path, str(dst))
        tg_send_text(chat_id, f"✅ Часть сохранена. Пришлите следующую или /finish.")
    except Exception as e:
        tg_send_text(chat_id, f"⚠️ Не удалось сохранить часть: {e}")

def do_finish(chat_id: int, message: dict):
    parts = sorted(chat_dir(chat_id).glob("part_*"))
    if not parts:
        tg_send_text(chat_id, "Нет сохранённых частей. Сначала пришлите аудио/видео.")
        return

    # соберём текст покусочно (чтобы знать, что если часть упала — остальные всё равно пойдут)
    all_text = []
    had_error = False

    for idx, part in enumerate(parts, start=1):
        try:
            wav_path = ensure_wav(str(part))  # конвертируем видео/аудио к стандартному WAV
            text = transcribe_audio(wav_path) # Whisper (авто ru/kk)
            all_text.append(text)
        except Exception as e:
            had_error = True
            all_text.append(f"[Ошибка распознавания части {idx}: {e}]")

    transcript = "\n".join(all_text).strip()

    # Оценка: сначала пробуем правило/LLM из evaluate_service
    try:
        score = evaluate_service(transcript)
    except Exception as e:
        score = {"Ошибка": f"Оценка не выполнена: {e}"}

    # Сборка ответа
    head = transcript.replace("\n", " ")[:350]
    dots = "…" if len(transcript) > 350 else ""
    lines = [
        f"🧩 Частей: {len(parts)}",
        f"📝 Расшифровка (кратко): {head}{dots}",
        "📊 Оценка:"
    ]
    # красивый порядок
    order = [
        "Приветствие и представление",
        "Приветствие",
        "Представление",
        "Опрос",
        "Презентация договора",
        "Прощание и отработка на возврат",
        "Ошибка",
    ]
    for k in order:
        if k in score:
            lines.append(f"• {k}: {score[k]}")
    for k, v in score.items():
        if k not in order:
            lines.append(f"• {k}: {v}")

    tg_send_text(chat_id, "\n".join(lines))

    # Пишем в Google Sheets (если настроено)
    try:
        from sheets import append_row  # опционально
        extra = {"Сессия": str(message.get("message_id", ""))}
        append_row(score, transcript, extra)
    except Exception as e:
        tg_send_text(chat_id, f"ℹ️ Таблица недоступна: {e}")

    # чистим
    shutil.rmtree(chat_dir(chat_id), ignore_errors=True)


