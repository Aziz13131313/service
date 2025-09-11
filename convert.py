# convert.py
import os
import tempfile
from moviepy.video.io.VideoFileClip import VideoFileClip

def convert_video_to_audio(video_path: str, output_format: str = "wav") -> str:
    # сохраняем рядом с исходником во временной папке
    tmpdir = tempfile.gettempdir()
    audio_path = os.path.join(tmpdir, f"audio_{os.getpid()}.{output_format}")
    clip = VideoFileClip(video_path)
    try:
        clip.audio.write_audiofile(audio_path, verbose=False, logger=None)
    finally:
        clip.close()
    return audio_path
