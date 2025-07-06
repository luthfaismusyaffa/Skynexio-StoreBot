import os, logging, time, asyncio
from flask import Flask, request, jsonify
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import xendit
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user

# ENV
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID=os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL=os.getenv("WEBHOOK_URL")
XENDIT_API_KEY=os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN=os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

# Init
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
logging.basicConfig(level=logging.INFO)

def is_admin(update): return str(update.effective_user.id) == ADMIN_CHAT_ID

async def start(update, ctx):
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_text("Selamat datang!\nGunakan tombol di bawah untuk cek stok.", reply_markup=InlineKeyboardMarkup(btn))

async def new_product(update, ctx):
    if not is_admin(update): return
    try:
        i,n,h,d = [x.strip() for x in " ".join(ctx.args).split("|",3)]
        headers = {"apikey": os.getenv("SUPABASE_KEY"), "Authorization": f"Bearer {os.getenv('SUPABASE_KEY')}", "Content-Type": "application/json"}
        data = {"id": i, "nama": n, "harga": int(h), "deskripsi": d}
        requests.post(f"{os.getenv('SUPABASE_URL')}/rest/v1/products", headers=headers, json=data)
        await update.message.reply_text(f"✅ Produk '{n}' berhasil ditambahkan.")
    except Exception as e:
        logging.error(f"new_product: {e}")
        await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")

async def add_stock(update, ctx):
    if not is_admin(update): return
    try:
        pid = ctx.args[0]
        detail = " ".join(ctx.args[1:])
        headers = {"apikey": os.getenv("SUPABASE_KEY"), "Authorization": f"Bearer {os.getenv('SUPABASE_KEY')}", "Content-Type": "application/json"}
        requests.post(f"{os.getenv('SUPABASE_URL')}/rest/v1/stok_akun", headers=headers, json={"produk_id": pid, "data": {"detail": detail}})
        await update.message.reply_text("✅ Stok berhasil ditambahkan.")
    except Exception as e:
        logging.error(f"add_stock: {e}")
        await update.message.reply_text("Format: /add <produk_id> <detail>")

async def info_stock(update, ctx):
    if not is_admin(update): return
    teks = "📦 Stok Produk:\n"
    for p in get_products():
        teks += f"- {p['nama']} (`{p['id']}`): {len(get_stock(p['id']))} akun\n"
    await update.message.reply_text(teks)

async def btn_handler(update, ctx):
    q = update.callback_query; await q.answer()
    if q.data == "cek":
        rows = [p for p in get_products() if get_stock(p["id"])]
        btns = [[InlineKeyboardButton(f"{p['nama']} — Rp{p['harga']}", callback_data=f"buy__{p['id']}")] for p in rows]
        btns.append([InlineKeyboardButton("↩️ Kembali", callback_data="back")])
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(btns))
    elif q.data.startswith("buy__"):
        pid = q.data.split("__")[1]
        prod = next((p for p in get_products() if p["id"] == pid), None)
        if not prod: return await q.edit_message_text("❌ Produk tidak ditemukan atau stok habis.")
        ext = f"invoice__{pid}__{q.from_user.id}__{int(time.time())}"
        inv = xendit.Invoice.create(external_id=ext, amount=prod["harga"], description=prod["nama"], customer={"given_names": q.from_user.full_name})
        insert_order(ext, q.from_user.id, pid, prod["harga"])
        await q.edit_message_text(f"✅ Berikut link pembayaran:\n{inv.invoice_url}")
    elif q.data == "back":
        await start(update, ctx)

async def text_handler(update, ctx):
    await update.message.reply_text("Ketik /start untuk mulai.")

@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return "forbidden", 403
    data = request.get_json()
    ext = data.get("external_id")
    if not ext or data.get("status") != "PAID":
        return jsonify({"error": "Invalid or unpaid invoice"}), 400

    order = get_order_user(ext)
    if not order:
        return jsonify({"error": "Order not found"}), 400
    pid = ext.split("__")[1]
    akun = pop_one_akun(pid)
    if not akun:
        return jsonify({"error": "No stock available"}), 400

    update_order_status(ext, akun["id"])
    detail = akun.get("data", {}).get("detail", "❌ Tidak ditemukan.")
    bot_app.bot.send_message(chat_id=order[0]["user_id"], text=f"✅ Pembayaran diterima!\nAkun: `{detail}`", parse_mode="Markdown")
    return jsonify(ok=True)

async def setup():
    await bot_app.bot.set_webhook(WEBHOOK_URL + "/telegram")
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("newproduct", new_product))
    bot_app.add_handler(CommandHandler("add", add_stock))
    bot_app.add_handler(CommandHandler("infostock", info_stock))
    bot_app.add_handler(CallbackQueryHandler(btn_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
