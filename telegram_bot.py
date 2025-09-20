# telegram_bot.py
import os
import re
import time
import json
import tempfile
from collections import deque
from typing import Optional

import requests
from flask import Flask, request, jsonify

# ваши модули
from convert import convert_video_to_audio
from recognize import transcribe_audio
from evaluate import evaluate_service
try:
    from sheets import append_row  # опционально
except Exception:  # noqa: BLE001
    append_row = None

# --- Конфиг ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN (или TELEGRAM_BOT_TOKEN) не задан")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "10000"))

# --- Flask ---
app = Flask(__name__)

# --- Утилиты Telegram ---

def tg_send_text(chat_id: int, text: str):
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except Exception:
        pass

def tg_get_file_path(file_id: str) -> str:
    r = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok") or "file_path" not in data["result"]:
        raise RuntimeError(f"Telegram getFile вернул неожиданный ответ: {data}")
    return data["result"]["file_path"]

def tg_download_by_path(file_path: str, dst_path: str):
    url = f"{TELEGRAM_FILE_URL}/{file_path}"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def pick_media(msg: dict):
    """
    Возвращает (file_id, suggested_name) для типов: video, video_note, animation, voice, audio, document(медиа).
    Если нет медиа — (None, None).
    """
    if "video" in msg:
        v = msg["video"]
        return v["file_id"], v.get("file_name") or "input.mp4"
    if "video_note" in msg:
        v = msg["video_note"]
        return v["file_id"], "input.mp4"
    if "animation" in msg:
        a = msg["animation"]
        return a["file_id"], a.get("file_name") or "input.mp4"
    if "voice" in msg:
        v = msg["voice"]
        return v["file_id"], "input.ogg"
    if "audio" in msg:
        a = msg["audio"]
        return a["file_id"], a.get("file_name") or "input.mp3"
    if "document" in msg:
        d = msg["document"]
        mime = (d.get("mime_type") or "").lower()
        name = d.get("file_name") or "input.bin"
        if any(x in mime for x in ("video", "audio", "ogg", "mp4", "mpeg", "x-matroska")) or \
           name.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".ogg", ".oga", ".mp3", ".wav")):
            return d["file_id"], name
    return None, None

# --- Сессии: копим части по 5 минут и потом оцениваем целиком ---

SESSIONS = {}  # chat_id -> {"parts": deque, "started": ts, "last": ts, "open": True, "title": Optional[str]}
SESSION_IDLE_SEC = 25 * 60  # авто-закрытие при простое 25 мин

def _get_order_from_name(name: str, caption: str) -> Optional[int]:
    s = f"{name or ''} {caption or ''}".lower()
    # “… часть 2/4”, “… 2 of 4”, “… (3)”, “…-1”, “…_01”
    m = (
        re.search(r"част[ьи]\s*(\d+)", s)
        or re.search(r"(\d+)\s*of\s*\d+", s)
        or re.search(r"[\(_\- ](\d{1,3})[\). _-]?", s)
    )
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None

def _ensure_session(chat_id: int, title: Optional[str] = None):
    now = int(time.time())
    sess = SESSIONS.get(chat_id)
    if not sess or not sess.get("open"):
        SESSIONS[chat_id] = {"parts": deque(), "started": now, "last": now, "open": True, "title": title}
    else:
        SESSIONS[chat_id]["last"] = now
        if title and not SESSIONS[chat_id].get("title"):
            SESSIONS[chat_id]["title"] = title

def _maybe_autoclose(chat_id: int) -> bool:
    sess = SESSIONS.get(chat_id)
    if not sess or not sess.get("open"):
        return False
    if int(time.time()) - sess["last"] > SESSION_IDLE_SEC:
        SESSIONS[chat_id]["open"] = False
        return True
    return False

