import asyncio
import argparse
import logging
import sys
import os
from html import escape
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
# from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from config import TOKEN, ADMIN_ID, GUI, WEB_HOST, WEB_PORT
from keyboard import *
from utils import now, backup_json
from storage import load_users, save_users, add_user
from web_admin import start_web_admin

bot = Bot(token=TOKEN)
dp = Dispatcher()

broadcast_mode = {}
pending_sub_text = {}
custom_date_state = {}
last_bot_messages = {}
active_bot_messages = {}


async def safe_delete_message(chat_id, message_id):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def delete_active_message(chat_id, except_message_id=None):
    message_id = active_bot_messages.get(chat_id)
    if message_id and message_id != except_message_id:
        await safe_delete_message(chat_id, message_id)
    active_bot_messages.pop(chat_id, None)


async def answer_clean(message: Message, text, **kwargs):
    await delete_active_message(message.chat.id)
    sent = await message.answer(text, **kwargs)
    active_bot_messages[message.chat.id] = sent.message_id
    return sent


async def edit_or_answer_clean(call: CallbackQuery, text, **kwargs):
    await call.answer()
    chat_id = call.message.chat.id
    active_bot_messages[chat_id] = call.message.message_id
    try:
        await call.message.edit_text(text, **kwargs)
        return call.message
    except Exception:
        await safe_delete_message(chat_id, call.message.message_id)
        sent = await call.message.answer(text, **kwargs)
        active_bot_messages[chat_id] = sent.message_id
        return sent


async def show_temp_message(message: Message, text, seconds=4, **kwargs):
    sent = await answer_clean(message, text, **kwargs)
    await asyncio.sleep(seconds)
    await safe_delete_message(sent.chat.id, sent.message_id)
    active_bot_messages.pop(sent.chat.id, None)
    return sent


def format_broadcast_message(text):
    return f"📣 <b>Уведомление</b>\n\n{escape(text)}"

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
                f"🆕 В боте новый пользователь\n\n"
                f"ID: {message.from_user.id}\n"
                f"Имя: {message.from_user.first_name}\n"
                f"@{message.from_user.username}"
            )
        except:
            pass

    kb = admin_kb() if message.from_user.id == ADMIN_ID else base_kb()

    try:
        await message.delete()
    except Exception:
        pass
    await answer_clean(message, "👋 Привет! Я на месте. Выберите нужное действие ниже.", reply_markup=kb)


# ---------------- MY SUB ----------------

@dp.callback_query(F.data == "my_sub")
async def my_sub(call: CallbackQuery):
    users = load_users()
    uid = str(call.from_user.id)

    u = users.get(uid)

    if not u or not u.get("subscription_text"):
        await call.answer("❌Пока активной подписки нет. Напишите администратору, чтобы получить доступ.", show_alert=True)
        return

    if not u.get("subscription_end"):
        await call.answer("❌Доступ найден, но дата окончания еще не указана. Администратор скоро поправит.", show_alert=True)
        return
    
    end = datetime.fromisoformat(u["subscription_end"])
    days_left = (end.date() - now().date()).days

    if days_left <= 0:
        await call.answer("❌Подписка уже закончилась. Обновите доступ у администратора.", show_alert=True)
        return

    await edit_or_answer_clean(
        call,
        f"📅 Ваша подписка активна\n\n"
        f"⏳ Работает до: {end.strftime('%Y-%m-%d %H:%M')}\n"
        f"📊 Осталось дней: {days_left}\n\n"
        f"‼️ Не передавайте VPN другим пользователям: из-за этого подключение могут заблокировать.\n\n"
        f"📱 Откройте приложение AmneziaVPN и вставьте данные доступа:\n"
        f"https://github.com/amnezia-vpn/amnezia-client/releases\n"
        f"\n👇Нажмите на блок ниже, чтобы скопировать:\n"
        f"`{u['subscription_text']}`",
        parse_mode="Markdown",
        reply_markup=back_kb()
    )


# ---------------- USERS ----------------

