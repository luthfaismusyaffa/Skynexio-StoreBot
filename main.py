import os, logging, json, time
from flask import Flask, request, jsonify
from telegram import Bot, Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user

# ENV VARS
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
XENDIT_API_KEY = os.environ["XENDIT_API_KEY"]
XENDIT_WEBHOOK_TOKEN = os.environ["XENDIT_WEBHOOK_VERIFICATION_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

bot = Bot(token=TELEGRAM_TOKEN)
xendit.api_key = XENDIT_API_KEY

app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

logging.basicConfig(level=logging.INFO)

# === ADMIN CHECK
def is_admin(update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# === HANDLERS ===
def start(update, context):
    rows = get_products()
    teks = "👋 Selamat datang! Silakan pilih produk yang tersedia:"
    btn = [[InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']}", callback_data=f"buy_{p['id']}")] for p in rows if get_stock(p["id"])]
    update.message.reply_text(teks, reply_markup=InlineKeyboardMarkup(btn))

def add(update, context):
    if not is_admin(update): return
    try:
        pid = context.args[0]
        akun = " ".join(context.args[1:])
        from supabase_client import SUPABASE_URL, HEADERS
        import requests
        data = {"produk_id": pid, "detail": akun, "sold": False}
        requests.post(f"{SUPABASE_URL}/rest/v1/stok_akun", headers=HEADERS, json=data)
        update.message.reply_text("✅ Akun berhasil ditambahkan.")
    except:
        update.message.reply_text("Format: /add <produk_id> <email:pass/pin>")

def newproduct(update, context):
    if not is_admin(update): return
    try:
        idp, nama, harga, deskripsi = " ".join(context.args).split("|")
        from supabase_client import SUPABASE_URL, HEADERS
        import requests
        data = {"id": idp.strip(), "nama": nama.strip(), "harga": int(harga.strip()), "deskripsi": deskripsi.strip()}
        requests.post(f"{SUPABASE_URL}/rest/v1/products", headers=HEADERS, json=data)
        update.message.reply_text("✅ Produk ditambahkan.")
    except:
        update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")

def info(update, context):
    if not is_admin(update): return
    rows = get_products()
    msg = "📦 Info stok:\n"
    for p in rows:
        jumlah = len(get_stock(p["id"]))
        msg += f"- {p['nama']} ({p['id']}): {jumlah} akun\n"
    update.message.reply_text(msg)

def callback_handler(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("buy_"):
        pid = data.split("_", 1)[1]
        produk = next((p for p in get_products() if p["id"] == pid), None)
        if not produk:
            return query.edit_message_text("❌ Produk tidak ditemukan.")
        ext_id = f"inv-{pid}-{query.from_user.id}-{int(time.time())}"
        invoice = xendit.Invoice.create(
            external_id=ext_id,
            amount=produk["harga"],
            description=produk["nama"],
            customer={"given_names": query.from_user.full_name}
        )
        insert_order(ext_id, query.from_user.id, pid, produk["harga"])
        return query.edit_message_text(f"✅ Invoice siap dibayar:\n{invoice.invoice_url}")

def text_handler(update, context):
    update.message.reply_text("Gunakan /start untuk melihat produk.")

# === FLASK ROUTES ===
@app.route("/", methods=["GET"])
def index(): return "Bot aktif!"

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return "Unauthorized", 403
    data = request.json
    if data.get("status") == "PAID":
        ext_id = data.get("external_id")
        akun = pop_one_akun(ext_id.split("-")[1])
        update_order_status(ext_id, akun_id=akun["id"])
        user_id = get_order_user(ext_id)[0]["user_id"]
        bot.send_message(user_id, f"✅ Pembayaran diterima!\nAkunmu: `{akun['detail']}`", parse_mode="Markdown")
    return jsonify(ok=True)

# === REGISTER HANDLER
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("add", add))
dispatcher.add_handler(CommandHandler("newproduct", newproduct))
dispatcher.add_handler(CommandHandler("infostock", info))
dispatcher.add_handler(CallbackQueryHandler(callback_handler))
dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

# === MAIN ===
if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
