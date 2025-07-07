from moviepy.editor import VideoFileClip
from pydub import AudioSegment
import os

def convert_video_to_audio(video_path):
    audio_path = video_path.replace(".mp4", ".mp3")
    
    try:
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(audio_path, codec='mp3')

        # Дополнительная обработка через pydub (если нужно)
        sound = AudioSegment.from_file(audio_path)
        sound.export(audio_path, format="mp3")

    except Exception as e:
        print(f"Ошибка при конвертации видео: {e}")
        return None
    
    return audio_path
