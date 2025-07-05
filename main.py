# main.py - VERSI FINAL

import os
import logging
import json
import asyncio
import time
from flask import Flask, request, jsonify
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler
import xendit # <-- PERBAIKAN: Menambahkan import xendit di sini

# --- KONFIGURASI ---
# Ambil konfigurasi dari Environment Variables agar aman saat hosting.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")

# Inisialisasi Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inisialisasi Xendit & Flask
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)

# --- FUNGSI DATABASE & STOK ---
def muat_data(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if 's.json' in file_path else {}

def simpan_data(data, file_path):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

def ambil_akun_dari_stok(produk_id):
    products = muat_data('products.json')
    for p in products:
        if p['id'] == produk_id and p.get('stok_akun'):
            akun = p['stok_akun'].pop(0)
            simpan_data(products, 'products.json')
            return akun
    return None

# --- HANDLER TELEGRAM ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🛒 Beli Akun Premium", callback_data='beli_produk')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Selamat datang di Skynexio Store! Silakan pilih menu:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'beli_produk':
        products = muat_data('products.json')
        keyboard = []
        for p in products:
            if p.get('stok_akun'):
                keyboard.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        if not keyboard:
            await query.edit_message_text("Mohon maaf, semua produk sedang habis.")
            return
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Silakan pilih produk yang Anda inginkan:", reply_markup=reply_markup)

    elif query.data.startswith('order_'):
        produk_id = query.data.split('_')[1]
        produk = next((p for p in muat_data('products.json') if p['id'] == produk_id), None)
        if not produk:
            await query.edit_message_text("Produk tidak ditemukan.")
            return

        await query.edit_message_text(f"⏳ Membuat invoice untuk {produk['nama']}...")
        try:
            external_id = f"skynexio-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=f"Pembelian {produk['nama']}",
                customer={'given_names': update.effective_user.full_name}
            )
            orders = muat_data('orders.json')
            orders.append({'external_id': external_id, 'user_id': update.effective_user.id, 'produk_id': produk_id, 'status': 'PENDING'})
            simpan_data(orders, 'orders.json')
            await query.edit_message_text(f"✅ Invoice berhasil dibuat!\n\nSilakan bayar melalui link:\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(f"Gagal membuat invoice Xendit: {e}")
            await query.edit_message_text("❌ Gagal membuat invoice. Coba lagi nanti.")

# --- WEB SERVER & WEBHOOK ---
@app.route('/')
def index():
    return "Skynexio Store Bot server is alive!"

@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    try:
        if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
            logger.warning("Webhook verification failed.")
            return jsonify({'status': 'error', 'message': 'Invalid verification token'}), 403
        
        data = request.json
        logger.info(f"Webhook diterima: {data}")

        if data.get('status') == 'PAID':
            external_id = data.get('external_id')
            orders = muat_data('orders.json')
            order_data = next((o for o in orders if o.get('external_id') == external_id and o.get('status') == 'PENDING'), None)

            if order_data:
                order_data['status'] = 'PAID'
                simpan_data(orders, 'orders.json')
                akun = ambil_akun_dari_stok(order_data['produk_id'])
                
                if akun:
                    pesan_sukses = f"🎉 Pembayaran Lunas!\n\nTerima kasih. Berikut detail akun Anda:\n\n`{akun}`\n\nHarap segera amankan akun Anda."
                    await bot_app.bot.send_message(order_data['user_id'], pesan_sukses, parse_mode='Markdown')
                    await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan sukses!\nID: {external_id}\nAkun: {akun}\nUser: {order_data['user_id']}")
                else:
                    await bot_app.bot.send_message(order_data['user_id'], "Pembayaran Anda berhasil, namun stok habis. Admin akan segera menghubungi Anda.")
                    await bot_app.bot.send_message(ADMIN_CHAT_ID, f"‼️ STOK HABIS ‼️\nID: {external_id} lunas tapi stok kosong! Hubungi user: {order_data['user_id']}")
        
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Error pada webhook: {e}")
        return jsonify({'status': 'error'}), 500

# --- INISIALISASI APLIKASI TELEGRAM ---
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CallbackQueryHandler(button_handler))
