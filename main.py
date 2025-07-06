import os
import json
import time
import random
import logging
import asyncio

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit

# Konfigurasi
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@admin")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
LOGO_URL = os.getenv("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup Flask & Telegram Bot
app = Flask(__name__)
xendit.api_key = XENDIT_API_KEY
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# ------------------- Helper Functions -------------------
def muat_data(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return []

def simpan_data(data, path):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def ambil_akun_dari_stok(produk_id):
    products = muat_data("products.json")
    for p in products:
        if p['id'] == produk_id and p.get('stok_akun'):
            akun = p['stok_akun'].pop(0)
            simpan_data(products, 'products.json')
            return akun
    return None

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# ------------------- Handlers -------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 1000)
    counters.setdefault('total_turnover', 1000000)
    counters['total_orders'] += random.randint(1, 2)
    simpan_data(counters, 'counter.json')

    msg = (
        f"**Selamat datang di Skynexio Store!**\n\n"
        f"📈 Total Pesanan: **{counters['total_orders']:,}**\n"
        f"💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n\n"
        f"Klik tombol di bawah untuk cek produk!"
    )
    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    await update.message.reply_photo(photo=LOGO_URL, caption=msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hai! Gunakan /start untuk mulai 😊")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "cek_stok":
        products = muat_data("products.json")
        keyboard = [
            [InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")]
            for p in products if p.get('stok_akun')
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="kembali")])
        await query.edit_message_text("Pilih produk yang ingin kamu beli:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("order_"):
        produk_id = query.data.split("_")[1]
        produk = next((p for p in muat_data("products.json") if p['id'] == produk_id), None)
        if not produk:
            await context.bot.send_message(chat_id, "❌ Produk tidak ditemukan atau stok habis.")
            return

        await query.edit_message_text("⏳ Membuat invoice...")
        try:
            external_id = f"{produk_id}-{chat_id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=produk['nama'],
                customer={"given_names": query.from_user.full_name}
            )
            orders = muat_data("orders.json")
            orders.append({
                "external_id": external_id,
                "user_id": chat_id,
                "produk_id": produk_id,
                "harga": produk['harga'],
                "status": "PENDING"
            })
            simpan_data(orders, "orders.json")
            await context.bot.send_message(chat_id, f"✅ Silakan bayar di link berikut:\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(e)
            await context.bot.send_message(chat_id, "❌ Gagal membuat invoice.")

    elif query.data == "kembali":
        await query.message.delete()
        class Fake:
            def __init__(self, m): self.message = m
        await start_command(Fake(query.message), context)

# ------------------- Webhook Routes -------------------
@app.route('/')
def index():
    return "Skynexio Bot Running"

@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.create_task(bot_app.process_update(update))  # jangan pakai asyncio.run()
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"[Telegram Error] {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/webhook/xendit', methods=['POST'])
def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({"status": "forbidden"}), 403

    data = request.json
    if data.get("status") == "PAID":
        external_id = data.get("external_id")
        orders = muat_data("orders.json")
        order = next((o for o in orders if o["external_id"] == external_id and o["status"] == "PENDING"), None)
        if order:
            order["status"] = "PAID"
            simpan_data(orders, "orders.json")

            akun = ambil_akun_dari_stok(order["produk_id"])
            pesan = f"✅ Pembayaran diterima!\n\nAkunmu: `{akun}`\n\nHubungi {ADMIN_USERNAME} jika ada kendala."
            asyncio.create_task(bot_app.bot.send_message(order["user_id"], pesan, parse_mode='Markdown'))
    return jsonify({"status": "ok"})

# ------------------- Setup -------------------
def setup_handlers():
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("infostok", handle_text))  # ganti jika kamu punya
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

def run_webhook():
    setup_handlers()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot_app.initialize())
    loop.run_until_complete(bot_app.start())
    loop.run_until_complete(bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram"))
    loop.run_until_complete(bot_app.bot.set_my_commands([
        BotCommand("start", "Mulai bot"),
        BotCommand("infostok", "Cek stok produk")
    ]))
    logger.info("Bot & Webhook aktif")
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    run_webhook()
