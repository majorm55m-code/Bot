from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus

async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        return True  # يمكن تغييرها حسب الحاجة
    try:
        member = await chat.get_member(user.id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False
