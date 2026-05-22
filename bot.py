import json
import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
# from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from config import TOKEN, ADMIN_ID
from keyboard import *
from utils import now, backup_json

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB_FILE = "users.json"

broadcast_mode = {}
pending_sub_text = {}
custom_date_state = {}
last_bot_messages = {}

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
        delet_messages = await call.message.answer("❌ Подписка не активна")
        await asyncio.sleep(5)
        try:
            await delet_messages.delete()
        except:
            pass
        return
    
    end = datetime.fromisoformat(u["subscription_end"])
    days_left = (end.date() - now().date()).days

    if days_left <= 0:
        delet_messages = await call.message.answer("❌ Ваша подписка истекла")
        await asyncio.sleep(5)
        try:
            await delet_messages.delete()
        except:
            pass
        return

    await call.message.answer(
        f"📅 Подписка:\n"
        f"⏳ До: {end.strftime('%Y-%m-%d %H:%M')}\n"
        f"📊 Осталось дней: {days_left}\n"
        f"‼️Не делитесь впн с другими пользователями, в избежание блокировки данного впн или вашего подключения‼️\n"
        f"📱 Вставьте в приложение AmneziaVpn\n"
        f"https://github.com/amnezia-vpn/amnezia-client/releases\n"
        f"👇 Нажмите что бы скопировать\n"
        f"`{u['subscription_text']}`",
        parse_mode="Markdown",
        reply_markup=back_kb()
    )


# ---------------- USERS ----------------

