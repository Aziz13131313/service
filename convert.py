from moviepy.video.io.VideoFileClip import VideoFileClip
from pydub import AudioSegment
import os

def convert_video_to_audio(video_path, output_format="wav"):
    audio_path = "temp_audio." + output_format
    video = VideoFileClip(video_path)
    audio = video.audio
    audio.write_audiofile(audio_path)
    video.close()
    return audio_path


def convert_audio(input_path, output_format="wav"):
    output_path = os.path.splitext(input_path)[0] + "." + output_format
    audio = AudioSegment.from_file(input_path)
    audio.export(output_path, format=output_format)
    return output_path
