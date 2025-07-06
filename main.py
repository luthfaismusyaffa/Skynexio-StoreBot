import os
import json
import logging
import asyncio
import time
import random
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import xendit

# --- Konfigurasi ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "username_admin_anda")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Utils File ---
def muat_data(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if 's.json' in file_path else {}

def simpan_data(data, file_path):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def ambil_akun_dari_stok(produk_id):
    products = muat_data('products.json')
    for p in products:
        if p['id'] == produk_id and p.get('stok_akun'):
            akun = p['stok_akun'].pop(0)
            simpan_data(products, 'products.json')
            return akun
    return None

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# --- Admin Command ---
async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, akun_baru = context.args[0], " ".join(context.args[1:])
        products = muat_data('products.json')
        for p in products:
            if p['id'] == produk_id:
                p.setdefault('stok_akun', []).append(akun_baru)
                simpan_data(products, 'products.json')
                await update.message.reply_text(f"✅ Stok ditambahkan ke: {produk_id}")
                return
        await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except:
        await update.message.reply_text("Format: /add <id_produk> <akun>")

async def info_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = muat_data('products.json')
    pesan = "📦 Daftar Stok Produk:\n\n"
    for p in products:
        stok = len(p.get("stok_akun", []))
        pesan += f"- {p['nama']} (`{p['id']}`): {stok} akun\n"
    await update.message.reply_text(pesan, parse_mode='Markdown')

# --- Start & Pesan Pengguna ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data("counter.json")
    counters.setdefault("total_orders", 1000)
    counters.setdefault("total_turnover", 5000000)
    counters["total_orders"] += random.randint(1, 3)
    simpan_data(counters, "counter.json")

    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    pesan = (
        f"**Selamat datang di Skynexio Store!**\n\n"
        f"📈 Total Pesanan: **{counters['total_orders']:,}**\n"
        f"💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n\n"
        "Klik tombol di bawah untuk melihat produk yang tersedia:"
    )
    await update.message.reply_photo(logo_url, caption=pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hai! Untuk memulai, silakan ketik /start ya.")

# --- Button Handler ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    if data == 'cek_stok':
        products = muat_data("products.json")
        keyboard = []
        for p in products:
            if p.get("stok_akun"):
                keyboard.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        if not keyboard:
            await context.bot.send_message(chat_id, "Stok kosong. Coba lagi nanti 🙏")
            return
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="kembali")])
        await query.edit_message_text("Pilih produk yang ingin dibeli:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("order_"):
        produk_id = data.split("_", 1)[1]
        produk = next((p for p in muat_data("products.json") if p["id"] == produk_id), None)
        if not produk:
            await query.edit_message_text("Produk tidak ditemukan atau stok habis.")
            return

        await query.edit_message_text("Sedang membuat invoice...")
        try:
            external_id = f"order-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=produk['nama'],
                customer={'given_names': update.effective_user.full_name}
            )
            orders = muat_data('orders.json')
            orders.append({'external_id': external_id, 'user_id': update.effective_user.id, 'produk_id': produk_id, 'harga': produk['harga'], 'status': 'PENDING'})
            simpan_data(orders, 'orders.json')
            await context.bot.send_message(chat_id, f"Silakan selesaikan pembayaran:\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(e)
            await query.edit_message_text("Gagal membuat invoice.")

    elif data == "kembali":
        await query.message.delete()
        class Mock:
            def __init__(self, m): self.message = m
        await start_command(Mock(query.message), context)

# --- Flask Webhook ---
@app.route("/")
def index():
    return "Skynexio Bot Active"

@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        await bot_app.update_queue.put(update)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(e)
        return jsonify({"status": "error"}), 500

@app.route("/webhook/xendit", methods=["POST"])
async def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({"status": "unauthorized"}), 403
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
                await bot_app.bot.send_message(order["user_id"], f"✅ Pembayaran sukses!\nBerikut akun kamu:\n`{akun}`", parse_mode="Markdown")
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan sukses ke user {order['user_id']}\nAkun: {akun}")
            else:
                await bot_app.bot.send_message(order["user_id"], "Stok habis. Admin akan hubungi kamu.")
    return jsonify({"status": "ok"})

# --- Setup ---
async def setup():
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("add", add_stock))
    bot_app.add_handler(CommandHandler("infostok", info_stock))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    await bot_app.bot.set_my_commands([
        BotCommand("start", "🚀 Mulai"),
        BotCommand("infostok", "📦 Lihat stok (Admin)"),
    ])
    logger.info("Bot dan webhook siap.")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
