import os
import json
import logging
import asyncio
import time
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit

# Konfigurasi
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@watchingnemo")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inisialisasi
xendit.api_key = XENDIT_API_KEY
app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# Helper JSON

def muat_data(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except:
        return [] if file.endswith(".json") else {}

def simpan_data(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def ambil_akun_dari_stok(produk_id):
    products = muat_data("products.json")
    for p in products:
        if p['id'] == produk_id and p.get('stok_akun'):
            akun = p['stok_akun'].pop(0)
            simpan_data(products, "products.json")
            return akun
    return None

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# Command
async def start(update: Update, context):
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 1000)
    counters.setdefault('total_turnover', 5000000)
    counters['total_orders'] += 1
    simpan_data(counters, 'counter.json')

    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    pesan = (
        f"**Selamat datang di Skynexio Store!**\n\n"
        f"📈 Total Pesanan: **{counters['total_orders']:,}**\n"
        f"💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n\n"
        "Klik tombol di bawah untuk melihat produk."
    )
    await update.message.reply_photo(photo=LOGO_URL, caption=pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context):
    await update.message.reply_text("Ketik /start untuk melihat produk tersedia.")

async def button(update: Update, context):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "cek_stok":
        products = muat_data("products.json")
        keyboard = []
        for p in products:
            if p.get('stok_akun'):
                keyboard.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="kembali")])
        await query.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("order_"):
        produk_id = query.data.split('_')[1]
        produk = next((p for p in muat_data("products.json") if p['id'] == produk_id), None)
        if not produk:
            await query.edit_message_text("Stok habis atau produk tidak ditemukan.")
            return
        await query.edit_message_text("Membuat invoice...")
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
            await context.bot.send_message(chat_id, f"Link pembayaran:\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(e)
            await query.edit_message_text("Gagal membuat invoice.")

    elif query.data == "kembali":
        await query.message.delete()
        class Dummy:
            def __init__(self, msg): self.message = msg
        await start(Dummy(query.message), context)

# Register
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
bot_app.add_handler(CallbackQueryHandler(button))

@app.on_event("startup")
async def on_startup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram")
    await bot_app.bot.set_my_commands([BotCommand("start", "Mulai bot")])
    logger.info("Webhook dan perintah bot berhasil disetel.")

@app.post("/telegram")
async def telegram_webhook(req: Request):
    try:
        data = await req.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(e)
        return JSONResponse(content={"status": "error"}, status_code=500)

@app.post("/webhook/xendit")
async def xendit_webhook(req: Request, x_callback_token: str = Header(...)):
    if x_callback_token != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return JSONResponse(status_code=403, content={"status": "unauthorized"})

    data = await req.json()
    if data.get("status") == "PAID":
        external_id = data.get("external_id")
        orders = muat_data("orders.json")
        order = next((o for o in orders if o['external_id'] == external_id and o['status'] == "PENDING"), None)
        if order:
            order['status'] = "PAID"
            simpan_data(orders, "orders.json")

            akun = ambil_akun_dari_stok(order['produk_id'])
            if akun:
                await bot_app.bot.send_message(order['user_id'], f"✅ Pembayaran diterima! Berikut akunmu:\n`{akun}`\n\nHubungi {ADMIN_USERNAME} jika ada masalah.", parse_mode='Markdown')
            else:
                await bot_app.bot.send_message(order['user_id'], "Pembayaran diterima, tapi stok kosong. Admin akan menghubungi Anda.")

    return {"status": "ok"}
