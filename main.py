# main.py - VERSI FINAL DENGAN SEMUA PERBAIKAN

import os
import logging
import json
import asyncio
import time
import random
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler
import xendit # <-- KESALAHAN ADA DI SINI, BARIS INI HILANG SEBELUMNYA

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Inisialisasi Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inisialisasi Xendit & Flask
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)

# --- INISIALISASI BOT TELEGRAM ---
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- FUNGSI DATABASE, STOK & COUNTER ---
def muat_data(file_path):
    try:
        with open(file_path, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return [] if 's.json' in file_path else {}

def simpan_data(data, file_path):
    with open(file_path, 'w') as f: json.dump(data, f, indent=2, ensure_ascii=False)

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
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 5530)
    counters.setdefault('total_turnover', 54000000)
    counters['total_orders'] += random.randint(1, 3)
    counters['total_turnover'] += random.randint(10000, 50000)
    simpan_data(counters, 'counter.json')

    keyboard = [[InlineKeyboardButton("🛒 Lihat Produk Premium", callback_data='beli_produk')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    total_orders_formatted = f"{counters['total_orders']:,}"
    total_turnover_formatted = f"Rp{counters['total_turnover']:,}"
    
    pesan_selamat_datang = (
        "**Selamat Datang di Skynexio Store!** ✨\n\n"
        "Pusatnya akun premium untuk segala kebutuhan digitalmu, mulai dari streaming film, musik, sampai tools produktivitas canggih!\n\n"
        "---\n"
        f"📈 Total Pesanan: **{total_orders_formatted}**\n"
        f"💰 Total Transaksi: **{total_turnover_formatted}**\n"
        "---\n\n"
        "Kami siap melayani Anda 24/7 dengan proses instan. Yuk, pilih produk jagoanmu di bawah!"
    )
    await update.message.reply_photo(
        photo=LOGO_URL,
        caption=pesan_selamat_datang,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'beli_produk':
        products = muat_data('products.json')
        keyboard = []
        pesan_produk = "Ini dia daftar 'amunisi' premium kita yang ready. Pilih jagoanmu! 👇"
        for p in products:
            if p.get('stok_akun'):
                keyboard.append([InlineKeyboardButton(f"✅ {p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        if not keyboard:
            await query.edit_message_text("Yah, amunisi lagi kosong nih. Cek lagi nanti ya! 🙏")
            return
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data='kembali_ke_awal')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(pesan_produk, reply_markup=reply_markup)

    elif query.data == 'kembali_ke_awal':
        await query.message.delete()
        await start_command(query.message, context)

    elif query.data.startswith('order_'):
        produk_id = query.data.split('_')[1]
        produk = next((p for p in muat_data('products.json') if p['id'] == produk_id), None)
        if not produk:
            await query.edit_message_text("Waduh, produknya udah gaib. Coba pilih yang lain."); return

        await query.edit_message_text("Oke, siap! Pesananmu lagi dibuatin tiketnya nih... ⏳")
        try:
            external_id = f"skynexio-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=f"Pembelian {produk['nama']}",
                customer={'given_names': update.effective_user.full_name}
            )
            orders = muat_data('orders.json')
            # Simpan juga harga produk untuk update counter
            orders.append({'external_id': external_id, 'user_id': update.effective_user.id, 'produk_id': produk_id, 'harga': produk['harga'], 'status': 'PENDING'})
            simpan_data(orders, 'orders.json')
            pesan_invoice = f"Tiket nontonmu sudah siap! ✅\n\nLakukan pembayaran di kasir sebelah ya (klik link di bawah), jangan sampai telat!\n\n{invoice.invoice_url}"
            await query.edit_message_text(pesan_invoice)
        except Exception as e:
            logger.error(f"Gagal membuat invoice Xendit: {e}")
            await query.edit_message_text("❌ Oops, mesin tiketnya lagi ngambek. Coba lagi beberapa saat ya.")

# Daftarkan handler ke bot_app
bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CallbackQueryHandler(button_handler))

# --- WEB SERVER & WEBHOOK ---
@app.route('/')
def index(): return "Skynexio Store Bot server is alive and well!"

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    try:
        await bot_app.initialize()
        await bot_app.process_update(Update.de_json(request.get_json(force=True), bot_app.bot))
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error di webhook Telegram: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({'status': 'error', 'message': 'Invalid verification token'}), 403
    
    data = request.json
    logger.info(f"Xendit webhook diterima: {data}")

    if data.get('status') == 'PAID':
        external_id = data.get('external_id')
        orders = muat_data('orders.json')
        order_data = next((o for o in orders if o.get('external_id') == external_id and o.get('status') == 'PENDING'), None)

        if order_data:
            await bot_app.initialize()
            order_data['status'] = 'PAID'
            simpan_data(orders, 'orders.json')
            
            # Update counter dengan data transaksi asli
            counters = muat_data('counter.json')
            counters['total_orders'] += 1
            counters['total_turnover'] += order_data.get('harga', 0)
            simpan_data(counters, 'counter.json')
            
            akun = ambil_akun_dari_stok(order_data['produk_id'])
            
            if akun:
                pesan_sukses = f"Yess, pembayaran lunas! 🎉\n\nIni dia akses VIP kamu. Selamat menikmati dan jangan lupa jajan lagi ya! 😉\n\nAkun Anda:\n`{akun}`"
                await bot_app.bot.send_message(order_data['user_id'], pesan_sukses, parse_mode='Markdown')
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan sukses!\nID: {external_id}\nAkun: {akun}\nUser: {order_data['user_id']}")
            else:
                await bot_app.bot.send_message(order_data['user_id'], "Pembayaran Anda berhasil, namun stok habis. Admin akan segera menghubungi Anda.")
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"‼️ STOK HABIS ‼️\nID: {external_id} lunas tapi stok kosong! Hubungi user: {order_data['user_id']}")
    
    return jsonify({'status': 'success'}), 200

# --- FUNGSI UNTUK MENJALANKAN KESELURUHAN APLIKASI ---
async def setup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    logger.info(f"Telegram webhook berhasil diatur ke {WEBHOOK_URL}/telegram")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == '__main__':
    main()