@dp.callback_query(F.data == "users")
async def users(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await call.message.answer("Дата и время сейчас: " + now().strftime("%Y-%m-%d %H:%M:%S") + "\n‼️ - Пустой\n⌛️ - Закончилась подписка\n❌ - Подски нет\n👥 Пользователи:", reply_markup=users_kb(load_users()))


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
        f"Username: @{u.get('username')}\n"
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

    delet_messages = await call.message.answer("✅ Обновлено")
    await asyncio.sleep(5)
    try:
        await delet_messages.delete()
    except:
        pass


# ---------------- CUSTOM DATE ----------------

@dp.callback_query(F.data.startswith("custom_"))
async def custom(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await call.message.delete()

    uid = call.data.split("_")[1]
    custom_date_state[call.from_user.id] = uid

    new_message = await call.message.answer("📅 Введите дату: YYYY-MM-DD HH:MM", reply_markup=cancel_kb())

    last_bot_messages[call.from_user.id] = new_message.message_id


# ---------------- SET SUB TEXT ----------------

@dp.callback_query(F.data.startswith("setsub_"))
async def setsub(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await call.message.delete()

    uid = call.data.split("_")[1]
    pending_sub_text[call.from_user.id] = uid

    new_message = await call.message.answer("✍️ Введите текст доступа:", reply_markup=cancel_kb())

    last_bot_messages[call.from_user.id] = new_message.message_id


# ---------------- DELETE ----------------

@dp.callback_query(F.data.startswith("del_"))
async def delete(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await call.message.delete()

    uid = call.data.split("_")[1]

    # users = load_users()

    u = load_users().get(uid)

    first_name = u.get("first_name") or "Без имени"
    username = u.get("username") or "без_username"

    await call.message.answer("🗑 Удалить " + first_name + " @" + username + " (" + uid + ")?", reply_markup=confirm_delete_kb(uid))

    # if uid in users:
    #     del users[uid]
    #     save_users(users)

    # await call.message.answer("🗑 Удален")


# ---------------- CONFIRM DELETE ----------------

@dp.callback_query(F.data.startswith("confirm_del_"))
async def confirm_del(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[2]

    users = load_users()

    u = load_users().get(uid)

    if uid in users:
        del users[uid]
        save_users(users)

    first_name = u.get("first_name") or "Без имени"
    username = u.get("username") or "без_username"

    await call.message.delete()

    await call.message.answer("🗑 Удален " + first_name + " @" + username + " (" + uid + ")")


# ---------------- NOT CONFIRM DELETE ----------------

# @dp.callback_query(F.data.startswith("not_confirm_del_"))
# async def not_confirm_del(call: CallbackQuery):
#     if call.from_user.id != ADMIN_ID:
#         return

#     await call.message.delete()


# ---------------- MAIN ----------------

@dp.callback_query(F.data.startswith("main"))
async def back(call: CallbackQuery):
    # if call.from_user.id != ADMIN_ID:
    #     return

    await call.message.delete()


# ---------------- CLEAR ----------------

@dp.callback_query(F.data.startswith("clear_"))
async def clear(call: CallbackQuery):
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
            await bot.send_message(uid, "❌ Доступ закрыт")
        except:
            pass

    u = load_users().get(uid)

    first_name = u.get("first_name") or "Без имени"
    username = u.get("username") or "без_username"

    await call.message.answer("🗑 Доступ закрыт для " + first_name + " @" + username + " (" + uid + ")")


# ---------------- BROADCAST ----------------

@dp.callback_query(F.data == "broadcast")
async def broadcast(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    
    # await call.message.delete()

    broadcast_mode[call.from_user.id] = True
    new_message = await call.message.answer("📢 Введите сообщение для рассылки", reply_markup=cancel_kb())

    last_bot_messages[call.from_user.id] = new_message.message_id


@dp.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await call.message.delete()

    # broadcast_mode[call.from_user.id] = False
    custom_date_state.pop(call.from_user.id, None)
    pending_sub_text.pop(call.from_user.id, None)
    broadcast_mode.pop(call.from_user.id, None)
    delet_messages = await call.message.answer("❌ Действие отменено")
    # kb = admin_kb() if call.from_user.id == ADMIN_ID else base_kb()
    # await call.message.answer("👋 Добро пожаловать!", reply_markup=kb)
    await asyncio.sleep(5)
    try:
        await delet_messages.delete()
    except:
        pass


# ---------------- BACK ----------------

@dp.callback_query(F.data.startswith("backup"))
async def back(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    backup_patch = backup_json("users.json")

    file = FSInputFile(backup_patch)
    await call.message.answer_document(file, caption="📂 Бэкап пользователей")
    if os.path.exists(backup_patch):
        os.remove(backup_patch)
        print(f"✅ Файл {backup_patch} удален")
        return True
    else:
        print(f"❌ Файл {backup_patch} не найден")
        return False


# ---------------- ROUTER ----------------

@dp.message()
async def router(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.delete()
        return

    admin_id = message.from_user.id

    # SUB TEXT
    if admin_id in pending_sub_text:
        uid = pending_sub_text[admin_id]

        users = load_users()
        users[uid]["subscription_text"] = message.text
        save_users(users)

        await bot.delete_message(message.chat.id, message_id=last_bot_messages[message.from_user.id])
        await message.delete()
        delet_messages = await message.answer("✅ Доступ установлен")
        await asyncio.sleep(5)
        try:
            await delet_messages.delete()
        except:
            pass

        try:
            await bot.send_message(uid, f"📦 Выдана подписка")
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

            await bot.delete_message(message.chat.id, message_id=last_bot_messages[message.from_user.id])
            await message.delete()
            delet_messages = await message.answer("✅ Установлено")
            await asyncio.sleep(5)
            try:
                await delet_messages.delete()
            except:
                pass

            try:
                await bot.send_message(uid, f"📅 До: {dt}")
            except:
                pass

        except:
            await bot.delete_message(message.chat.id, message_id=last_bot_messages[message.from_user.id])
            await message.delete()
            delet_messages = await message.answer("❌ Формат: YYYY-MM-DD HH:MM")
            await asyncio.sleep(5)
            try:
                await delet_messages.delete()
            except:
                pass

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
        await bot.delete_message(message.chat.id, message_id=last_bot_messages[message.from_user.id])
        await message.delete()
        delet_messages = await message.answer("✅ Рассылка отправлена")
        await asyncio.sleep(5)
        try:
            await delet_messages.delete()
        except:
            pass


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
                first_name = u.get("first_name") or "Без имени"
                username = u.get("username") or "без_username"
                await bot.send_message(ADMIN_ID, f"⚠️ {first_name} (@{username}) заканчивается завтра")
            except:
                pass

            u["notified_1day"] = True
        elif (end.date() - n.date()).days == 0 and not u.get("notified_0day"):
            try:
                await bot.send_message(uid, "⚠️ Подписка закончилась!")
                first_name = u.get("first_name") or "Без имени"
                username = u.get("username") or "без_username"
                await bot.send_message(ADMIN_ID, f"⚠️  {first_name} (@{username}) закончилась")
            except:
                pass

            u["notified_0day"] = True

    save_users(users)


async def scheduler():
    while True:
        await check()
        await asyncio.sleep(3600)


# ---------------- AUTO BACKUP ----------------

async def auto_backup():
    while True:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        target_time = now.replace(hour=3, minute=0, second=0, microsecond=0)

        if now > target_time:
            target_time = target_time.replace(day=now.day + 1)
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        backup_patch = backup_json("users.json")

        file = FSInputFile(backup_patch)
        await bot.send_document(chat_id=ADMIN_ID, document=file, caption="📂 Ежедневный бэкап")
        if os.path.exists(backup_patch):
            os.remove(backup_patch)
            print(f"✅ Файл {backup_patch} удален")
        else:
            print(f"❌ Файл {backup_patch} не найден")

# ---------------- MAIN ----------------

async def main():
    asyncio.create_task(scheduler())
    asyncio.create_task(auto_backup())
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())