@dp.callback_query(F.data == "users")
async def users(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    await edit_or_answer_clean(call, "👥 Пользователи\n\nСейчас: " + now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n‼️ - доступ без текста\n⌛️ - срок закончился или не задан\n❌ - доступа нет\n\nВыберите пользователя из списка:", reply_markup=users_kb(load_users()))


@dp.callback_query(F.data.startswith("user_"))
async def user_open(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]
    u = load_users().get(uid)

    if not u:
        return

    await edit_or_answer_clean(
        call,
        f"👤 Карточка пользователя\n\n"
        f"Имя: {u['first_name']}\n"
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
        await bot.send_message(uid, f"✅ Подписка продлена на {days} дн. Можно продолжать пользоваться доступом.")
    except:
        pass

    await edit_or_answer_clean(
        call,
        f"👤 Карточка пользователя обновлена\n\n"
        f"Имя: {u['first_name']}\n"
        f"ID: {uid}\n"
        f"Username: @{u.get('username')}\n"
        f"Доступ: {u.get('subscription_text')}\n"
        f"До: {u.get('subscription_end')}",
        reply_markup=user_manage_kb(uid)
    )


# ---------------- CUSTOM DATE ----------------

@dp.callback_query(F.data.startswith("custom_"))
async def custom(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]
    custom_date_state[call.from_user.id] = uid

    new_message = await edit_or_answer_clean(call, "📅 Укажите новую дату окончания доступа\n\nФормат: YYYY-MM-DD HH:MM", reply_markup=cancel_kb())

    last_bot_messages[call.from_user.id] = new_message.message_id


# ---------------- SET SUB TEXT ----------------

@dp.callback_query(F.data.startswith("setsub_"))
async def setsub(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]
    pending_sub_text[call.from_user.id] = uid

    new_message = await edit_or_answer_clean(call, "✍️ Отправьте новый текст доступа для пользователя.", reply_markup=cancel_kb())

    last_bot_messages[call.from_user.id] = new_message.message_id


# ---------------- DELETE ----------------

@dp.callback_query(F.data.startswith("del_"))
async def delete(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    uid = call.data.split("_")[1]

    # users = load_users()

    u = load_users().get(uid)

    first_name = u.get("first_name") or "Без имени"
    username = u.get("username") or "без_username"

    await edit_or_answer_clean(call, "🗑 Удалить пользователя " + first_name + " @" + username + " (" + uid + ") из базы?", reply_markup=confirm_delete_kb(uid))

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

    await edit_or_answer_clean(call, "🗑 Пользователь удален: " + first_name + " @" + username + " (" + uid + ")")


# ---------------- NOT CONFIRM DELETE ----------------

# @dp.callback_query(F.data.startswith("not_confirm_del_"))
# async def not_confirm_del(call: CallbackQuery):
#     if call.from_user.id != ADMIN_ID:
#         return

#     await call.message.delete()


# ---------------- MAIN ----------------

@dp.callback_query(F.data.startswith("main"))
async def back(call: CallbackQuery):
    kb = admin_kb() if call.from_user.id == ADMIN_ID else base_kb()
    await edit_or_answer_clean(call, "👋 Главное меню. Что делаем дальше?", reply_markup=kb)


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
            await bot.send_message(uid, "🔒 Доступ закрыт. Если это ошибка, напишите администратору.")
        except:
            pass

    u = load_users().get(uid)

    first_name = u.get("first_name") or "Без имени"
    username = u.get("username") or "без_username"

    await edit_or_answer_clean(call, "🔒 Доступ закрыт для " + first_name + " @" + username + " (" + uid + ")")


# ---------------- BROADCAST ----------------

@dp.callback_query(F.data == "broadcast")
async def broadcast(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    
    broadcast_mode[call.from_user.id] = True
    new_message = await edit_or_answer_clean(call, "📣 Отправьте текст рассылки. Я разошлю его всем пользователям из базы.", reply_markup=cancel_kb())

    last_bot_messages[call.from_user.id] = new_message.message_id


@dp.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    # broadcast_mode[call.from_user.id] = False
    custom_date_state.pop(call.from_user.id, None)
    pending_sub_text.pop(call.from_user.id, None)
    broadcast_mode.pop(call.from_user.id, None)
    await edit_or_answer_clean(call, "Готово, действие отменено.")
    # kb = admin_kb() if call.from_user.id == ADMIN_ID else base_kb()
    # await call.message.answer("👋 Добро пожаловать!", reply_markup=kb)
    await asyncio.sleep(5)
    await safe_delete_message(call.message.chat.id, call.message.message_id)
    active_bot_messages.pop(call.message.chat.id, None)


# ---------------- BACK ----------------

@dp.callback_query(F.data.startswith("backup"))
async def back(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return

    backup_patch = backup_json("users.json")

    file = FSInputFile(backup_patch)
    await call.answer()
    await safe_delete_message(call.message.chat.id, call.message.message_id)
    active_bot_messages.pop(call.message.chat.id, None)
    await call.message.answer_document(file, caption="📂 Свежий бэкап пользователей готов.")
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

        await safe_delete_message(message.chat.id, last_bot_messages.get(message.from_user.id))
        await message.delete()
        await show_temp_message(message, "✅ Доступ сохранен и отправлен пользователю.")

        try:
            await bot.send_message(uid, "🎁 Вам выдали доступ. Откройте раздел «Моя подписка», чтобы посмотреть данные подключения.")
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

            await safe_delete_message(message.chat.id, last_bot_messages.get(message.from_user.id))
            await message.delete()
            await show_temp_message(message, "✅ Дата окончания обновлена.")

            try:
                await bot.send_message(uid, f"📅 Дата окончания подписки обновлена: {dt}")
            except:
                pass

        except:
            await safe_delete_message(message.chat.id, last_bot_messages.get(message.from_user.id))
            await message.delete()
            await show_temp_message(message, "❌Не получилось распознать дату. Нужен формат: YYYY-MM-DD HH:MM")

        custom_date_state.pop(admin_id)
        return

    # BROADCAST
    if broadcast_mode.get(admin_id) and message.text:
        users = load_users()

        for uid in users:
            try:
                await bot.send_message(uid, format_broadcast_message(message.text), parse_mode="HTML")
            except:
                pass

        broadcast_mode[admin_id] = False
        await safe_delete_message(message.chat.id, last_bot_messages.get(message.from_user.id))
        await message.delete()
        await show_temp_message(message, "✅ Рассылка отправлена пользователям.")


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
                await bot.send_message(uid, "⏳ Подписка заканчивается завтра. Чтобы не потерять доступ, продлите ее у администратора.")
                first_name = u.get("first_name") or "Без имени"
                username = u.get("username") or "без_username"
                await bot.send_message(ADMIN_ID, f"⏳ У {first_name} (@{username}) подписка заканчивается завтра.")
            except:
                pass

            u["notified_1day"] = True
        elif (end.date() - n.date()).days == 0 and not u.get("notified_0day"):
            try:
                await bot.send_message(uid, "🔒 Подписка закончилась. Для продления напишите администратору.")
                first_name = u.get("first_name") or "Без имени"
                username = u.get("username") or "без_username"
                await bot.send_message(ADMIN_ID, f"🔒 У {first_name} (@{username}) подписка закончилась.")
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
        await bot.send_document(chat_id=ADMIN_ID, document=file, caption="📂 Ежедневный бэкап пользователей готов.")
        if os.path.exists(backup_patch):
            os.remove(backup_patch)
            print(f"✅ Файл {backup_patch} удален")
        else:
            print(f"❌ Файл {backup_patch} не найден")

# ---------------- MAIN ----------------

# def parse_args():
#     parser = argparse.ArgumentParser(description="Telegram bot with optional web admin panel")
#     parser.add_argument("-nogui", action="store_true", help="start bot without web admin interface")
#     return parser.parse_args()


async def main():
    asyncio.create_task(scheduler())
    asyncio.create_task(auto_backup())
    gui = GUI
    if gui:
        await start_web_admin(bot, WEB_HOST, WEB_PORT)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    # args = parse_args()
    asyncio.run(main())
