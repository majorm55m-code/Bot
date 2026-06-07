import os
import logging
import re
import requests
from typing import Dict, List, Optional, Tuple
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ChatPermissions, ChatMemberAdministrator, ChatMemberOwner
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from telegram.constants import ChatMemberStatus, ChatType
from llama_cpp import Llama
from bs4 import BeautifulSoup
import html

# ==================== التسجيل ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== الإعدادات ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL_REPO = os.getenv("MODEL_REPO", "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF")
MODEL_FILE = os.getenv("MODEL_FILE", "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.6"))
N_THREADS = int(os.getenv("N_THREADS", "4"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN غير محدد!")

# ==================== تحميل النموذج ====================
logger.info("🔄 جاري تحميل DeepSeek-R1 Distill...")
try:
    llm = Llama.from_pretrained(
        repo_id=MODEL_REPO,
        filename=MODEL_FILE,
        n_ctx=4096,
        verbose=False,
        n_threads=N_THREADS,
    )
    logger.info("✅ تم تحميل DeepSeek-R1 بنجاح!")
except Exception as e:
    logger.error(f"❌ فشل تحميل النموذج: {e}")
    raise

# ==================== إدارة المحادثات ====================
class ConversationManager:
    def __init__(self):
        self._store: Dict[int, List[dict]] = {}
    
    def get_or_create(self, user_id: int) -> List[dict]:
        if user_id not in self._store:
            self._store[user_id] = []
        return self._store[user_id]
    
    def clear(self, user_id: int):
        self._store[user_id] = []
    
    def add_message(self, user_id: int, role: str, content: str):
        conv = self.get_or_create(user_id)
        conv.append({"role": role, "content": content})
        if len(conv) > MAX_HISTORY:
            self._store[user_id] = conv[-MAX_HISTORY:]
    
    def get_messages(self, user_id: int) -> List[dict]:
        return self.get_or_create(user_id)

conv_manager = ConversationManager()

# ==================== التحقق من الصلاحيات ====================
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"خطأ في التحقق من الصلاحيات: {e}")
        return False

async def is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status == ChatMemberStatus.OWNER
    except Exception as e:
        logger.error(f"خطأ في التحقق من المالك: {e}")
        return False

async def can_bot_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.effective_chat.id
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            return False
        if hasattr(bot_member, 'can_delete_messages'):
            return bot_member.can_delete_messages
        return True
    except Exception as e:
        logger.error(f"خطأ في التحقق من صلاحيات البوت: {e}")
        return False

# ==================== أدوات البحث والصور ====================
class ToolExecutor:
    @staticmethod
    def search(query: str) -> str:
        try:
            logger.info(f"🔍 البحث عن: {query}")
            url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            results = []
            for result in soup.select(".result")[:5]:
                title_tag = result.select_one(".result__a")
                snippet_tag = result.select_one(".result__snippet")
                if title_tag and snippet_tag:
                    title = html.unescape(title_tag.get_text(strip=True))
                    snippet = html.unescape(snippet_tag.get_text(strip=True))
                    results.append(f"• {title}: {snippet}")
            
            return "\n".join(results) if results else "لم يتم العثور على نتائج."
        except Exception as e:
            return f"خطأ في البحث: {str(e)}"
    
    @staticmethod
    def generate_image(prompt: str) -> str:
        try:
            encoded = requests.utils.quote(prompt)
            return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed=42"
        except Exception as e:
            return None

tool_executor = ToolExecutor()

# ==================== تنسيق DeepSeek-R1 ====================
SYSTEM_PROMPT = """أنت بوت إدارة ذكي للمجموعات والقنوات على Telegram. لديك القدرة على:

1. فهم الأوامر الطبيعية وتنفيذها (حذف، طرد، حظر، تثبيت، كتم، تحذير)
2. البحث على الإنترنت باستخدام: [SEARCH:الاستعلام]
3. توليد الصور باستخدام: [IMAGE:وصف الصورة]

قواعد مهمة:
- تنفذ الأوامر فقط إذا كان المرسل مشرفاً أو مالك المجموعة
- ترد بأدب واحترافية
- تشرح ما فعلته بعد تنفيذ الأمر
- تستخدم اللغة العربية أو الإنجليزية حسب لغة المستخدم

أوامر الإدارة المتاحة:
- حذف/مسح/احذف: حذف رسالة
- طرد/إزالة/اطرد: طرد عضو من المجموعة
- حظر/بان/احظر: حظر عضو نهائياً
- فك_حظر/فك_الحظر: فك حظر عضو
- كتم/سكوت/اكتم: كتم عضو
- فك_كتم/فك_الكتم: فك كتم عضو
- تثبيت/ثبت/pin: تثبيت رسالة
- تحذير/إنذار/حذر: إعطاء تحذير لعضو"""

def build_deepseek_prompt(messages: List[dict]) -> str:
    prompt = "<｜begin▁of▁sentence｜>"
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            prompt += f"{content}"
        elif role == "user":
            prompt += f"<｜User｜>{content}"
        elif role in ("model", "assistant"):
            prompt += f"<｜Assistant｜>{content}"
    prompt += "<｜Assistant｜>"
    return prompt

def extract_think_and_answer(text: str) -> Tuple[str, str]:
    think_match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        answer = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return thinking, answer
    return "", text

# ==================== أوامر الإدارة الذكية ====================
async def execute_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                  command_type: str, target_user_id: int = None, 
                                  reason: str = "") -> str:
    chat_id = update.effective_chat.id
    message = update.effective_message
    
    try:
        if command_type == "delete":
            if message.reply_to_message:
                await message.reply_to_message.delete()
                return "✅ تم حذف الرسالة بنجاح."
            else:
                await message.delete()
                return "✅ تم حذف الرسالة."
        
        elif command_type == "kick":
            if target_user_id:
                await context.bot.ban_chat_member(chat_id, target_user_id)
                await context.bot.unban_chat_member(chat_id, target_user_id)
                return f"✅ تم طرد العضو. {reason}"
            return "❌ لم يتم تحديد العضو."
        
        elif command_type == "ban":
            if target_user_id:
                await context.bot.ban_chat_member(chat_id, target_user_id)
                return f"🚫 تم حظر العضو نهائياً. {reason}"
            return "❌ لم يتم تحديد العضو."
        
        elif command_type == "unban":
            if target_user_id:
                await context.bot.unban_chat_member(chat_id, target_user_id)
                return f"🔓 تم فك حظر العضو. {reason}"
            return "❌ لم يتم تحديد العضو."
        
        elif command_type == "mute":
            if target_user_id:
                permissions = ChatPermissions(can_send_messages=False)
                await context.bot.restrict_chat_member(chat_id, target_user_id, permissions)
                return f"🔇 تم كتم العضو. {reason}"
            return "❌ لم يتم تحديد العضو."
        
        elif command_type == "unmute":
            if target_user_id:
                permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
                await context.bot.restrict_chat_member(chat_id, target_user_id, permissions)
                return f"🔊 تم فك كتم العضو. {reason}"
            return "❌ لم يتم تحديد العضو."
        
        elif command_type == "pin":
            if message.reply_to_message:
                await context.bot.pin_chat_message(chat_id, message.reply_to_message.message_id)
                return "📌 تم تثبيت الرسالة."
            return "❌ قم بالرد على الرسالة التي تريد تثبيتها."
        
        elif command_type == "warn":
            if target_user_id:
                return f"⚠️ تحذير للعضو! {reason}"
            return "❌ لم يتم تحديد العضو."
        
        else:
            return "❌ أمر غير معروف."
            
    except Exception as e:
        logger.error(f"خطأ في تنفيذ الأمر {command_type}: {e}")
        return f"❌ فشل في تنفيذ الأمر: {str(e)}"

