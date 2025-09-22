import os
import re
import time
import telebot
import config
import voice

bot = telebot.TeleBot(config.bot_token)

def refresh_voices():
    try:
        return voice.list_voices()  # [{'name': str, 'id': str}, ...]
    except Exception as err:
        print(f"[voices] fetch error: {err}")
        return []

VOICES = refresh_voices()
selected_voice_id = {}   # user_id -> voice_id
user_mode = {}           # user_id -> 'auto' | 'single' | 'batch'  (default: 'auto')


def build_inline_kb(voices):
    kb = telebot.types.InlineKeyboardMarkup()
    row = []
    for v in voices:
        btn = telebot.types.InlineKeyboardButton(text=v["name"], callback_data=f"voice:{v['id']}")
        row.append(btn)
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    return kb


def has_multiple_segments(text: str) -> bool:
    if len(re.findall(r"(?m)^\s*\d+\)\s", text)) >= 2:
        return True
    if len([p for p in re.split(r"\n{2,}", text) if p.strip()]) >= 2:
        return True
    return False


def split_segments(text: str) -> list[str]:
    # 1) Пытаться по нумерованным пунктам: 1) ..., 2) ...
    m = list(re.finditer(r"(?m)^\s*(\d+)\)\s", text))
    if len(m) >= 2:
        idxs = [mi.start() for mi in m] + [len(text)]
        segs = [text[idxs[i]:idxs[i+1]].strip() for i in range(len(idxs)-1)]
        return [s for s in segs if s]
    # 2) Иначе — по пустым строкам
    segs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return segs


@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(
        message,
        "Команды: /voices — выбор голоса, /mode_auto, /mode_single, /mode_batch. Пришлите текст."
    )


@bot.message_handler(commands=['voices'])
def list_voices_cmd(message):
    global VOICES
    VOICES = refresh_voices()
    if not VOICES:
        bot.reply_to(message, "Голоса недоступны.")
        return
    bot.send_message(message.chat.id, "Выберите голос:", reply_markup=build_inline_kb(VOICES))


@bot.message_handler(commands=['mode_auto'])
def mode_auto(message):
    user_mode[message.from_user.id] = 'auto'
    bot.reply_to(message, "Режим: auto (несколько файлов, если текст разбит на части).")


@bot.message_handler(commands=['mode_single'])
def mode_single(message):
    user_mode[message.from_user.id] = 'single'
    bot.reply_to(message, "Режим: single (всегда один MP3-файл).")


@bot.message_handler(commands=['mode_batch'])
def mode_batch(message):
    user_mode[message.from_user.id] = 'batch'
    bot.reply_to(message, "Режим: batch (разбивать текст и отправлять несколько MP3-файлов).")


@bot.callback_query_handler(func=lambda c: c.data.startswith("voice:"))
def choose_voice_cb(call):
    vid = call.data.split(":", 1)[1]
    selected_voice_id[call.from_user.id] = vid
    bot.answer_callback_query(call.id, "Голос выбран")
    try:
        bot.edit_message_text("Голос выбран. Пришлите текст.", call.message.chat.id, call.message.message_id)
    except Exception as err:
        print(f"[callback edit] {err}")


@bot.message_handler(content_types=['text'])
def tts(message):
    txt = (message.text or "").strip()
    if not txt:
        bot.reply_to(message, "Пустой текст.")
        return

    uid = message.from_user.id
    mode = user_mode.get(uid, 'auto')

    # Определить voice_id (или None -> fallback внутри voice.py)
    vid = None
    if VOICES:
        vid = selected_voice_id.get(uid, VOICES[0]["id"])

    # Выбор однофайлового или пакетного режима
    do_batch = (mode == 'batch') or (mode == 'auto' and has_multiple_segments(txt))
    if not do_batch:
        audio_file = None
        try:
            audio_file = voice.tts_to_file(txt, vid) if vid else voice._fallback_gtts(txt)  # noqa: SLF001
            with open(audio_file, "rb") as f:
                bot.send_audio(message.chat.id, f)
        except Exception as err:
            bot.reply_to(message, f"Ошибка синтеза: {err}")
        finally:
            if audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except Exception as rm_err:
                    print(f"[cleanup] {rm_err}")
        return

    # Пакетный режим: разбиваем текст и шлём несколько MP3
    segments = split_segments(txt)[:12]  # ограничим до 12 частей на сообщение
    if not segments:
        bot.reply_to(message, "Не удалось разбить текст.")
        return

    for i, seg in enumerate(segments, 1):
        audio_file = None
        try:
            audio_file = voice.tts_to_file(seg, vid) if vid else voice._fallback_gtts(seg)  # noqa: SLF001
            caption = f"Часть {i}/{len(segments)}"
            with open(audio_file, "rb") as f:
                bot.send_audio(message.chat.id, f, caption=caption)
            time.sleep(0.3)  # мягкая задержка между отправками
        except Exception as err:
            bot.send_message(message.chat.id, f"Ошибка синтеза в части {i}: {err}")
        finally:
            if audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except Exception as rm_err:
                    print(f"[cleanup] {rm_err}")


if __name__ == "__main__":
    print(f"VOICES loaded: {len(VOICES)}")
    try:
        bot.remove_webhook()
    except Exception as err:
        print(f"[remove_webhook] {err}")
    bot.polling(none_stop=True, interval=0)
