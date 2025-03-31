import logging
import sqlite3
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    _updater,
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    filters
)

# Конфигурация
TOKEN = "7749755571:AAE4qmU7G04BpVzddPMjkzN3dAO9tj7qqrU"
ADMIN_IDS = [2134434120, 6639580282]
VPN_DNS = "1.1.1.1, 8.8.8.8"
KEY_EXPIRATION_DAYS = 30
WG_SERVER_PUBLIC_KEY = "your_wg_pubkey"
SERVER_IP = "your.server.ip"
SUBSCRIPTION_PRICE = 20000
STARS_PER_SUBSCRIPTION = 50
REFERRAL_BONUS_DAYS = 7
MAX_DEVICES = 3

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
user_keyboard = ReplyKeyboardMarkup([
    ["/getkey", "/dns", "/buy"],
    ["/support", "/myid", "/ref"],
    ["/devices", "/servers"]
], resize_keyboard=True)

admin_keyboard = ReplyKeyboardMarkup(
    [["/stats", "/allkeys"], ["/broadcast"]],
    resize_keyboard=True
)

# ================= ОСНОВНЫЕ ОБРАБОТЧИКИ =================

async def getkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, expires_at FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()

            if result and result[1]:
                expires_at = datetime.fromisoformat(result[1])
                if datetime.now(timezone.utc) < expires_at:
                    await update.message.reply_text(
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

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("WireGuard Config", callback_data="wg_config")],
                [InlineKeyboardButton("OpenVPN Config", callback_data="ovpn_config")]
            ])

            await update.message.reply_text(
                f"🎉 Новый ключ: `{new_key}`\n"
                f"⏳ Срок действия: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                "📎 Выберите тип конфигурации:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error in getkey: {e}")
        await update.message.reply_text("🚫 Ошибка генерации ключа")

# ================= ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ =================

async def dns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🔧 Рекомендуемые DNS-серверы:\n\n"
        f"• Cloudflare: `1.1.1.1`\n"
        f"• Google: `8.8.8.8`\n"
        f"• AdGuard: `94.140.14.14`",
        parse_mode='Markdown'
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 Техническая поддержка:\n\n"
        "• Email: support@example.com\n"
        "• Telegram: @tech_support"
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 Ваш Telegram ID: `{user.id}`",
        parse_mode='Markdown'
    )

# ================= АДМИН-ФУНКЦИИ =================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    conn = sqlite3.connect('vpn_keys.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total = cursor.fetchone()[0]
    conn.close()
    
    await update.message.reply_text(
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total}\n"
        f"• Срок действия ключа: {KEY_EXPIRATION_DAYS} дней"
    )

async def allkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    conn = sqlite3.connect('vpn_keys.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, key, expires_at FROM users')
    keys = cursor.fetchall()
    conn.close()
    
    response = "🔑 Все активные ключи:\n\n"
    for user_id, key, expires_at in keys:
        response += f"👤 {user_id}: `{key}`\n⏳ {expires_at}\n\n"
    
    await update.message.reply_text(response[:4000], parse_mode='Markdown')

# ================= КОНФИГУРАЦИИ VPN =================

async def generate_config(update: Update, context: ContextTypes.DEFAULT_TYPE, vpn_type: str):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                await query.message.reply_text("❌ Сначала получите ключ через /getkey")
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
            await context.bot.send_document(
                chat_id=user_id,
                document=bio,
                caption=f"⚙️ {vpn_type} конфигурация"
            )
    except Exception as e:
        logger.error(f"Config generation error: {e}")
        await query.message.reply_text("⚠️ Ошибка генерации конфига")

async def check_subscriptions(app: Application):
    """Ежедневная проверка подписок"""
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE expires_at < ?", 
                         (datetime.now(timezone.utc).isoformat(),))
            
            for user_id, in cursor.fetchall():
                await app.bot.send_message(
                    user_id,
                    "⚠️ Ваша подписка истекает через 3 дня! Продлите её командой /buy"
                )
    except Exception as e:
        logger.error(f"Subscription check error: {e}")

# ================= НОВЫЕ ФУНКЦИИ ================= #