# ==================== فهم الأوامر الطبيعية ====================
async def parse_natural_command(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[Tuple[str, int, str]]:
    target_user_id = None
    if update.effective_message.reply_to_message:
        target_user_id = update.effective_message.reply_to_message.from_user.id
    
    username_match = re.search(r"@(\w+)", text)
    if username_match and not target_user_id:
        username = username_match.group(1)
        try:
            chat_members = await context.bot.get_chat_administrators(update.effective_chat.id)
            for member in chat_members:
                if member.user.username == username:
                    target_user_id = member.user.id
                    break
        except:
            pass
    
    text_lower = text.lower()
    
    commands = {
        "delete": ["احذف", "حذف", "امسح", "مسح", "delete", "remove"],
        "kick": ["اطرد", "طرد", "إزالة", "ازالة", "kick", "remove user"],
        "ban": ["احظر", "حظر", "بان", "ban", "block"],
        "unban": ["فك الحظر", "فك_الحظر", "فك حظر", "unban", " unblock"],
        "mute": ["اكتم", "كتم", "اسكت", "سكوت", "mute", "silence"],
        "unmute": ["فك الكتم", "فك_الكتم", "فك كتم", "unmute"],
        "pin": ["ثبت", "تثبيت", "pin", "fix"],
        "warn": ["حذر", "تحذير", "إنذار", "انذار", "warn", "warning"]
    }
    
    detected_command = None
    for cmd, keywords in commands.items():
        if any(kw in text_lower for kw in keywords):
            detected_command = cmd
            break
    
    if detected_command:
        return (detected_command, target_user_id, "")
    
    return None

# ==================== معالجات الأوامر ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conv_manager.clear(user_id)
    conv_manager.add_message(user_id, "system", SYSTEM_PROMPT)
    
    welcome = """
🤖 **بوت إدارة المجموعات - DeepSeek-R1**

👋 مرحباً! أنا بوت إدارة ذكي للمجموعات والقنوات.

✨ **المميزات:**
• 🧠 فهم الأوامر الطبيعية بالعربية والإنجليزية
• 👮‍♂️ إدارة المجموعات (حذف، طرد، حظر، كتم، تثبيت)
• 🔍 بحث على الإنترنت
• 🎨 توليد الصور

📌 **كيفية الاستخدام:**
1. اجعلني **مشرفاً** في المجموعة
2. اذكرني بـ @ أو رد على رسالتي
3. أرسل أمراً طبيعياً مثل:
   - "@botname احذف هذه الرسالة"
   - "@botname اطرد هذا المستخدم"
   - "@botname ثبت الرسالة"

⚠️ **أنفذ الأوامر فقط من المشرفين والمالك!**

📝 أرسل /help للمزيد من المعلومات.
    """
    await update.message.reply_text(welcome, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📋 **دليل استخدام بوت الإدارة**

**🛠 أوامر الإدارة (للمشرفين فقط):**

🗑 **الحذف:**
• "@bot احذف هذه الرسالة"
• "@bot امسح الرسالة"
• (مع الرد على الرسالة)

👢 **الطرد:**
• "@bot اطرد @username"
• "@bot طرد هذا المستخدم"
• (مع الرد على رسالة العضو)

🚫 **الحظر:**
• "@bot احظر @username"
• "@bot بان هذا المستخدم"

🔇 **الكتم:**
• "@bot اكتم @username"
• "@bot سكت هذا المستخدم"

🔊 **فك الكتم:**
• "@bot فك الكتم @username"

📌 **التثبيت:**
• "@bot ثبت الرسالة"
• "@bot pin"
• (مع الرد على الرسالة)

⚠️ **التحذير:**
• "@bot حذر @username"
• "@bot تحذير لهذا المستخدم"

**🔍 أوامر عامة:**
/search استعلام - بحث على الإنترنت
/image وصف - توليد صورة

**💡 ملاحظات:**
• يجب أن أكون مشرفاً في المجموعة
• الأوامر تنفذ فقط من المشرفين والمالك
• يمكنك استخدام الرد على الرسائل بدلاً من @username
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("🔍 استخدم: /search استعلام البحث")
        return
    
    await update.message.chat.send_action(action="typing")
    results = tool_executor.search(query)
    await update.message.reply_text(f"🔍 **نتائج البحث:**\n\n{results}", parse_mode="Markdown")

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("🎨 استخدم: /image وصف الصورة")
        return
    
    await update.message.chat.send_action(action="upload_photo")
    image_url = tool_executor.generate_image(prompt)
    if image_url:
        await update.message.reply_photo(photo=image_url, caption=f"🎨 **الصورة:** {prompt}")
    else:
        await update.message.reply_text("❌ فشل في توليد الصورة.")

# ==================== معالج الرسائل في المجموعات ====================
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    
    if not message or not chat:
        return
    
    # التحقق من أن البوت مشرف
    if not await can_bot_admin(update, context):
        return
    
    # التحقق من أن المرسل مشرف
    if not await is_admin(update, context):
        return
    
    # التحقق من أن الرسالة تذكر البوت أو رد على رسالته
    bot_mentioned = False
    
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mention_text = message.text[entity.offset:entity.offset + entity.length]
                if BOT_USERNAME and mention_text.lower() == f"@{BOT_USERNAME.lower()}":
                    bot_mentioned = True
                    break
    
    if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
        bot_mentioned = True
    
    if not bot_mentioned and message.text:
        text_lower = message.text.lower()
        if BOT_USERNAME and f"@{BOT_USERNAME.lower()}" in text_lower:
            bot_mentioned = True
    
    if not bot_mentioned:
        return
    
    # إزالة اسم البوت من النص
    user_text = message.text
    if BOT_USERNAME:
        user_text = re.sub(rf"@{BOT_USERNAME}\s*", "", user_text, flags=re.IGNORECASE).strip()
    
    logger.info(f"👮 أمر إدارة من {user.username or user.id}: {user_text[:60]}...")
    
    # إظهار مؤشر الكتابة
    await message.chat.send_action(action="typing")
    
    try:
        # أولاً: محاولة التعرف على الأمر باستخدام regex السريع
        parsed = await parse_natural_command(user_text, update, context)
        
        if parsed:
            command_type, target_id, reason = parsed
            result = await execute_admin_command(update, context, command_type, target_id, reason)
            await message.reply_text(result)
            return
        
        # ثانياً: استخدام DeepSeek-R1 للفهم الذكي
        user_id = user.id
        conv_manager.clear(user_id)
        conv_manager.add_message(user_id, "system", SYSTEM_PROMPT)
        
        context_info = f"""
المستخدم: {user.username or user.first_name}
المجموعة: {chat.title}
نوع الدردشة: {chat.type}
الرسالة: {user_text}
"""
        conv_manager.add_message(user_id, "user", context_info)
        
        messages = conv_manager.get_messages(user_id)
        prompt = build_deepseek_prompt(messages)
        
        output = llm(
            prompt,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            stop=["<<｜User｜>", "<｜end▁of▁sentence｜>"],
            echo=False
        )
        
        response = output["choices"][0]["text"].strip()
        thinking, answer = extract_think_and_answer(response)
        
        # التحقق من وجود أمر في الرد
        admin_keywords = ["حذف", "طرد", "حظر", "كتم", "تثبيت", "تحذير", "فك"]
        if any(kw in answer for kw in admin_keywords):
            parsed2 = await parse_natural_command(answer, update, context)
            if parsed2:
                command_type, target_id, reason = parsed2
                result = await execute_admin_command(update, context, command_type, target_id, reason)
                await message.reply_text(result)
                return
        
        if answer:
            await message.reply_text(answer, parse_mode="Markdown")
        else:
            await message.reply_text("🤔 لم أفهم الأمر. استخدم /help لعرض الأوامر المتاحة.")
            
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة رسالة المجموعة: {e}")
        await message.reply_text("❌ حدث خطأ أثناء تنفيذ الأمر.")

# ==================== معالج الأخطاء ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ خطأ: {context.error}")

# ==================== الدالة الرئيسية ====================
def main():
    logger.info("🚀 جاري تشغيل بوت إدارة المجموعات DeepSeek-R1...")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("image", image_command))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS | filters.ChatType.CHANNELS,
        handle_group_message
    ))
    
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))
    
    application.add_error_handler(error_handler)
    
    logger.info("✅ بوت الإدارة يعمل الآن! اضغط Ctrl+C للإيقاف.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
