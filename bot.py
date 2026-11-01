import asyncio
import io
import logging
import os
import sqlite3
from typing import Any

import requests
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler,
    ContextTypes, filters
)

load_dotenv()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
XI_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
DEFAULT_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
OWNER_ID = os.getenv("OWNER_ID", "").strip()
MAX_TEXT_CHARS = max(100, min(int(os.getenv("MAX_TEXT_CHARS", "2500")), 5000))
BRAND_NAME = os.getenv("BOT_BRAND_NAME", "VoicePro Bot").strip()[:64]
DB_PATH = os.getenv("VOICE_DB_PATH", "voicepro.sqlite3")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("voicepro-bot")
PAGE_SIZE = 8
SAMPLE_TEXT = "مرحباً بك! هذا مثال لتجربة الصوت قبل اختياره."


def db_init() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY, voice_id TEXT NOT NULL
        )""")


def save_voice(user_id: int, voice_id: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO user_settings(user_id, voice_id) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET voice_id=excluded.voice_id",
            (user_id, voice_id)
        )


def load_voice(user_id: int) -> str:
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT voice_id FROM user_settings WHERE user_id=?", (user_id,)
        ).fetchone()
    return row[0] if row else DEFAULT_VOICE


def authorized(update: Update) -> bool:
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
            data = response.json()
            detail = data.get("detail", data)
            if response.status_code == 402:
                raise RuntimeError(
                    "الخطة أو الرصيد لا يسمح باستخدام هذا الصوت عبر API. "
                    "جرّب صوتاً آخر متاحاً لحسابك."
                )
            if response.status_code == 401:
                raise RuntimeError("مفتاح ElevenLabs غير صحيح أو تم إلغاؤه.")
            if response.status_code == 422:
                raise RuntimeError("إعدادات الصوت أو النص غير مقبولة من ElevenLabs.")
            raise RuntimeError(f"خطأ ElevenLabs ({response.status_code}): {detail}")
        except ValueError:
            raise RuntimeError(f"خطأ ElevenLabs ({response.status_code}).")
    return response


def get_voices() -> list[dict[str, Any]]:
    response = elevenlabs_request(
        "GET", "https://api.elevenlabs.io/v1/voices", headers=api_headers()
    )
    voices = response.json().get("voices", [])
    # Library voices are excluded: ElevenLabs may list them even when a free API
    # account is not entitled to synthesize them.
    return [v for v in voices if str(v.get("category", "")).lower() != "library"]


def synthesize(text: str, voice_id: str) -> bytes:
    response = elevenlabs_request(
        "POST", f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": XI_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        },
        json={"text": text, "model_id": MODEL_ID, "language_code": "ar"},
        params={"output_format": "mp3_44100_128"}
    )
    return response.content


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙️ تحويل النص إلى صوت", callback_data="convert"),
         InlineKeyboardButton("🎧 اختيار الصوت", callback_data="voices:0")],
        [InlineKeyboardButton("🔊 تجربة الصوت الحالي", callback_data="preview"),
         InlineKeyboardButton("⚙️ إعداداتي", callback_data="settings")],
        [InlineKeyboardButton("❓ طريقة الاستخدام", callback_data="help"),
         InlineKeyboardButton("ℹ️ عن البوت", callback_data="about")]
    ])


def home_text() -> str:
    return (
        f"👑 أهلاً بك في {BRAND_NAME}!\n\n"
        "حوّل كلامك العربي إلى ملف صوتي MP3 بسهولة.\n"
        "اختر زرّاً من القائمة، أو أرسل النص مباشرة بعد تحديد الصوت.\n\n"
        "✨ واجهة بسيطة • اختيار صوت بالأزرار • حفظ اختيارك"
    )


async def deny(update: Update) -> bool:
    if authorized(update):
        return False
    if update.effective_message:
        await update.effective_message.reply_text("هذا البوت خاص بصاحبه.")
    return True


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny(update):
        return
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(home_text(), reply_markup=home_keyboard())
    else:
        await update.effective_message.reply_text(home_text(), reply_markup=home_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("waiting_for_text", None)
    await show_home(update, context)


async def show_voices(target, context: ContextTypes.DEFAULT_TYPE, user_id: int, page: int = 0) -> None:
    try:
        voices = await asyncio.to_thread(get_voices)
    except Exception as exc:
        log.warning("Voice list error: %s", exc)
        await target.reply_text(
            "لم أستطع جلب الأصوات الآن. تأكد من صلاحية Voices Read في مفتاح ElevenLabs."
        )
        return
    if not voices:
        await target.reply_text(
            "لم أجد أصواتاً غير مصنفة كأصوات مكتبة في حسابك. "
            "أضف أو أنشئ صوتاً متاحاً للـAPI في ElevenLabs ثم أعد المحاولة."
        )
        return
    total_pages = (len(voices) + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    selected = load_voice(user_id)
    rows = []
    for index, voice in enumerate(voices[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], start=page * PAGE_SIZE):
        voice_id = str(voice.get("voice_id", ""))
        name = str(voice.get("name", "صوت بدون اسم"))[:45]
        category = str(voice.get("category", ""))
        mark = " ✅" if voice_id == selected else ""
        rows.append([InlineKeyboardButton(
            f"{name}{mark}", callback_data=f"select:{index}:{page}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"voices:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"voices:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")])
    context.user_data["voice_cache"] = voices
    await target.reply_text(
        "🎧 اختر الصوت الذي يعجبك بالضغط على اسمه.\n"
        "الأصوات المصنفة كمكتبة عامة مخفية لتجنب خطأ الخطة المجانية.\n"
        "بعد الاختيار يمكنك تجربة الصوت.",
        reply_markup=InlineKeyboardMarkup(rows)
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if await deny(update):
        await query.answer()
        return
    data = query.data or ""
    await query.answer()
    if data == "noop":
        return
    if data == "home":
        context.user_data.pop("waiting_for_text", None)
        await query.message.reply_text(home_text(), reply_markup=home_keyboard())
    elif data.startswith("voices:"):
        await show_voices(query.message, context, query.from_user.id, int(data.split(":")[1]))
    elif data.startswith("select:"):
        try:
            _, raw_index, raw_page = data.split(":")
            voices = context.user_data.get("voice_cache") or await asyncio.to_thread(get_voices)
            index = int(raw_index)
            voice = voices[index]
            voice_id = str(voice["voice_id"])
            save_voice(query.from_user.id, voice_id)
            await query.message.reply_text(
                f"✅ تم اختيار: {voice.get('name', 'الصوت')}\n"
                "اضغط تجربة الصوت أو أرسل النص الذي تريد تحويله.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔊 تجربة الصوت", callback_data="preview")],
                    [InlineKeyboardButton("🎧 تغيير الصوت", callback_data=f"voices:{raw_page}")],
                    [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
                ])
            )
        except Exception:
            await query.message.reply_text("تعذّر اختيار الصوت. افتح قائمة الأصوات وحاول مجدداً.")
    elif data == "convert":
        context.user_data["waiting_for_text"] = True
        await query.message.reply_text(
            f"✍️ أرسل النص الآن، وسأحوّله إلى MP3.\nالحد الأقصى: {MAX_TEXT_CHARS} حرف."
        )
    elif data == "preview":
        voice_id = load_voice(query.from_user.id)
        if not voice_id:
            await query.message.reply_text("اختر صوتاً أولاً من زر «اختيار الصوت».")
            return
        await make_audio(query.message, SAMPLE_TEXT, voice_id, preview=True)
    elif data == "settings":
        voice_id = load_voice(query.from_user.id)
        await query.message.reply_text(
            f"⚙️ إعداداتك\nالصوت الحالي: {'محدد' if voice_id else 'لم تختر صوتاً بعد'}\n"
            f"الحد الأقصى للنص: {MAX_TEXT_CHARS} حرف.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎧 تغيير الصوت", callback_data="voices:0")],
                [InlineKeyboardButton("🔊 تجربة الصوت", callback_data="preview")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
    elif data == "help":
        await query.message.reply_text(
            "📌 طريقة الاستخدام:\n1) اختر «اختيار الصوت».\n"
            "2) اضغط على الصوت المناسب.\n3) أرسل نصك أو اضغط «تحويل النص إلى صوت».\n"
            "4) استلم ملف MP3.\n\n"
            "ملاحظة: التحويل وتجربة الصوت قد يستهلكان رصيد ElevenLabs حسب خطتك."
        )
    elif data == "about":
        await query.message.reply_text(
            f"🎙️ {BRAND_NAME}\nبوت لتحويل النصوص إلى ملفات MP3 باستخدام ElevenLabs.\n"
            "توفّر الأصوات والتحويل يعتمد على صلاحيات وخطة حساب ElevenLabs."
        )


async def make_audio(message, text: str, voice_id: str, preview: bool = False) -> None:
    status = await message.reply_text("⏳ جارٍ تجهيز الصوت...")
    try:
        audio = await asyncio.to_thread(synthesize, text, voice_id)
        stream = io.BytesIO(audio)
        stream.name = "voice_preview.mp3" if preview else "voicepro.mp3"
        await message.reply_audio(
            audio=stream,
            title="تجربة الصوت" if preview else "الصوت الناتج",
            caption="🔊 عينة تجريبية" if preview else "✅ تم تحويل النص بنجاح"
        )
        await status.delete()
    except Exception as exc:
        log.exception("TTS failed")
        detail = str(exc)
        await status.edit_text(
            "⚠️ لم يتم إنشاء الصوت.\n" + detail[:350] +
            "\n\nيمكنك اختيار صوت آخر من القائمة. لا يتم عرض مفاتيحك السرية هنا."
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny(update):
        return
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return
    if len(text) > MAX_TEXT_CHARS:
        await message.reply_text(
            f"النص طويل. الحد الأقصى {MAX_TEXT_CHARS} حرفاً. أرسله على أجزاء."
        )
        return
    voice_id = load_voice(update.effective_user.id)
    if not voice_id:
        await message.reply_text(
            "🎧 قبل التحويل، اختر صوتاً من القائمة:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("اختيار الصوت الآن", callback_data="voices:0")]
            ])
        )
        return
    context.user_data["waiting_for_text"] = False
    await make_audio(message, text, voice_id)


async def post_init(app: Application) -> None:
    db_init()
    await app.bot.set_my_name(BRAND_NAME)
    await app.bot.set_my_description(
        "حوّل النص العربي إلى صوت MP3 بسهولة. اختر صوتك بالأزرار واستلم ملفك الصوتي."
    )
    await app.bot.set_my_short_description("تحويل النص العربي إلى صوت MP3 🎙️")
    await app.bot.set_my_commands([
        BotCommand("start", "فتح القائمة الرئيسية"),
        BotCommand("help", "طريقة الاستخدام")
    ])


def main() -> None:
    if not TG_TOKEN or not XI_KEY:
        raise SystemExit("أضف TELEGRAM_BOT_TOKEN و ELEVENLABS_API_KEY في ملف .env.")
    app = Application.builder().token(TG_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", lambda u, c: show_home(u, c)))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    log.info("VoicePro bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
