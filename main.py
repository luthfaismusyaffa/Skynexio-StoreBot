import os, logging, time
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit
from supabase_client import *

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

# Init
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
logging.basicConfig(level=logging.INFO)

def is_admin(update): return str(update.effective_user.id) == ADMIN_CHAT_ID

# Handler Commands
async def start(update, ctx):
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_text("Selamat datang!\nGunakan tombol di bawah untuk melihat stok tersedia.", reply_markup=InlineKeyboardMarkup(btn))

async def new_product(update, ctx):
    if not is_admin(update): return
    try:
        i, n, h, d = [x.strip() for x in " ".join(ctx.args).split("|", 3)]
        add_product(i, n, int(h), d)
        await update.message.reply_text(f"✅ Produk `{n}` berhasil ditambahkan.")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")

async def add_stock(update, ctx):
    if not is_admin(update): return
    try:
        pid = ctx.args[0]
        akun = " ".join(ctx.args[1:])
        data = {"akun": akun}
        add_stock_akun(pid, data)
        await update.message.reply_text(f"✅ Stok akun ditambahkan ke produk `{pid}`.")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Format: /add <produk_id> <akun_detail>")

async def info_stock(update, ctx):
    if not is_admin(update): return
    teks = "📦 Stok Produk:\n"
    for p in get_products():
        stok = get_stock(p["id"])
        teks += f"- {p['nama']} (`{p['id']}`): {len(stok)} akun\n"
    await update.message.reply_text(teks)

# Handler Buttons
async def btn_handler(update, ctx):
    q = update.callback_query; await q.answer()
    if q.data == "cek":
        rows = [p for p in get_products() if get_stock(p["id"])]
        btns = [[InlineKeyboardButton(f"{p['nama']} — Rp{p['harga']}", callback_data=f"buy__{p['id']}")] for p in rows]
        btns.append([InlineKeyboardButton("↩️ Kembali", callback_data="back")])
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(btns))
    elif q.data.startswith("buy__"):
        pid = q.data.split("__", 1)[1]
        prod = next((p for p in get_products() if p["id"] == pid), None)
        if not prod:
            return await q.edit_message_text("❌ Produk tidak ditemukan.")
        ext = f"invoice__{pid}__{q.from_user.id}__{int(time.time())}"
        invoice = xendit.Invoice.create(
            external_id=ext,
            amount=prod["harga"],
            description=prod["nama"],
            customer={"given_names": q.from_user.full_name}
        )
        insert_order(ext, q.from_user.id, pid, prod["harga"])
        await q.edit_message_text(f"✅ Berikut link pembayaran:\n{invoice.invoice_url}")
    elif q.data == "back":
        await start(update, ctx)

async def text_handler(update, ctx):
    await update.message.reply_text("Gunakan /start untuk mulai.")

# Routes
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot_app.bot)
    bot_app.update_queue.put_nowait(update)
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return "forbidden", 403
    d = request.get_json()
    if d.get("status") == "PAID":
        ext = d["external_id"]
        orders = get_order_user(ext)
        if not orders:
            return jsonify({"error": "Order not found"}), 400
        pid = ext.split("__")[1]
        akun = pop_one_akun(pid)
        if not akun:
            return jsonify({"error": "No stock"}), 400
        update_order_status(ext, akun_id=akun["id"])
        user_id = orders[0]["user_id"]
        akun_info = akun["data"].get("akun") or "akun tidak tersedia"
        bot_app.bot.send_message(user_id, f"✅ Pembayaran berhasil!\nAkun: `{akun_info}`", parse_mode="Markdown")
    return jsonify(ok=True)

async def setup_bot():
    await bot_app.bot.set_webhook(WEBHOOK_URL + "/telegram")
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("newproduct", new_product))
    bot_app.add_handler(CommandHandler("add", add_stock))
    bot_app.add_handler(CommandHandler("infostock", info_stock))
    bot_app.add_handler(CallbackQueryHandler(btn_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

def main():
    import threading
    threading.Thread(target=bot_app.run_polling, daemon=True).start()
    asyncio.run(setup_bot())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    main()
