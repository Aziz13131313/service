
import telebot
import os
from convert import convert_video_to_audio
from whisper_utils import transcribe_audio
from evaluate import evaluate_script

# Токен Telegram-бота
TOKEN = "7851015115:AAHj83iRYLsUrGmk8QC36SrrqPik4NOlOpo"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(content_types=['video', 'document', 'voice', 'audio'])
def handle_media(message):
    file_id = message.video.file_id if message.video else message.document.file_id if message.document else message.voice.file_id if message.voice else message.audio.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    input_ext = file_info.file_path.split('.')[-1]
    base_filename = f"media_{message.chat.id}"
    video_path = f"{base_filename}.{input_ext}"
    audio_path = f"{base_filename}.wav"

    with open(video_path, 'wb') as f:
        f.write(downloaded_file)

    try:
        convert_video_to_audio(video_path, audio_path)
        transcript = transcribe_audio(audio_path)
        score, total = evaluate_script(transcript)

        result = f"🧾 Распознанный текст:\n{transcript}\n\n📊 Оценка по 5 столпам:\n"
        for k, v in score.items():
            result += f"{k}: {'✅' if v else '❌'}\n"
        result += f"\n⭐ Общая оценка: {total}/5"

        bot.send_message(message.chat.id, result)
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка обработки: {str(e)}")

bot.polling()