async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата подписки через ЮKassa"""
    chat_id = update.message.chat_id
    title = "VPN Premium подписка"
    description = "Доступ к VPN на 1 месяц"
    payload = "subscription"
    currency = "RUB"
    prices = [LabeledPrice("Месячная подписка", SUBSCRIPTION_PRICE)]

    await context.bot.send_invoice(
        chat_id,
        title,
        description,
        payload,
        "YOUR_PAYMENT_TOKEN",
        currency,
        prices
    )

async def referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реферальная система"""
    user_id = update.effective_user.id
    ref_link = f"https://t.me/{context.bot.username}?start=ref{user_id}"
    
    await update.message.reply_text(
        f"🎁 Пригласите друзей и получайте +{REFERRAL_BONUS_DAYS} дней за каждого!\n\n"
        f"Ваша ссылка:\n{ref_link}"
    )

async def device_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление устройствами"""
    # Логика проверки активных подключений
    await update.message.reply_text(
        "📱 Активные устройства:\n"
        "1. Android [IP: 192.168.1.101]\n"
        "2. Windows [IP: 192.168.1.102]\n\n"
        "❌ Для отключения используйте /revoke <номер>"
    )

async def server_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор сервера"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Москва", callback_data="server_ru")],
        [InlineKeyboardButton("🇩🇪 Берлин", callback_data="server_de")],
        [InlineKeyboardButton("🇺🇸 Нью-Йорк", callback_data="server_us")]
    ])
    
    await update.message.reply_text(
        "🌍 Выберите сервер:",
        reply_markup=keyboard
    )

# ==================  PAYMENT  ================== #

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора способа оплаты"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплата картой", callback_data="pay_card")],
        [InlineKeyboardButton("⭐️ Telegram Stars", callback_data="pay_stars")]
    ])
    
    await update.message.reply_text(
        "🎁 Выберите способ оплаты:",
        reply_markup=keyboard
    )

async def handle_payment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора оплаты"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "pay_card":
        await send_card_invoice(query)
    elif query.data == "pay_stars":
        await send_stars_invoice(query)

async def send_card_invoice(query):
    """Инвойс для оплаты картой"""
    await query.message.reply_invoice(
        title="VPN Premium (Карта)",
        description="Доступ к VPN на 1 месяц",
        payload="card_payment",
        provider_token="YOUR_CARD_PROVIDER_TOKEN",  # Токен для карт
        currency="RUB",
        prices=[LabeledPrice("Месячная подписка", 49000)],
        need_phone_number=False,
        need_email=False
    )

async def send_stars_invoice(query):
    """Инвойс для оплаты Stars"""
    await query.message.reply_invoice(
        title="VPN Premium (Stars)",
        description="Доступ к VPN на 1 месяц",
        payload="stars_payment",
        provider_token="YOUR_STARS_PROVIDER_TOKEN",  # Токен для Stars
        currency="XTR",
        prices=[LabeledPrice("Месячная подписка", 50 * 100)],  # 50 Stars
        need_phone_number=False,
        need_email=False
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение платежа"""
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешного платежа"""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    
    # Обновляем срок подписки
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    
    conn = sqlite3.connect('vpn_keys.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET expires_at = ? 
        WHERE user_id = ?
    ''', (expires_at.isoformat(), user_id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ Подписка успешно активирована!")

# ================= ЗАПУСК БОТА ================= #

async def check_subscriptions(app: Application):
    """Ежедневная проверка подписок"""
    try:
        with sqlite3.connect('vpn_keys.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE expires_at < ?", 
                         (datetime.now(timezone.utc).isoformat(),))
            
            for user_id, in cursor.fetchall():
                await app.bot.send_message(
                    user_id,
                    "⚠️ Ваша подписка истекает через 3 дня! Продлите её командой /buy"
                )
    except Exception as e:
        logger.error(f"Subscription check error: {e}")

async def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # Планировщик задач
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_subscriptions,
        IntervalTrigger(days=1),
        args=[application]
    )
    scheduler.start()

    # Регистрация обработчиков
    handlers = [
        CommandHandler("start", start),
        CommandHandler("getkey", getkey),
        CommandHandler("dns", dns),
        CommandHandler("support", support),
        CommandHandler("stats", stats),
        CommandHandler("allkeys", allkeys),
        CommandHandler("myid", myid),
        CommandHandler("buy", buy),
        CommandHandler("ref", referral_system),
        CommandHandler("devices", device_management),
        CommandHandler("servers", server_selection),
        CallbackQueryHandler(button_handler),
        CallbackQueryHandler(handle_payment_choice, pattern=r"^(pay_card|pay_stars)$"),
        PreCheckoutQueryHandler(precheckout),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment),
        MessageHandler(filters.TEXT & ~filters.COMMAND, start)
    ]

    for handler in handlers:
        application.add_handler(handler)

    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())