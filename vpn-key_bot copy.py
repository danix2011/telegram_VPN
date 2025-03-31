import logging
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, Message
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import asyncio

# Конфигурация
TOKEN = "7749755571:AAE4qmU7G04BpVzddPMjkzN3dAO9tj7qqrU"
ADMIN_IDS = [2134434120, 6639580282]
VPN_DNS = "1.1.1.1, 8.8.8.8"
KEY_EXPIRATION_DAYS = 30
WG_SERVER_PUBLIC_KEY = "your_wg_pubkey"
SERVER_IP = "your.server.ip"
SUBSCRIPTION_PRICE = 20000

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация БД
def init_db():
    with sqlite3.connect('vpn_keys.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                key TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )
        ''')

init_db()

# Генерация ключа
def generate_key():
    return secrets.token_urlsafe(24)

# Клавиатуры
def user_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("/getkey", "/dns", "/buy")
    markup.row("/support", "/myid", "/ref")
    markup.row("/devices", "/servers")
    return markup

def admin_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("/stats", "/allkeys")
    markup.row("/broadcast")
    return markup

# ================= ОСНОВНЫЕ ОБРАБОТЧИКИ =================
@dp.message(Command("start"))
async def start(message: types.Message):
    text = (
        f"🔑 Добро пожаловать, {message.from_user.first_name}!\n"
        "Выберите действие:\n"
        "• /getkey - Получить VPN-ключ\n"
        "• /dns - Рекомендуемые DNS\n"
        "• /support - Техподдержка"
    )

    if message.from_user.id in ADMIN_IDS:
        await message.answer("👑 Режим администратора", reply_markup=admin_keyboard())
    
    await message.answer(text, reply_markup=user_keyboard())

@dp.message_handler(commands=['getkey'])
async def getkey(message: types.Message):
    user_id = message.from_user.id
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, expires_at FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()

            if result and result[1]:
                expires_at = datetime.fromisoformat(result[1])
                if datetime.now(timezone.utc) < expires_at:
                    await message.answer(
                        f"✅ Ваш ключ: {result[0]}\n"
                        f"⏳ Действует до: {expires_at.strftime('%d.%m.%Y %H:%M')}"
                    )
                    return

            new_key = generate_key()
            expires_at = datetime.now(timezone.utc) + timedelta(days=KEY_EXPIRATION_DAYS)
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, key, expires_at)
                VALUES (?, ?, ?)
            ''', (user_id, new_key, expires_at.isoformat()))
            conn.commit()

            keyboard = InlineKeyboardMarkup()
            keyboard.row(
                InlineKeyboardButton("WireGuard Config", callback_data="wg_config"),
                InlineKeyboardButton("OpenVPN Config", callback_data="ovpn_config")
            )

            await message.answer(
                f"🎉 Новый ключ: `{new_key}`\n"
                f"⏳ Срок действия: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                "📎 Выберите тип конфигурации:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error in getkey: {e}")
        await message.answer("🚫 Ошибка генерации ключа")

# ================= ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ =================
@dp.message_handler(commands=['dns'])
async def dns(message: types.Message):
    await message.answer(
        f"🔧 Рекомендуемые DNS-серверы:\n\n"
        f"• Cloudflare: `1.1.1.1`\n"
        f"• Google: `8.8.8.8`\n"
        f"• AdGuard: `94.140.14.14`",
        parse_mode='Markdown'
    )

@dp.message_handler(commands=['support'])
async def support(message: types.Message):
    await message.answer(
        "🛠 Техническая поддержка:\n\n"
        "• Email: support@example.com\n"
        "• Telegram: @tech_support"
    )

@dp.message_handler(commands=['myid'])
async def myid(message: types.Message):
    await message.answer(
        f"🆔 Ваш Telegram ID: `{message.from_user.id}`",
        parse_mode='Markdown'
    )

# ================= АДМИН-ФУНКЦИИ =================
@dp.message_handler(commands=['stats'])
async def stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    with sqlite3.connect('vpn_keys.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        total = cursor.fetchone()[0]
    
    await message.answer(
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total}\n"
        f"• Срок действия ключа: {KEY_EXPIRATION_DAYS} дней"
    )

@dp.message_handler(commands=['allkeys'])
async def allkeys(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    with sqlite3.connect('vpn_keys.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, key, expires_at FROM users')
        keys = cursor.fetchall()
    
    response = "🔑 Все активные ключи:\n\n"
    for user_id, key, expires_at in keys:
        response += f"👤 {user_id}: `{key}`\n⏳ {expires_at}\n\n"
    
    await message.answer(response[:4000], parse_mode='Markdown')

# ================= КОНФИГУРАЦИИ VPN =================
@dp.callback_query_handler(lambda c: c.data in ['wg_config', 'ovpn_config'])
async def button_handler(callback_query: types.CallbackQuery):
    vpn_type = "WireGuard" if callback_query.data == 'wg_config' else "OpenVPN"
    await generate_config(callback_query, vpn_type)
    await bot.answer_callback_query(callback_query.id)

async def generate_config(callback_query: types.CallbackQuery, vpn_type: str):
    user_id = callback_query.from_user.id
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                await bot.send_message(user_id, "❌ Сначала получите ключ через /getkey")
                return

            key = result[0]
            config = ""
            filename = ""
            
            if vpn_type == "WireGuard":
                config = f"""[Interface]
PrivateKey = {key}
Address = 10.0.0.{user_id % 254}/24
DNS = 1.1.1.1

[Peer]
PublicKey = {WG_SERVER_PUBLIC_KEY}
Endpoint = {SERVER_IP}:51820
AllowedIPs = 0.0.0.0/0"""
                filename = f"wg-{user_id}.conf"
                
            elif vpn_type == "OpenVPN":
                config = f"""client
dev tun
proto udp
remote {SERVER_IP} 1194
resolv-retry infinite
nobind
persist-key
persist-tun
<ca>
-----BEGIN CERTIFICATE-----
ВАШ_CA_СЕРТИФИКАТ
-----END CERTIFICATE-----
</ca>
<key>
{key}
</key>"""
                filename = f"ovpn-{user_id}.ovpn"

            bio = BytesIO(config.encode())
            bio.name = filename
            await bot.send_document(
                chat_id=user_id,
                document=bio,
                caption=f"⚙️ {vpn_type} конфигурация"
            )
    except Exception as e:
        logger.error(f"Config generation error: {e}")
        await bot.send_message(user_id, "⚠️ Ошибка генерации конфига")

# ================= ПЛАТЕЖНАЯ СИСТЕМА =================
@dp.message_handler(commands=['buy'])
async def buy(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("💳 Оплата картой", callback_data="pay_card"),
        InlineKeyboardButton("⭐️ Telegram Stars", callback_data="pay_stars")
    )
    await message.answer("🎁 Выберите способ оплаты:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('pay_'))
async def handle_payment_choice(callback_query: types.CallbackQuery):
    payment_type = callback_query.data.split('_')[1]
    
    if payment_type == "card":
        await send_card_invoice(callback_query)
    elif payment_type == "stars":
        await send_stars_invoice(callback_query)
    
    await bot.answer_callback_query(callback_query.id)

async def send_card_invoice(callback_query: types.CallbackQuery):
    await bot.send_invoice(
        callback_query.from_user.id,
        title="VPN Premium (Карта)",
        description="Доступ к VPN на 1 месяц",
        provider_token="YOUR_CARD_PROVIDER_TOKEN",
        currency="RUB",
        prices=[types.LabeledPrice("Месячная подписка", 49000)],
        payload="card_payment"
    )

async def send_stars_invoice(callback_query: types.CallbackQuery):
    await bot.send_invoice(
        callback_query.from_user.id,
        title="VPN Premium (Stars)",
        description="Доступ к VPN на 1 месяц",
        provider_token="YOUR_STARS_PROVIDER_TOKEN",
        currency="XTR",
        prices=[types.LabeledPrice("Месячная подписка", 50 * 100)],
        payload="stars_payment"
    )

@dp.pre_checkout_query_handler()
async def precheckout(query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: types.Message):
    user_id = message.from_user.id
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    
    with sqlite3.connect('vpn_keys.db') as conn:
        conn.execute('''
            UPDATE users 
            SET expires_at = ? 
            WHERE user_id = ?
        ''', (expires_at.isoformat(), user_id))
        conn.commit()
    
    await message.answer("✅ Подписка успешно активирована!")

# ================= ПЛАНИРОВЩИК ЗАДАЧ =================
async def check_subscriptions():
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE expires_at < ?", 
                         (datetime.now(timezone.utc).isoformat(),))
            
            for user_id, in cursor.fetchall():
                await bot.send_message(
                    user_id,
                    "⚠️ Ваша подписка истекает через 3 дня! Продлите её командой /buy"
                )
    except Exception as e:
        logger.error(f"Subscription check error: {e}")

async def on_startup(dp):
    scheduler.add_job(check_subscriptions, 'interval', days=1)
    scheduler.start()

async def main():
    # Планировщик задач
    scheduler.add_job(
        check_subscriptions,
        IntervalTrigger(days=1),
        args=[dp]  # Передаем dp вместо application
    )
    scheduler.start()

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())