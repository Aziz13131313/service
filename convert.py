import os
import subprocess
from pydub import AudioSegment
from math import ceil

LIMIT_MB = 25  # лимит размера файла (в мегабайтах)
CHUNK_DIR = "chunks"

def convert_video_to_audio(input_path):
    output_path = "temp_audio.mp3"
    
    command = [
        "ffmpeg",
        "-i", input_path,
        "-vn",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", "64k",
        output_path
    ]

    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return output_path

def split_audio_if_needed(audio_path):
    if not os.path.exists(CHUNK_DIR):
        os.makedirs(CHUNK_DIR)

    audio = AudioSegment.from_file(audio_path)
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)

    if size_mb <= LIMIT_MB:
        return [audio_path]  # Не нужно резать

    chunk_duration = int(len(audio) / ceil(size_mb / LIMIT_MB))  # длительность куска в мс
    chunk_paths = []

    for i, start in enumerate(range(0, len(audio), chunk_duration)):
        chunk = audio[start:start + chunk_duration]
        chunk_path = os.path.join(CHUNK_DIR, f"chunk_{i+1}.mp3")
        chunk.export(chunk_path, format="mp3", bitrate="64k")
        chunk_paths.append(chunk_path)

    return chunk_paths


