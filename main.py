import os, logging, json, time, random, asyncio
from flask import Flask, request, jsonify
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import requests
import xendit
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user

# === ENV SETUP ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
XENDIT_API_KEY = os.environ["XENDIT_API_KEY"]
XENDIT_WEBHOOK_TOKEN = os.environ["XENDIT_WEBHOOK_VERIFICATION_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# === INIT ===
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# === ADMIN HELPERS ===
def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def new_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        args = " ".join(ctx.args).split("|")
        if len(args) < 4:
            return await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")
        idp, n, h, d = [x.strip() for x in args]
        requests.post(
            f"{os.environ['SUPABASE_URL']}/rest/v1/products",
            headers={"apikey": os.environ["SUPABASE_KEY"], "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}",
                     "Content-Type": "application/json"},
            json={"id": idp, "nama": n, "harga": int(h), "deskripsi": d}
        )
        await update.message.reply_text(f"✅ Produk '{n}' ditambahkan.")
    except Exception as e:
        await update.message.reply_text("Gagal menambahkan produk.")
        logger.error(e)

async def add_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        pid = ctx.args[0]
        akun = " ".join(ctx.args[1:])
        requests.post(
            f"{os.environ['SUPABASE_URL']}/rest/v1/stok_akun",
            headers={"apikey": os.environ["SUPABASE_KEY"], "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}",
                     "Content-Type": "application/json"},
            json={"produk_id": pid, "detail": akun, "sold": False}
        )
        await update.message.reply_text(f"✅ Stok akun ditambahkan ke '{pid}'.")
    except Exception as e:
        await update.message.reply_text("Format: /add <produk_id> <akun_detail>")
        logger.error(e)

async def info_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    rows = get_products()
    teks = "📦 Stok Produk:\n"
    for p in rows:
        stok = len(get_stock(p["id"]))
        teks += f"- {p['nama']} (`{p['id']}`): {stok} akun\n"
    await update.message.reply_text(teks, parse_mode="Markdown")


# === PENGGUNA HANDLER ===
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = get_products()
    teks = f"**Selamat datang!** Silakan cek stok produk..."
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_photo(photo=LOGO_URL, caption=teks, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btn))

async def btn_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        await q.edit_message_text("Membuat invoice...")
        ext = f"invoice_{pid}_{q.from_user.id}_{int(time.time())}"
        inv = xendit.Invoice.create(
            external_id=ext,
            amount=prod["harga"],
            description=prod["nama"],
            customer={"given_names": q.from_user.full_name}
        )
        insert_order(ext, q.from_user.id, pid, prod["harga"])
        await q.edit_message_text(f"✅ Berikut link pembayaran:\n{inv.invoice_url}")
    elif q.data == "back":
        return await start(update, ctx)

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gunakan /start untuk mulai.")

# === WEBHOOK ROUTES ===
@app.route("/", methods=["GET"])
def index(): return "OK"

@app.route("/webhook/xendit", methods=["POST"])
def xendit_webhook():
    try:
        if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
            return "forbidden", 403
        data = request.get_json()
        if data.get("status") == "PAID":
            ext_id = data["external_id"]
            user_data = get_order_user(ext_id)
            if not user_data:
                return jsonify({"error": "Order not found"}), 400
            akun = pop_one_akun(ext_id.split("_")[1])
            update_order_status(ext_id, akun_id=akun["id"])
            chat_id = user_data[0]["user_id"]
            bot_app.bot.send_message(chat_id, f"✅ Pembayaran diterima!\nAkun kamu: `{akun['detail']}`", parse_mode="Markdown")
        return jsonify(ok=True)
    except Exception as e:
        logger.error("Xendit Webhook Error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, bot_app.bot)
        asyncio.run(bot_app.process_update(update))
        return jsonify(ok=True)
    except Exception as e:
        logger.error("Telegram Webhook Error: %s", e)
        return jsonify({"error": str(e)}), 500

# === BOT INIT ===
async def setup_bot():
    await bot_app.bot.set_webhook(WEBHOOK_URL + "/telegram")
    await bot_app.bot.set_my_commands([
        BotCommand("start", "Mulai bot"),
        BotCommand("newproduct", "Tambah produk (admin)"),
        BotCommand("add", "Tambah stok (admin)"),
        BotCommand("infostock", "Cek stok (admin)")
    ])
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("newproduct", new_product))
    bot_app.add_handler(CommandHandler("add", add_stock))
    bot_app.add_handler(CommandHandler("infostock", info_stock))
    bot_app.add_handler(CallbackQueryHandler(btn_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_bot())

    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
