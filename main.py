# main.py
import os
import json
import logging
import time
import random
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit

# --- Konfigurasi ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@admin")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
xendit.api_key = XENDIT_API_KEY

# --- Helper JSON ---
def load_json(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except:
        return []

def save_json(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def ambil_akun(produk_id):
    data = load_json("products.json")
    for produk in data:
        if produk['id'] == produk_id and produk.get('stok_akun'):
            akun = produk['stok_akun'].pop(0)
            save_json(data, "products.json")
            return akun
    return None

# --- Command Handler ---
async def start(update, context):
    counters = load_json("counter.json")
    counters.setdefault('total_orders', 500)
    counters.setdefault('total_turnover', 1000000)
    counters['total_orders'] += random.randint(1, 3)
    save_json(counters, "counter.json")

    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    text = (f"**Selamat datang di Skynexio Store!**\n\n"
            f"📈 Total Pesanan: **{counters['total_orders']}**\n"
            f"💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n\n"
            "Klik tombol di bawah untuk mulai.")

    await update.message.reply_photo(photo=LOGO_URL, caption=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update, context):
    await update.message.reply_text("Ketik /start untuk memulai")

async def button(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "cek_stok":
        produk = load_json("products.json")
        keyboard = []
        for p in produk:
            if p.get("stok_akun"):
                keyboard.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="kembali")])
        await query.edit_message_text("Silakan pilih produk:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("order_"):
        produk_id = data.split("_", 1)[1]
        produk = next((p for p in load_json("products.json") if p['id'] == produk_id), None)
        if not produk:
            await query.edit_message_text("Stok habis atau produk tidak ditemukan.")
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
            orders = load_json("orders.json")
            orders.append({"external_id": external_id, "user_id": update.effective_user.id, "produk_id": produk_id, "status": "PENDING", "harga": produk['harga']})
            save_json(orders, "orders.json")
            await context.bot.send_message(chat_id, f"Link pembayaran:
{invoice.invoice_url}")
        except Exception as e:
            logger.error(e)
            await query.edit_message_text("Gagal membuat invoice.")

    elif data == "kembali":
        await query.message.delete()
        class Fake:
            def __init__(self, m): self.message = m
        await start(Fake(query.message), context)

# --- Telegram Webhook Endpoint ---
@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.initialize()
        await bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"status": "error"}

# --- Xendit Webhook Endpoint ---
@app.post("/webhook/xendit")
async def xendit_webhook(request: Request):
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return JSONResponse(status_code=403, content={"status": "forbidden"})

    data = await request.json()
    if data.get("status") == "PAID":
        external_id = data.get("external_id")
        orders = load_json("orders.json")
        order = next((o for o in orders if o['external_id'] == external_id and o['status'] == "PENDING"), None)
        if order:
            order['status'] = "PAID"
            save_json(orders, "orders.json")
            akun = ambil_akun(order['produk_id'])
            if akun:
                await bot_app.bot.send_message(order['user_id'], f"✅ Pembayaran berhasil! Berikut akun kamu:
`{akun}`", parse_mode="Markdown")
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Pesanan baru dibayar!\nAkun: {akun}")
            else:
                await bot_app.bot.send_message(order['user_id'], "Pembayaran berhasil, tapi stok kosong. Admin akan hubungi kamu segera.")
    return {"status": "ok"}

# --- Setup ---
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
bot_app.add_handler(CallbackQueryHandler(button))

# --- Jalankan: uvicorn main:app (Procfile) ---
