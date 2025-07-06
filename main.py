import os
import logging
import json
import time
import asyncio
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import xendit

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
xendit.api_key = XENDIT_API_KEY

app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- FUNGSI DATA ---
def muat_data(file_path):
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if file_path.endswith(".json") else {}

def simpan_data(data, file_path):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

def ambil_akun_dari_stok(produk_id):
    products = muat_data("products.json")
    for p in products:
        if p["id"] == produk_id and p.get("stok_akun"):
            akun = p["stok_akun"].pop(0)
            simpan_data(products, "products.json")
            return akun
    return None

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# --- PERINTAH ADMIN ---
async def info_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = muat_data("products.json")
    msg = "📦 Daftar Stok Produk:\n\n"
    for p in products:
        msg += f"- {p['nama']} (`{p['id']}`): {len(p.get('stok_akun', []))} akun\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- PENGGUNA ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data('counter.json')
    counters.setdefault("total_orders", 1000)
    counters.setdefault("total_turnover", 5000000)
    counters["total_orders"] += 1
    simpan_data(counters, 'counter.json')

    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    text = (
        f"**Selamat datang di Skynexio Store!**\n\n"
        f"📈 Total Pesanan: **{counters['total_orders']:,}**\n"
        f"💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n\n"
        "Klik tombol di bawah untuk melihat produk 👇"
    )
    await update.message.reply_photo(photo=LOGO_URL, caption=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hai! Untuk mulai, ketik /start ya 😊")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "cek_stok":
        products = muat_data("products.json")
        keyboard = []
        for p in products:
            if p.get("stok_akun"):
                keyboard.append([
                    InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")
                ])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="kembali")])
        await query.edit_message_text("Pilih produk yang ingin kamu beli:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("order_"):
        produk_id = data.split("_", 1)[1]
        produk = next((p for p in muat_data("products.json") if p["id"] == produk_id), None)
        if not produk:
            await query.edit_message_text("❌ Produk tidak ditemukan.")
            return
        await query.edit_message_text("Sedang membuat invoice...")
        try:
            external_id = f"order-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk["harga"],
                description=produk["nama"],
                customer={"given_names": update.effective_user.full_name}
            )
            orders = muat_data("orders.json")
            orders.append({
                "external_id": external_id,
                "user_id": update.effective_user.id,
                "produk_id": produk_id,
                "harga": produk["harga"],
                "status": "PENDING"
            })
            simpan_data(orders, "orders.json")
            await context.bot.send_message(chat_id, f"✅ Invoice siap dibayar!\n\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(e)
            await query.edit_message_text("❌ Gagal membuat invoice.")

    elif data == "kembali":
        await query.message.delete()
        class Fake: def __init__(self, m): self.message = m
        await start_command(Fake(query.message), context)

# --- ROUTE FLASK (SYNC MODE) ---
@app.route('/')
def index():
    return "Skynexio Bot is running."

@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        asyncio.run(bot_app.update_queue.put(update))
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"[Telegram Webhook Error] {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/webhook/xendit', methods=['POST'])
def xendit_webhook():
    if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({'status': 'unauthorized'}), 403
    try:
        data = request.json
        if data.get("status") == "PAID":
            external_id = data.get("external_id")
            orders = muat_data("orders.json")
            order = next((o for o in orders if o["external_id"] == external_id and o["status"] == "PENDING"), None)
            if order:
                order["status"] = "PAID"
                simpan_data(orders, "orders.json")

                akun = ambil_akun_dari_stok(order["produk_id"])
                if akun:
                    msg = f"✅ Pembayaran sukses!\n\nAkun kamu:\n`{akun}`\n\nHubungi admin @{ADMIN_USERNAME} jika ada kendala."
                    asyncio.run(bot_app.bot.send_message(order["user_id"], msg, parse_mode='Markdown'))
                    asyncio.run(bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan: {akun}"))
                else:
                    asyncio.run(bot_app.bot.send_message(order["user_id"], "✅ Pembayaran berhasil tapi stok kosong. Admin akan segera hubungi kamu."))
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"[Xendit Webhook Error] {e}")
        return jsonify({'status': 'error'}), 500

# --- SETUP ---
async def setup():
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("infostok", info_stock))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await bot_app.initialize()
    await bot_app.bot.set_webhook(f"{WEBHOOK_URL}/telegram")
    await bot_app.bot.set_my_commands([
        BotCommand("start", "Mulai bot"),
        BotCommand("infostok", "Lihat stok produk (admin)")
    ])
    logger.info("Bot dan webhook sudah siap.")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
