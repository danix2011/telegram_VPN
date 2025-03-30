import logging
import sqlite3
from io import BytesIO
import secrets
import asyncio
from datetime import datetime, timedelta, timezone, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Конфигурация
TOKEN = "7749755571:AAE4qmU7G04BpVzddPMjkzN3dAO9tj7qqrU"
ADMIN_IDS = [2134434120]
VPN_DNS = "1.1.1.1, 8.8.8.8"
KEY_EXPIRATION_DAYS = 30
WG_SERVER = {
    "public_key": "YOUR_WG_PUBLIC_KEY",
    "endpoint": "vpn.example.com:51820",
    "allowed_ips": "0.0.0.0/0",
    "dns": "1.1.1.1"
}

OVPN_SERVER = {
    "host": "vpn.example.com",
    "port": "1194",
    "proto": "udp"
}

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Инициализация БД
def init_db():
    conn = sqlite3.connect('vpn_keys.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            key TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Клавиатуры
user_keyboard = ReplyKeyboardMarkup(
    [["/getkey", "/dns"], ["/support"]],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    [["/stats", "/allkeys"], ["/broadcast"]],
    resize_keyboard=True
)

# Обработчик /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"🔑 Добро пожаловать, {user.first_name}!\n"
        "Выберите действие:\n"
        "• /getkey - Получить VPN-ключ\n"
        "• /dns - Рекомендуемые DNS\n"
        "• /support - Техподдержка"
    )
    
    if user.id in ADMIN_IDS:
        await update.message.reply_text("👑 Режим администратора", reply_markup=admin_keyboard)
    
    await update.message.reply_text(text, reply_markup=user_keyboard)

# Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "wg_config":
        await generate_config(update, context, "WireGuard")
    elif query.data == "ovpn_config":
        await generate_config(update, context, "OpenVPN")

async def generate_config(update: Update, context: ContextTypes.DEFAULT_TYPE, vpn_type: str):
    user_id = update.effective_user.id
    conn = sqlite3.connect('vpn_keys.db')
    
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT key FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result:
            await update.callback_query.message.reply_text("❌ Сначала получите ключ через /getkey")
            return

        vpn_key = result[0]
        config = ""
        filename = ""
        
        if vpn_type == "WireGuard":
            # Генерация конфига WireGuard
            config = f"""[Interface]

PrivateKey = {vpn_key}
Address = 10.0.0.{user_id % 254}/24
DNS = {WG_SERVER['dns']}

[Peer]
PublicKey = {WG_SERVER['public_key']}
Endpoint = {WG_SERVER['endpoint']}
AllowedIPs = {WG_SERVER['allowed_ips']}"""
            filename = f"wg-{user_id}.conf"
            
        elif vpn_type == "OpenVPN":
            # Генерация конфига OpenVPN (пример)
            config = f"""client
dev tun
proto {OVPN_SERVER['proto']}
remote {OVPN_SERVER['host']} {OVPN_SERVER['port']}
resolv-retry infinite
nobind
persist-key
persist-tun
<ca>
-----BEGIN CERTIFICATE-----
(вставьте CA сертификат)
-----END CERTIFICATE-----
</ca>
<cert>
-----BEGIN CERTIFICATE-----
(вставьте клиентский сертификат)
-----END CERTIFICATE-----
</cert>
<key>
-----BEGIN PRIVATE KEY-----
{vpn_key}
-----END PRIVATE KEY-----
</key>"""
            filename = f"ovpn-{user_id}.ovpn"
        
        # Отправка файла
        bio = BytesIO(config.encode())
        bio.name = filename
        await context.bot.send_document(
            chat_id=user_id,
            document=bio,
            caption=f"⚙️ {vpn_type} конфигурация для вашего ключа"
        )
        
    except Exception as e:
        logging.error(f"Ошибка генерации конфига: {e}")
        await update.callback_query.message.reply_text("⚠️ Ошибка генерации конфигурации")
        
    finally:
        conn.close()

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "wg_config":
        await generate_config(update, context, "WireGuard")
    elif query.data == "ovpn_config":
        await generate_config(update, context, "OpenVPN")

# Генерация ключа
def generate_config():
    return secrets.token_urlsafe(16)

# Клавиатура для пользователей
user_keyboard = ReplyKeyboardMarkup(
    [["/getkey", "/dns"], ["/support"]],
    resize_keyboard=True
)

# Админ-клавиатура
admin_keyboard = ReplyKeyboardMarkup(
    [["/stats", "/allkeys"], ["/broadcast"]],
    resize_keyboard=True
)

async def getkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = None
    try:
        conn = sqlite3.connect('vpn_keys.db')
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

        # Генерация нового ключа
        new_key = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + timedelta(days=KEY_EXPIRATION_DAYS)  # Теперь работает
        expires_str = expires_at.isoformat()

        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, key, expires_at)
            VALUES (?, ?, ?)
        ''', (user_id, new_key, expires_str))
        conn.commit()

        # Создаем клавиатуру с кнопками
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("WireGuard Config", callback_data="wg_config")],
            [InlineKeyboardButton("OpenVPN Config", callback_data="ovpn_config")]
        ])

        # Отправляем сообщение
        await update.message.reply_text(
            f"🎉 Новый ключ успешно создан!\n\n"
            f"🔑 Ваш ключ: `{new_key}`\n"
            f"⏳ Срок действия: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            "📎 Выберите тип конфигурации:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        await update.message.reply_text("⚠️ Ошибка работы с базой данных")
        
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        await update.message.reply_text("🚫 Произошла непредвиденная ошибка")
        
    finally:
        if conn:
            conn.close()

async def delete_expired_keys(context: ContextTypes.DEFAULT_TYPE):
    """Удаление просроченных ключей"""
    conn = sqlite3.connect('vpn_keys.db')
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE expires_at < ?', (datetime.utcnow().isoformat(),))
        conn.commit()
        logging.info(f"Удалено ключей: {cursor.rowcount}")
    except Exception as e:
        logging.error(f"Ошибка очистки: {e}")
    finally:
        conn.close()

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"🆔 Ваш ID: `{user_id}`", parse_mode='Markdown')

async def main():
    application = Application.builder().token(TOKEN).build()
    
    application.job_queue.run_daily(
        delete_expired_keys,
        time=time(hour=3, minute=0, tzinfo=timezone.utc)  # Используйте timezone.utc
    )
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getkey", getkey))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запускаем бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Бесконечный цикл
    while True:
        await asyncio.sleep(1)

# Запуск приложения
if __name__ == '__main__':
    import asyncio
    asyncio.run(main())  # <-- Здесь вызывается main()

async def cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    count = await delete_expired_keys()
    await update.message.reply_text(f"Очистка выполнена. Удалено ключей: {count}")
