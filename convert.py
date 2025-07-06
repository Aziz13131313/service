from moviepy.editor import VideoFileClip
import os

def video_to_audio(video_path):
    audio_path = "temp_audio.wav"
    try:
        video = VideoFileClip(video_path)
        audio = video.audio
        audio.write_audiofile(audio_path, logger=None)
        audio.close()
        video.close()
    except Exception as e:
        print(f"Ошибка при конвертации видео в аудио: {e}")
        if os.path.exists(audio_path):
            os.remove(audio_path)
        return None
    return audio_path
