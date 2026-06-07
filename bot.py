import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN
from permissions import is_admin_or_owner
from ai_model import ask_ai

BOT_USERNAME = ""

async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    entities = message.entities or message.caption_entities
    if not entities:
        return

    # التحقق من وجود منشن للبوت
    bot_mentioned = False
    for entity in entities:
        if entity.type == "mention":
            mention_text = message.text[entity.offset:entity.offset + entity.length]
            if mention_text.lower() == f"@{BOT_USERNAME.lower()}":
                bot_mentioned = True
                break
    if not bot_mentioned:
        return

    # التحقق من الصلاحية
    if not await is_admin_or_owner(update, context):
        await message.reply_text("🚫 هذا الأمر متاح فقط لمالك المجموعة والمشرفين.")
        return

    # استخراج النص بعد المنشن
    text_after_mention = ""
    for entity in entities:
        if entity.type == "mention":
            mention_text = message.text[entity.offset:entity.offset + entity.length]
            if mention_text.lower() == f"@{BOT_USERNAME.lower()}":
                start = entity.offset + entity.length
                text_after_mention = message.text[start:].strip()
                break

    if not text_after_mention:
        await message.reply_text("❓ اكتب أمراً بعد المنشن، مثال: @MyAdminBot لخص آخر 10 رسائل.")
        return

    await message.reply_chat_action("typing")
    reply = await ask_ai(text_after_mention)
    await message.reply_text(reply)

async def post_init(application: Application):
    global BOT_USERNAME
    me = await application.bot.get_me()
    BOT_USERNAME = me.username
    print(f"🤖 @{BOT_USERNAME} جاهز")

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mention))
    print("🚀 البوت يعمل محليًا...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
