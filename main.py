# main.py - VERSI FINAL SEDERHANA & STABIL

import os
import logging
import time
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from xendit import Xendit # Menggunakan library Xendit versi baru
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

# --- INISIALISASI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Cara baru inisialisasi Xendit
xendit_client = Xendit(api_key=XENDIT_API_KEY)
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- HANDLER ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    btn = [[InlineKeyboardButton("✅ Cek Stok Produk", callback_data="cek_stok")]]
    await update.message.reply_text("Selamat datang di toko kami! Silakan cek produk yang tersedia:", reply_markup=InlineKeyboardMarkup(btn))

async def btn_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if q.data == "cek_stok":
        try:
            products = get_products()
            rows = [p for p in products if get_stock(p["id"])]
            if not rows:
                return await q.edit_message_text("Maaf, semua produk sedang habis 😢")
            
            buttons = [[InlineKeyboardButton(f"{p['nama']} — Rp{p['harga']:,}", callback_data=f"order__{p['id']}")] for p in rows]
            buttons.append([InlineKeyboardButton("↩️ Kembali", callback_data="start_menu")])
            await q.edit_message_text("Pilih produk yang Anda inginkan:", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception as e:
            logging.error(f"Error saat mengambil produk: {e}")
            await q.edit_message_text("Gagal mengambil data produk. Coba lagi nanti.")

    elif q.data.startswith("order__"):
        pid = q.data.split("__", 1)[1]
        prod = next((p for p in get_products() if p["id"] == pid), None)
        if not prod or not get_stock(pid):
            return await q.edit_message_text("Maaf, produk ini baru saja habis.")
            
        await q.edit_message_text(f"⏳ Membuat invoice untuk {prod['nama']}...")
        try:
            ext_id = f"invoice__{pid}__{q.from_user.id}__{int(time.time())}"
            # PERBAIKAN UTAMA: Cara baru membuat invoice
            inv = xendit_client.invoice.create(
                external_id=ext_id,
                amount=prod["harga"],
                description=f"Pembelian {prod['nama']}",
                customer={
                    "given_names": q.from_user.full_name,
                    "email": f"{q.from_user.id}@telegram.user" # Email wajib diisi
                },
                success_redirect_url=f"https://t.me/{ctx.bot.username}",
                failure_redirect_url=f"https://t.me/{ctx.bot.username}"
            )
            insert_order(ext_id, q.from_user.id, pid, prod["harga"])
            await q.edit_message_text(f"✅ Invoice berhasil dibuat!\nSilakan selesaikan pembayaran melalui link berikut:\n\n{inv.invoice_url}")
        except Exception as e:
            logging.error(f"Gagal membuat invoice Xendit: {e}")
            await q.edit_message_text("❌ Terjadi kesalahan saat membuat invoice. Silakan coba lagi.")

    elif q.data == "start_menu":
        btn = [[InlineKeyboardButton("✅ Cek Stok Produk", callback_data="cek_stok")]]
        await q.edit_message_text("Selamat datang! Silakan klik tombol di bawah:", reply_markup=InlineKeyboardMarkup(btn))

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Perintah tidak dikenal. Silakan gunakan /start untuk memulai.")

# --- WEBHOOKS ---
@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    await bot_app.initialize()
    await bot_app.process_update(Update.de_json(request.get_json(force=True), bot_app.bot))
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
async def xendit_hook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return jsonify({"error": "Forbidden"}), 403
    
    d = request.get_json()
    logging.info(f"Xendit webhook diterima: {d}")

    # Logika baru untuk menangani format webhook yang berbeda
    data = d.get("data", d)
    if data.get("status") == "PAID":
        ext_id = data.get("external_id", "")

        if ext_id == "invoice_123124123":
            return jsonify(ok=True)

        if not ext_id.startswith("invoice__"):
            return jsonify({"error": "Invalid external_id"}), 400
        
        orders = get_order_user(ext_id)
        if not orders or orders[0].get('status') == 'PAID':
            return jsonify(ok=True)
        
        pid = ext_id.split("__")[1]
        akun = pop_one_akun(pid)
        
        if not akun:
            return {"error": "No stock"}, 400
        
        update_order_status(ext_id, akun_id=akun["id"])
        user_id = orders[0]["user_id"]
        
        akun_detail = akun['data']
        pesan_sukses = f"✅ Pembayaran diterima!\nAkun: `{akun_detail.get('detail', 'N/A')}`"

        await bot_app.bot.send_message(user_id, pesan_sukses, parse_mode="Markdown")
        await bot_app.bot.send_message(ADMIN_CHAT_ID, f"Penjualan sukses: {pid}")
        
    return jsonify(ok=True)

# --- SETUP & RUN ---
async def setup():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(btn_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    await bot_app.initialize()
    await bot_app.bot.set_webhook(WEBHOOK_URL + "/telegram")
    await bot_app.bot.set_my_commands([BotCommand("start", "Mulai bot")])
    logging.info("Bot webhook & commands berhasil diatur.")

# Menjalankan setup async sebelum server Flask dimulai
asyncio.run(setup())
