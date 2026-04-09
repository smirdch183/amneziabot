import json
import asyncio
import logging
import sys
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from config import TOKEN, ADMIN_ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB_FILE = "users.json"

broadcast_mode = {}
pending_sub_text = {}
custom_date_state = {}


# ---------------- TIME ----------------

def now():
    return datetime.now().replace(microsecond=0)


# ---------------- JSON ----------------

def load_users():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def add_user(user_id, username, first_name):
    users = load_users()
    uid = str(user_id)

    if uid not in users:
        users[uid] = {
            "first_name": first_name,
            "username": username,
            "subscription_text": None,
            "subscription_end": None,
            "notified_1day": False,
            "notified_0day": False
        }
        save_users(users)
        return True

    return False


# ---------------- KEYBOARDS ----------------

def base_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Моя подписка", callback_data="my_sub")]
    ])


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Моя подписка", callback_data="my_sub")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")]
    ])

def cancel_broadcast_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить рассылку", callback_data="cancel_broadcast")]
    ])

def copy_kb(text: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать", copy_text={"text": text})]
    ])


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
        [InlineKeyboardButton(text="❌ Удалить", callback_data=f"del_{uid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="users")]
    ])


def users_kb(users):
    kb = []
    for uid, u in users.items():
        kb.append([
            InlineKeyboardButton(
                text=f"{u.get('first_name')} ({uid})",
                callback_data=f"user_{uid}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ---------------- START ----------------

@dp.message(Command("start"))
async def start(message: Message):
    added = add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )

    if added:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🆕 Новый пользователь:\n"
                f"ID: {message.from_user.id}\n"
                f"Имя: {message.from_user.first_name}\n"
                f"@{message.from_user.username}"
            )
        except:
            pass

    kb = admin_kb() if message.from_user.id == ADMIN_ID else base_kb()

    await message.answer("👋 Добро пожаловать!", reply_markup=kb)


# ---------------- MY SUB ----------------

@dp.callback_query(F.data == "my_sub")
async def my_sub(call: CallbackQuery):
    users = load_users()
    uid = str(call.from_user.id)

    u = users.get(uid)

    if not u or not u.get("subscription_text"):
        await call.message.answer("❌ Подписка не активна")
        return
    
    end = datetime.fromisoformat(u["subscription_end"])
    days_left = (end.date() - now().date()).days

    if days_left <= 0:
        await call.message.answer("❌ Ваша подписка истекла")
        return

    await call.message.answer(
        f"📅 Подписка:\n"
        # f"{u['subscription_text']}\n\n"
        f"⏳ До: {end.strftime('%Y-%m-%d %H:%M')}\n"
        f"📊 Осталось дней: {days_left}\n"
        f"‼️Не делитесь впн с другими пользователями, в избежание блокировки данного впн или вашего подключения‼️\n"
        f"📱 Вставьте в приложение AmneziaVpn\n"
        f"https://github.com/amnezia-vpn/amnezia-client/releases",
        reply_markup=copy_kb(u["subscription_text"])
    )


# ---------------- USERS ----------------

@dp.callback_query(F.data == "users")
async def users(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await call.message.answer("👥 Пользователи:", reply_markup=users_kb(load_users()))


@dp.callback_query(F.data.startswith("user_"))
async def user_open(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]
    u = load_users().get(uid)

    if not u:
        return

    await call.message.answer(
        f"👤 {u['first_name']}\n"
        f"ID: {uid}\n"
        f"Доступ: {u.get('subscription_text')}\n"
        f"До: {u.get('subscription_end')}",
        reply_markup=user_manage_kb(uid)
    )


# ---------------- ADD DAYS ----------------

@dp.callback_query(F.data.startswith("add_"))
async def add_days(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    _, uid, days = call.data.split("_")

    users = load_users()
    u = users.get(uid)

    base = now()

    if u.get("subscription_end"):
        current = datetime.fromisoformat(u["subscription_end"])
        if current > base:
            base = current

    new_end = (base + timedelta(days=int(days))).replace(microsecond=0)

    u["subscription_end"] = new_end.isoformat()
    u["notified_1day"] = False
    u["notified_0day"] = False

    save_users(users)

    try:
        await bot.send_message(uid, f"✅ +{days} дней добавлено")
    except:
        pass

    await call.message.answer("✅ Обновлено")


# ---------------- CUSTOM DATE ----------------

@dp.callback_query(F.data.startswith("custom_"))
async def custom(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]
    custom_date_state[call.from_user.id] = uid

    await call.message.answer("📅 Введите дату: YYYY-MM-DD HH:MM")


# ---------------- SET SUB TEXT ----------------

@dp.callback_query(F.data.startswith("setsub_"))
async def setsub(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]
    pending_sub_text[call.from_user.id] = uid

    await call.message.answer("✍️ Введите текст доступа:")


# ---------------- DELETE ----------------

@dp.callback_query(F.data.startswith("del_"))
async def delete(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]

    users = load_users()

    if uid in users:
        users[uid]["subscription_text"] = None
        users[uid]["subscription_end"] = None
        users[uid]["notified_1day"] = False
        users[uid]["notified_0day"] = False
        save_users(users)

        try:
            await bot.send_message(uid, "❌ Подписка удалена")
        except:
            pass

    await call.message.answer("🗑 Удалено")


# ---------------- BROADCAST ----------------

@dp.callback_query(F.data == "broadcast")
async def broadcast(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    
    broadcast_mode[call.from_user.id] = True
    await call.message.answer("📢 Введите сообщение для рассылки", reply_markup=cancel_broadcast_kb())


@dp.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    broadcast_mode[call.from_user.id] = False
    await call.message.answer("❌ Рассылка отменена")


# ---------------- ROUTER ----------------

@dp.message()
async def router(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    admin_id = message.from_user.id

    # SUB TEXT
    if admin_id in pending_sub_text:
        uid = pending_sub_text[admin_id]

        users = load_users()
        users[uid]["subscription_text"] = message.text
        save_users(users)

        await message.answer("✅ Доступ установлен")

        try:
            await bot.send_message(uid, f"📦 Доступ:\n{message.text}")
        except:
            pass

        pending_sub_text.pop(admin_id)
        return

    # CUSTOM DATE
    if admin_id in custom_date_state:
        uid = custom_date_state[admin_id]

        try:
            dt = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
            dt = dt.replace(microsecond=0)

            users = load_users()
            users[uid]["subscription_end"] = dt.isoformat()
            users[uid]["notified_1day"] = False
            users[uid]["notified_0day"] = False
            save_users(users)

            await message.answer("✅ Установлено")

            try:
                await bot.send_message(uid, f"📅 До: {dt}")
            except:
                pass

        except:
            await message.answer("❌ Формат: YYYY-MM-DD HH:MM")

        custom_date_state.pop(admin_id)
        return

    # BROADCAST
    if broadcast_mode.get(admin_id) and message.text:
        users = load_users()

        for uid in users:
            try:
                await bot.send_message(uid, f"📢 {message.text}")
            except:
                pass

        broadcast_mode[admin_id] = False
        await message.answer("✅ Рассылка отправлена")


# ---------------- CHECK SUBS ----------------

async def check():
    users = load_users()
    n = now()

    for uid, u in users.items():
        if not u.get("subscription_end"):
            continue

        end = datetime.fromisoformat(u["subscription_end"])

        if (end.date() - n.date()).days == 1 and not u.get("notified_1day"):
            try:
                await bot.send_message(uid, "⚠️ Подписка заканчивается завтра!")
                await bot.send_message(ADMIN_ID, f"⚠️ {u['first_name']} ({uid}) заканчивается завтра")
            except:
                pass

            u["notified_1day"] = True
        elif (end.date() - n.date()).days == 0 and not u.get("notified_0day"):
            try:
                await bot.send_message(uid, "⚠️ Подписка закончилась!")
                await bot.send_message(ADMIN_ID, f"⚠️  {u['first_name']} ({uid}) закончилась")
            except:
                pass

            u["notified_0day"] = True

    save_users(users)


async def scheduler():
    while True:
        await check()
        await asyncio.sleep(3600)


# ---------------- MAIN ----------------

async def main():
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())