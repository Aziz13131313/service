from moviepy.video.io.VideoFileClip import VideoFileClip

def convert_video_to_audio(video_path, output_format="wav"):
    audio_path = "temp_audio." + output_format
    video = VideoFileClip(video_path)
    audio = video.audio
    audio.write_audiofile(audio_path)  # ДОЛЖНО идти до return!
    video.close()
    return audio_path