def _process_finish(chat_id: int):
    sess = SESSIONS.get(chat_id)
    if not sess:
        tg_send_text(chat_id, "ℹ️ Нет активной сессии.")
        return
    parts = list(sess["parts"])
    if not parts:
        tg_send_text(chat_id, "⚠️ Нет файлов в сессии. Пришлите части и повторите /finish.")
        return

    # сортировка: сначала по extracted order, затем по времени поступления
    parts.sort(key=lambda p: (p["order"], p["ts"]))

    # распознаём
    full_text_chunks = []
    for i, p in enumerate(parts, start=1):
        try:
            t = transcribe_audio(p["path"]).strip()
            full_text_chunks.append(t)
        except Exception as e:
            full_text_chunks.append(f"[Ошибка распознавания части {i}: {e}]")

    full_text = "\n".join(full_text_chunks).strip()

    # оценка целиком
    score = evaluate_service(full_text)

    # отправка ответа
    head = full_text[:400].replace("\n", " ")
    dots = "…" if len(full_text) > 400 else ""
    lines = [
        f"🧩 Частей: {len(parts)}",
        f"📝 Расшифровка (кратко): {head}{dots}",
        "📊 Оценка:",
    ]
    for k, v in score.items():
        lines.append(f"• {k}: {v}")
    tg_send_text(chat_id, "\n".join(lines))

    # опционально — запись в таблицу
    try:
        if append_row:
            # пробуем обе распространённые сигнатуры
            try:
                append_row(full_text, score, chat_id, int(time.time()))
            except TypeError:
                append_row(score, full_text, {"chat_id": chat_id})
    except Exception as e_sheet:
        tg_send_text(chat_id, f"ℹ️ Таблица недоступна: {e_sheet}")

    # очистка
    for p in parts:
        try:
            os.remove(p["path"])
        except Exception:
            pass
    sess["parts"].clear()
    sess["open"] = False

# --- Health ---

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})

# --- Вебхуки: принимаем и на "/" и на "/telegram/webhook" (чтобы не путаться в BotFather) ---

def _handle_update(update: dict):
    # лог апдейта (коротко)
    try:
        print("[TG UPDATE]", json.dumps(update, ensure_ascii=False)[:2000])
    except Exception:
        print("[TG UPDATE] <unserializable>")

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return

    text = (message.get("text") or "").strip()
    low_text = text.lower()

    # команды
    if low_text in ("/start", "/start@your_bot"):
        _ensure_session(chat_id)
        tg_send_text(chat_id, "🟢 Сессия начата. Отправляйте части (по 5 мин). Когда всё — пришлите /finish.")
        return

    if low_text in ("/finish", "/finish@your_bot"):
        _ensure_session(chat_id)
        SESSIONS[chat_id]["open"] = False
        _process_finish(chat_id)
        return

    # медиа
    file_id, file_name = pick_media(message)
    if not file_id:
        # не медиа и не команда — просто игнор/подсказка
        if low_text:
            tg_send_text(chat_id, "ℹ️ Пришлите видео/голос/аудио. Для завершения — /finish.")
        return

    caption = message.get("caption") or ""
    _ensure_session(chat_id, title=file_name)

    try:
        # скачиваем
        path = tg_get_file_path(file_id)
        with tempfile.TemporaryDirectory() as tmpd:
            src_path = os.path.join(tmpd, os.path.basename(path) or (file_name or "input.bin"))
            tg_download_by_path(path, src_path)

            # видео → WAV, остальное как есть
            lower = src_path.lower()
            if lower.endswith((".mp4", ".mov", ".mkv", ".avi", ".webm")):
                audio_path = convert_video_to_audio(src_path, output_format="wav")
            else:
                audio_path = src_path

            # копия в стабильный файл (чтобы пережил выход из tmpdir)
            fd, stable_path = tempfile.mkstemp(suffix="_part.wav")
            os.close(fd)
            with open(stable_path, "wb") as wf, open(audio_path, "rb") as rf:
                wf.write(rf.read())

        order = _get_order_from_name(file_name or "", caption) or 10**6
        sess = SESSIONS[chat_id]
        sess["parts"].append({"order": order, "ts": int(time.time()), "path": stable_path, "name": file_name})
        sess["last"] = int(time.time())

        tg_send_text(chat_id, f"📥 Принял файл: {file_name or 'без имени'}")
    except requests.HTTPError as http_err:
        tg_send_text(chat_id, f"⚠️ Telegram API: {http_err}")
        return
    except Exception as e:
        tg_send_text(chat_id, f"⚠️ Ошибка загрузки файла: {e}")
        return

    # если простаивали долго — авто-завершение
    finished = _maybe_autoclose(chat_id)
    if finished:
        _process_finish(chat_id)
    else:
        tg_send_text(chat_id, "✅ Часть сохранена. Пришлите следующую или /finish.")

def _check_secret(req) -> Optional[tuple]:
    if WEBHOOK_SECRET:
        token = req.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if token != WEBHOOK_SECRET:
            return {"ok": False, "error": "invalid webhook secret"}, 401
    return None

@app.post("/")
def webhook_root():
    bad = _check_secret(request)
    if bad:
        return jsonify(bad[0]), bad[1]
    update = request.get_json(silent=True) or {}
    _handle_update(update)
    return jsonify({"ok": True})

@app.post("/telegram/webhook")
def webhook_tg():
    bad = _check_secret(request)
    if bad:
        return jsonify(bad[0]), bad[1]
    update = request.get_json(silent=True) or {}
    _handle_update(update)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

