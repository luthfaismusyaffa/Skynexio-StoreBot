import os, time, logging, asyncio
from flask import Flask, request, jsonify
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import xendit
import supabase_client as db

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

xendit.api_key = XENDIT_API_KEY

app = Flask(__name__)
bot = Application.builder().token(TELEGRAM_TOKEN).build()
logging.basicConfig(level=logging.INFO)

# ADMIN CEK

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# HANDLER
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    products = db.get_products()
    teks = "Selamat datang! Klik tombol di bawah."
    btns = [[InlineKeyboardButton("Lihat Produk", callback_data="cek")]]
    await update.message.reply_text(teks, reply_markup=InlineKeyboardMarkup(btns))

async def btn_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "cek":
        rows = db.get_products()
        buttons = [
            [InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']}", callback_data=f"buy_{p['id']}")]
            for p in rows if db.get_stock(p['id'])
        ]
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(buttons))
    elif q.data.startswith("buy_"):
        pid = q.data.split("_",1)[1]
        produk = next((p for p in db.get_products() if p["id"]==pid), None)
        if not produk:
            return await q.edit_message_text("Produk tidak ditemukan atau stok habis.")
        external_id = f"order-{pid}-{q.from_user.id}-{int(time.time())}"
        invoice = xendit.Invoice.create(
            external_id=external_id,
            amount=produk['harga'],
            description=produk['nama'],
            customer={"given_names": q.from_user.full_name}
        )
        db.insert_order(external_id, q.from_user.id, pid, produk['harga'])
        await q.edit_message_text(f"Berikut link pembayaran:
{invoice.invoice_url}")

# ADMIN
async def new_product(update: Update, ctx):
    if not is_admin(update): return
    args = " ".join(ctx.args).split("|")
    if len(args)<4: return await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")
    idp,n,h,d = [x.strip() for x in args]
    db.HEADERS
    requests.post(f"{os.getenv('SUPABASE_URL')}/rest/v1/products", headers=db.HEADERS, json={
        "id": idp, "nama": n, "harga": int(h), "deskripsi": d
    })
    await update.message.reply_text("✅ Produk ditambahkan")

# TEXT
async def fallback(update: Update, ctx):
    await update.message.reply_text("Silakan ketik /start untuk mulai.")

# WEBHOOK
@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot.bot)
    await bot.process_update(update)
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def webhook_x():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return "unauthorized", 403
    data = request.json
    if data["status"] == "PAID":
        ext_id = data["external_id"]
        pid = ext_id.split("-")[1] if "-" in ext_id else None
        akun = db.pop_one_akun(pid) if pid else None
        db.update_order_status(ext_id, akun_id=akun["id"] if akun else None)
        order = db.get_order_user(ext_id)
        if order:
            chat_id = order[0]["user_id"]
            bot.bot.send_message(chat_id, f"✅ Pembayaran diterima! Akun:
{akun['detail'] if akun else 'Kosong'}")
    return jsonify(ok=True)

@app.route("/")
def index(): return "OK"

# RUN
async def setup():
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("newproduct", new_product))
    bot.add_handler(CallbackQueryHandler(btn_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    await bot.initialize()
    await bot.bot.set_webhook(os.getenv("WEBHOOK_URL") + "/telegram")

def main():
    asyncio.run(setup())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
