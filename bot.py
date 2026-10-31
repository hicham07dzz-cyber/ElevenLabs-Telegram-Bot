import io
import logging
import os
import asyncio
from typing import Any

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

load_dotenv()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
XI_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
DEFAULT_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
OWNER_ID = os.getenv("OWNER_ID", "").strip()
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "2500"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("arabic-tts-bot")


def authorized(update: Update) -> bool:
    """If OWNER_ID is set, only that Telegram account can use the bot."""
    if not OWNER_ID:
        return True
    user = update.effective_user
    return bool(user and str(user.id) == OWNER_ID)


def api_headers() -> dict[str, str]:
    return {"xi-api-key": XI_KEY, "Accept": "application/json"}


def elevenlabs_request(method: str, url: str, **kwargs: Any) -> requests.Response:
    response = requests.request(method, url, timeout=90, **kwargs)
    if not response.ok:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:300]
        raise RuntimeError(f"ElevenLabs returned HTTP {response.status_code}: {body}")
    return response


def get_voices() -> list[dict[str, Any]]:
    response = elevenlabs_request(
        "GET", "https://api.elevenlabs.io/v1/voices", headers=api_headers()
    )
    return response.json().get("voices", [])


def synthesize(text: str, voice_id: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": XI_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {"text": text, "model_id": MODEL_ID, "language_code": "ar"}
    response = elevenlabs_request(
        "POST", url, headers=headers, json=payload,
        params={"output_format": "mp3_44100_128"}
    )
    return response.content


async def deny_if_unauthorized(update: Update) -> bool:
    if authorized(update):
        return False
    if update.effective_message:
        await update.effective_message.reply_text("هذا البوت خاص بصاحبه.")
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_unauthorized(update):
        return
    await update.effective_message.reply_text(
        "أهلاً بك! أرسل نصاً بالعربية وسأحوّله إلى ملف MP3.\n\n"
        "الأوامر:\n"
        "/voices — عرض الأصوات المتاحة في حسابك\n"
        "/setvoice ID — اختيار صوت\n"
        "/voice — معرفة الصوت الحالي\n"
        "/help — المساعدة\n\n"
        "ملاحظة: التحويل يستهلك رصيد ElevenLabs."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_unauthorized(update):
        return
    await update.effective_message.reply_text(
        "أرسل النص مباشرة وسأعيده لك كملف MP3.\n"
        "لعرض الأصوات: /voices\n"
        "لاختيار صوت: /setvoice VOICE_ID\n"
        f"الحد الحالي للنص: {MAX_TEXT_CHARS} حرف."
    )


async def voices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_unauthorized(update):
        return
    status = await update.effective_message.reply_text(
        "⏳ أجلب الأصوات من حساب ElevenLabs..."
    )
    try:
        voices = await asyncio.to_thread(get_voices)
        if not voices:
            await status.edit_text("لم أجد أصواتاً متاحة في حسابك.")
            return
        lines = []
        for voice in voices[:35]:
            name = str(voice.get("name", "بدون اسم"))
            voice_id = str(voice.get("voice_id", ""))
            language = (voice.get("labels") or {}).get("language", "")
            lines.append(
                f"• {name}{' (' + language + ')' if language else ''}\n`{voice_id}`"
            )
        await status.edit_text(
            "الأصوات المتاحة (حتى 35 صوتاً):\n\n" + "\n\n".join(lines) +
            "\n\nلاختيار صوت انسخ معرّفه وأرسل:\n/setvoice VOICE_ID",
            parse_mode="Markdown"
        )
    except Exception:
        log.exception("Could not list voices")
        await status.edit_text(
            "تعذّر جلب الأصوات. تحقق من مفتاح API وصلاحية Voices."
        )


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_unauthorized(update):
        return
    current = context.application.bot_data.get("voice_id", DEFAULT_VOICE)
    await update.effective_message.reply_text(
        f"الصوت الحالي:\n{current or 'لم يتم اختياره'}"
    )


async def setvoice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_unauthorized(update):
        return
    if not context.args:
        await update.effective_message.reply_text("استخدم: /setvoice VOICE_ID")
        return
    context.application.bot_data["voice_id"] = context.args[0].strip()
    await update.effective_message.reply_text(
        "تم اختيار الصوت. جرّب إرسال نص عربي الآن."
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_unauthorized(update):
        return
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return
    if len(text) > MAX_TEXT_CHARS:
        await message.reply_text(
            f"النص طويل. الحد الأقصى حالياً {MAX_TEXT_CHARS} حرفاً؛ أرسله على أجزاء."
        )
        return
    voice_id = context.application.bot_data.get("voice_id", DEFAULT_VOICE)
    if not voice_id:
        await message.reply_text(
            "لم تختر صوتاً بعد. أرسل /voices ثم اختر صوتاً عبر /setvoice ID."
        )
        return

    status = await message.reply_text("⏳ جارٍ تحويل النص إلى صوت...")
    try:
        audio = await asyncio.to_thread(synthesize, text, voice_id)
        stream = io.BytesIO(audio)
        stream.name = "arabic_voice.mp3"
        await message.reply_audio(
            audio=stream, title="Arabic text to speech",
            caption="تم إنشاء الصوت بواسطة ElevenLabs"
        )
        await status.delete()
    except Exception as exc:
        log.exception("Text-to-speech failed")
        detail = str(exc)
        if len(detail) > 500:
            detail = detail[:500]
        await status.edit_text(
            "تعذّر إنشاء الصوت.\n"
            "تحقق من رصيد ElevenLabs وصلاحية المفتاح ومعرّف الصوت.\n"
            f"التفاصيل: {detail}"
        )


def main() -> None:
    missing = []
    if not TG_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not XI_KEY:
        missing.append("ELEVENLABS_API_KEY")
    if missing:
        raise SystemExit("أضف هذه القيم في ملف .env: " + ", ".join(missing))

    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("voices", voices_command))
    app.add_handler(CommandHandler("voice", voice_command))
    app.add_handler(CommandHandler("setvoice", setvoice_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    log.info("Bot started. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
