import os
import json
import asyncio
import logging
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# Konfigurasi lingkungan
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inisialisasi Flask & Bot
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# Fungsi utilitas def

def muat_data(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except:
        return {}

def simpan_data(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

# Command Handlers

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 1000)
    counters.setdefault('total_turnover', 5000000)
    counters['total_orders'] += 1
    simpan_data(counters, 'counter.json')
    await update.message.reply_photo(
        photo=LOGO_URL,
        caption=(f"Selamat datang!\n\nTotal Pesanan: {counters['total_orders']}\nTotal Transaksi: Rp{counters['total_turnover']:,}\n\nGunakan tombol di bawah untuk cek stok."),
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hai! Gunakan /start untuk memulai 😊")

# Setup Bot Handler

def setup_handlers():
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# Route Webhook Telegram
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.create_task(bot_app.process_update(update))
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Telegram Webhook Error: {e}")
        return jsonify({"status": "error"}), 500

# Web Index
@app.route("/")
def index():
    return "Bot Aktif 🚀"

# Setup & Main

def main():
    setup_handlers()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_app.initialize())
    loop.run_until_complete(bot_app.start())
    loop.run_until_complete(bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram"))
    loop.run_until_complete(bot_app.bot.set_my_commands([
        BotCommand("start", "Mulai bot")
    ]))
    logger.info("Bot aktif dan webhook diset.")
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == '__main__':
    main()
