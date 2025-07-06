import os, logging, time, asyncio
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import httpx
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user
import xendit

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
LOGO_URL = "https://i.imgur.com/default-logo.png"

xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot = Application.builder().token(TELEGRAM_TOKEN).build()
logging.basicConfig(level=logging.INFO)

# Admin check
def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# Command: /newproduct
async def new_product(update: Update, context):
    if not is_admin(update): return
    args = " ".join(context.args).split("|")
    if len(args) < 4:
        return await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")
    idp, nama, harga, deskripsi = [x.strip() for x in args]
    from supabase_client import SUPABASE_URL, SUPABASE_KEY
    import requests
    requests.post(f"{SUPABASE_URL}/rest/v1/products", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }, json={"id": idp, "nama": nama, "harga": int(harga), "deskripsi": deskripsi})
    await update.message.reply_text("✅ Produk ditambahkan.")

# Command: /add
async def add_stock(update: Update, context):
    if not is_admin(update): return
    if len(context.args) < 2:
        return await update.message.reply_text("Format: /add <produk_id> <akun_detail>")
    produk_id = context.args[0]
    akun_detail = " ".join(context.args[1:])
    from supabase_client import SUPABASE_URL, SUPABASE_KEY
    import requests
    requests.post(f"{SUPABASE_URL}/rest/v1/stok_akun", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }, json={"produk_id": produk_id, "detail": akun_detail, "sold": False})
    await update.message.reply_text("✅ Akun ditambahkan.")

# Command: /infostock
async def info_stock(update: Update, context):
    if not is_admin(update): return
    teks = "📦 Stok Produk:\n"
    for p in get_products():
        stok = len(get_stock(p["id"]))
        teks += f"- {p['nama']} ({p['id']}): {stok} akun\n"
    await update.message.reply_text(teks)

# Start Command
async def start(update: Update, context):
    rows = get_products()
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_photo(photo=LOGO_URL, caption="Selamat datang! Klik tombol untuk cek stok produk:", reply_markup=InlineKeyboardMarkup(btn))

# Handle Button Click
async def btn_handler(update: Update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "cek":
        rows = get_products()
        btns = [[InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']}", callback_data=f"buy_{p['id']}")] for p in rows if get_stock(p["id"])]
        btns.append([InlineKeyboardButton("↩️ Kembali", callback_data="back")])
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(btns))
    elif q.data.startswith("buy_"):
        pid = q.data.split("_", 1)[1]
        prod = next((p for p in get_products() if p["id"] == pid), None)
        if not prod:
            return await q.edit_message_text("Stok habis 😢")
        external_id = f"order-{pid}-{q.from_user.id}-{int(time.time())}"
        invoice = xendit.Invoice.create(
            external_id=external_id,
            amount=prod["harga"],
            description=prod["nama"],
            customer={"given_names": q.from_user.full_name}
        )
        insert_order(external_id, q.from_user.id, pid, prod["harga"])
        await q.edit_message_text(f"Berikut link pembayaran:\n{invoice.invoice_url}")
    elif q.data == "back":
        await start(update, context)

# Text message fallback
async def text_handler(update: Update, context):
    await update.message.reply_text("Silakan gunakan /start untuk mulai.")

# Webhook root
@app.route("/", methods=["GET"])
def home(): return "OK"

# Telegram webhook
@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot.bot)
        await bot.process_update(update)
    except Exception as e:
        logging.error(f"Telegram webhook error: {e}")
    return jsonify(ok=True)

# Xendit webhook
@app.route("/webhook/xendit", methods=["POST"])
def webhook_xendit():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return "Forbidden", 403
    d = request.json
    if d.get("status") == "PAID":
        external_id = d["external_id"]
        update_order_status(external_id)
        akun = pop_one_akun(external_id.split("-")[1])
        order = get_order_user(external_id)
        chat_id = order[0]["user_id"]
        message = f"✅ Pembayaran diterima!\nBerikut detail akunmu:\n`{akun['detail']}`"
        httpx.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        })
    return jsonify(ok=True)

# Setup bot handler
async def setup():
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("newproduct", new_product))
    bot.add_handler(CommandHandler("add", add_stock))
    bot.add_handler(CommandHandler("infostock", info_stock))
    bot.add_handler(CallbackQueryHandler(btn_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await bot.initialize()
    await bot.bot.set_webhook(WEBHOOK_URL + "/telegram")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
