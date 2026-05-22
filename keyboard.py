from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from utils import now

# ---------------- KEYBOARDS ----------------

def base_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Моя подписка", callback_data="my_sub")]
    ])


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Моя подписка", callback_data="my_sub")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="📂 Бэкап", callback_data="backup")]
    ])

def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить действие", callback_data="cancel")]
    ])

def confirm_delete_kb(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_del_{uid}")],
        [InlineKeyboardButton(text="❌ Нет", callback_data=f"main")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])

# def copy_kb(text: str):
#     return InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="📋 Скопировать", copy_text={"text": text})]
#     ])


def user_manage_kb(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕1", callback_data=f"add_{uid}_1"),
            InlineKeyboardButton(text="➕7", callback_data=f"add_{uid}_7"),
            InlineKeyboardButton(text="➕30", callback_data=f"add_{uid}_30"),
        ],
        [
            InlineKeyboardButton(text="📅 Кастом дата", callback_data=f"custom_{uid}"),
            InlineKeyboardButton(text="📝 Установить доступ", callback_data=f"setsub_{uid}")
        ],
        [InlineKeyboardButton(text=" 🗑️ Очистить", callback_data=f"clear_{uid}")],
        [InlineKeyboardButton(text="❌ Удалить", callback_data=f"del_{uid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])


def users_kb(users):
    kb = []
    for uid, u in users.items():
        if u.get("subscription_end") == None and u.get("subscription_text") == None:
            kb.append([
                InlineKeyboardButton(
                    text=f"‼️ | {u.get('first_name')} (@{u.get('username')})",
                    callback_data=f"user_{uid}"
                )
            ])
        elif u.get("subscription_end") == None or (u.get("subscription_end") and datetime.fromisoformat(u["subscription_end"]) < now()):
            kb.append([
                InlineKeyboardButton(
                    text=f"⌛️ | {u.get('first_name')} (@{u.get('username')})",
                    callback_data=f"user_{uid}"
                )
            ])
        elif u.get("subscription_text") == None:
            kb.append([
                InlineKeyboardButton(
                    text=f"❌ | {u.get('first_name')} (@{u.get('username')})",
                    callback_data=f"user_{uid}"
                )
            ])
        else:
            kb.append([
                InlineKeyboardButton(
                    text=f"{u.get('first_name')} (@{u.get('username')})",
                    callback_data=f"user_{uid}"
                )
            ])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)