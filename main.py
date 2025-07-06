import os, time, asyncio, httpx
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import xendit
from supabase_client import *

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot = Application.builder().token(TELEGRAM_TOKEN).build()

# ========== BOT COMMAND ==========
def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    btn = [[InlineKeyboardButton("📦 Lihat Produk", callback_data="cek_produk")]]
    await update.message.reply_text("Selamat datang!", reply_markup=InlineKeyboardMarkup(btn))

async def new_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    args = " ".join(ctx.args).split("|")
    if len(args) < 4:
        return await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")
    idp, nama, harga, deskripsi = [x.strip() for x in args]
    requests.post(f"{SUPABASE_URL}/rest/v1/products", headers=HEADERS,
                  json={"id": idp, "nama": nama, "harga": int(harga), "deskripsi": deskripsi})
    await update.message.reply_text(f"✅ Produk '{nama}' ditambahkan.")

async def add_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    pid = ctx.args[0]
    akun = " ".join(ctx.args[1:])
    requests.post(f"{SUPABASE_URL}/rest/v1/stok_akun", headers=HEADERS,
                  json={"produk_id": pid, "detail": akun})
    await update.message.reply_text("✅ Stok ditambahkan.")

async def info_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    teks = "📦 Info Stok:\n"
    for p in get_products():
        jumlah = len(get_stock(p["id"]))
        teks += f"- {p['nama']} ({p['id']}): {jumlah} akun\n"
    await update.message.reply_text(teks)

# ========== CALLBACK ==========
async def handle_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cek_produk":
        btns = []
        for p in get_products():
            if get_stock(p["id"]):
                btns.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']}", callback_data=f"buy_{p['id']}")])
        await query.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(btns))
    elif query.data.startswith("buy_"):
        pid = query.data.split("_", 1)[1]
        produk = next((p for p in get_products() if p["id"] == pid), None)
        if not produk:
            return await query.edit_message_text("Produk tidak ditemukan.")
        ext_id = f"order-{pid}-{query.from_user.id}-{int(time.time())}"
        invoice = xendit.Invoice.create(
            external_id=ext_id,
            amount=produk["harga"],
            description=produk["nama"],
            customer={"given_names": query.from_user.full_name}
        )
        insert_order(ext_id, query.from_user.id, pid, produk["harga"])
        await query.edit_message_text(f"Berikut link pembayaran:\n{invoice.invoice_url}")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gunakan /start untuk mulai.")

# ========== FLASK ROUTES ==========
@app.route("/")
def root(): return "OK"

@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    update_data = request.get_json(force=True)
    update = Update.de_json(update_data, bot.bot)
    await bot.process_update(update)
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return "Unauthorized", 403
    d = request.json
    if d.get("status") != "PAID":
        return jsonify(ok=True)

    external_id = d.get("external_id", "")
    order = get_order_user(external_id)
    if not order: return jsonify({"error": "Order not found"}), 400

    produk_id = order[0]["produk_id"]
    akun = pop_one_akun(produk_id)
    if not akun:
        return jsonify({"error": "No stock left"}), 400

    update_order_status(external_id, akun["id"])

    msg = f"✅ Pembayaran diterima!\nBerikut akun kamu:\n`{akun['detail']}`"
    httpx.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
        "chat_id": order[0]["user_id"],
        "text": msg,
        "parse_mode": "Markdown"
    })
    return jsonify(ok=True)

# ========== START ==========
async def run():
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("newproduct", new_product))
    bot.add_handler(CommandHandler("add", add_stock))
    bot.add_handler(CommandHandler("infostock", info_stock))
    bot.add_handler(CallbackQueryHandler(handle_button))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    await bot.initialize()
    await bot.bot.set_webhook(WEBHOOK_URL + "/telegram", allowed_updates=Update.ALL_TYPES)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
