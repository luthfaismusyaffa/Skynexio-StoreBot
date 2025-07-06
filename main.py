# main.py - VERSI FINAL DENGAN PERBAIKAN WEBHOOK

import os, logging, asyncio, time
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import xendit
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

# Init
logging.basicConfig(level=logging.INFO)
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
logging.getLogger("httpx").setLevel(logging.WARNING)

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_text("Selamat datang! Silakan klik tombol di bawah:", reply_markup=InlineKeyboardMarkup(btn))

async def btn_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cek":
        rows = [p for p in get_products() if get_stock(p["id"])]
        if not rows:
            return await q.edit_message_text("Stok produk kosong 😢")
        buttons = [[InlineKeyboardButton(f"{p['nama']} — Rp{p['harga']:,}", callback_data=f"buy__{p['id']}")] for p in rows]
        # Membuat tombol kembali yang akan memanggil fungsi start lagi
        buttons.append([InlineKeyboardButton("↩️ Kembali", callback_data="start_menu")])
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(buttons))
    elif q.data.startswith("buy__"):
        pid = q.data.split("__", 1)[1]
        prod = next((p for p in get_products() if p["id"] == pid), None)
        if not prod:
            return await q.edit_message_text("Produk tidak ditemukan.")
        ext = f"invoice__{pid}__{q.from_user.id}__{int(time.time())}"
        inv = xendit.Invoice.create(
            external_id=ext,
            amount=prod["harga"],
            description=prod["nama"],
            customer={"given_names": q.from_user.full_name},
        )
        insert_order(ext, q.from_user.id, pid, prod["harga"])
        await q.edit_message_text(f"✅ Silakan bayar melalui link berikut:\n{inv.invoice_url}")
    elif q.data == "start_menu":
        # Menghapus pesan produk dan mengirim pesan start baru
        await q.message.delete()
        await start(q, ctx)


async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gunakan /start untuk memulai.")

@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return jsonify(ok=True)

# --- PERBAIKAN UTAMA ADA DI FUNGSI INI ---
@app.route("/webhook/xendit", methods=["POST"])
async def xendit_hook(): # <-- Diubah menjadi async def
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return jsonify({"error": "Forbidden"}), 403
    
    d = request.get_json()
    logging.info(f"Xendit webhook diterima: {d}")

    # Cek jika ini adalah tes dari dashboard Xendit
    if d.get("external_id") == "invoice_123124123":
        logging.info("Webhook tes dari Xendit diterima, merespons sukses.")
        return jsonify(ok=True) # <-- Langsung kembalikan sukses

    if d.get("status") == "PAID":
        ext = d.get("external_id", "")
        if not ext.startswith("invoice__"):
            logging.error(f"Invalid external_id format: {ext}")
            return jsonify({"error": "Invalid external_id"}), 400
        
        orders = get_order_user(ext)
        if not orders:
            logging.error(f"Order not found for external_id: {ext}")
            return {"error": "Order not found"}, 404
        
        # Periksa apakah order sudah diproses
        if orders[0].get('status') == 'PAID':
            logging.warning(f"Order {ext} sudah pernah diproses.")
            return jsonify(ok=True) # Kembalikan sukses agar Xendit tidak coba lagi
        
        pid = ext.split("__")[1]
        akun = pop_one_akun(pid)
        
        if not akun:
            logging.error(f"Stok habis untuk produk: {pid} pada order: {ext}")
            return {"error": "No stock"}, 400
        
        update_order_status(ext, akun_id=akun["id"])
        user_id = orders[0]["user_id"]

        # Menggunakan await karena ini adalah fungsi async
        await bot_app.bot.send_message(
            user_id,
            f"✅ Pembayaran diterima!\nAkun: `{akun['detail']}`",
            parse_mode="Markdown"
        )
    return jsonify(ok=True)

async def setup():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(btn_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await bot_app.initialize()
    await bot_app.bot.set_webhook(WEBHOOK_URL + "/telegram")
    await bot_app.bot.set_my_commands([BotCommand("start", "Mulai bot")])
    logging.info("Bot webhook & commands berhasil diatur.")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    main()
