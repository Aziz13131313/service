from moviepy.editor import VideoFileClip

def convert_video_to_audio(video_path, output_format="mp3"):
    audio_path = "temp_audio." + output_format
    video = VideoFileClip(video_path)
    audio = video.audio
    audio.write_audiofile(audio_path, codec='libmp3lame')
    video.close()
    return audio_path

