from pathlib import Path
import uuid, re
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs import save
from gtts import gTTS
import config

client = ElevenLabs(api_key=config.elevenlabs_api_key)

def list_voices():
    resp = client.voices.search()
    return [{"name": v.name, "id": v.voice_id} for v in resp.voices]

def _fallback_gtts(text: str) -> str:
    lang = "ru" if re.search(r"[А-Яа-яЁё]", text) else "en"
    filename = f"audio_{uuid.uuid4().hex}.mp3"
    gTTS(text=text, lang=lang).save(filename)
    return str(Path(filename).resolve())

def tts_to_file(text: str,
                voice_id: str,
                model_id: str = "eleven_multilingual_v2",
                output_format: str = "mp3_44100_128") -> str:
    try:
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )
        filename = f"audio_{uuid.uuid4().hex}.mp3"
        save(audio, filename)
        return str(Path(filename).resolve())
    except ApiError as e:
        # quota_exceeded или иные ошибки доступа → резервный канал
        return _fallback_gtts(text)
