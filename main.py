import os
import json
import asyncio
import time
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import xendit

# --- Konfigurasi lingkungan ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@admin")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
LOGO_URL = os.getenv("LOGO_URL", "https://i.imgur.com/default-logo.png")

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

xendit.api_key = XENDIT_API_KEY
app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- Fungsi bantu ---
def muat_data(file_path):
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except:
        return []

def simpan_data(data, file_path):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

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

# --- Command handler ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    await update.message.reply_photo(
        photo=LOGO_URL,
        caption="Selamat datang! Klik tombol di bawah.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Silakan ketik /start untuk memulai.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cek_stok":
        products = muat_data("products.json")
        keyboard = []
        for p in products:
            if p.get("stok_akun"):
                keyboard.append([
                    InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")
                ])
        await query.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("order_"):
        produk_id = query.data.split("_")[1]
        produk = next((p for p in muat_data("products.json") if p['id'] == produk_id), None)
        if not produk:
            await query.edit_message_text("Produk tidak ditemukan atau stok habis.")
            return
        invoice = xendit.Invoice.create(
            external_id=f"inv_{int(time.time())}",
            amount=produk['harga'],
            description=produk['nama'],
            customer={'given_names': update.effective_user.full_name}
        )
        orders = muat_data("orders.json")
        orders.append({
            "external_id": invoice.external_id,
            "user_id": update.effective_user.id,
            "produk_id": produk_id,
            "harga": produk['harga'],
            "status": "PENDING"
        })
        simpan_data(orders, "orders.json")
        await context.bot.send_message(update.effective_user.id, f"Bayar di sini:
{invoice.invoice_url}")

# --- Telegram webhook route ---
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    asyncio.create_task(bot_app.process_update(update))
    return JSONResponse(content={"status": "ok"})

# --- Xendit webhook route ---
@app.post("/webhook/xendit")
async def xendit_webhook(request: Request):
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    data = await request.json()
    if data.get("status") == "PAID":
        external_id = data.get("external_id")
        orders = muat_data("orders.json")
        order = next((o for o in orders if o['external_id'] == external_id and o['status'] == "PENDING"), None)
        if order:
            order['status'] = 'PAID'
            simpan_data(orders, "orders.json")
            akun = ambil_akun_dari_stok(order['produk_id'])
            if akun:
                await bot_app.bot.send_message(order['user_id'], f"✅ Pembayaran berhasil! Berikut akunmu: `{akun}`", parse_mode='Markdown')
            else:
                await bot_app.bot.send_message(order['user_id'], "Stok habis. Admin akan hubungi kamu segera.")
    return {"status": "ok"}

# --- Setup handlers dan webhook ---
@app.on_event("startup")
async def startup():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    await bot_app.initialize()
    await bot_app.bot.set_webhook(os.getenv("WEBHOOK_URL") + "/telegram")
    await bot_app.bot.set_my_commands([BotCommand("start", "Mulai bot")])
