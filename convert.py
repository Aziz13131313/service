import moviepy.editor as mp
import os

def convert_video_to_audio(video_path, audio_path):
    try:
        video = mp.VideoFileClip(video_path)
        audio = video.audio
        audio.write_audiofile(audio_path, logger=None)
        audio.close()
        video.close()
    except Exception as e:
        print(f"Ошибка при конвертации видео в аудио: {e}")
        if os.path.exists(audio_path):
            os.remove(audio_path)
