# main.py

import os
import logging
import json
import asyncio
import time
from flask import Flask, request, jsonify
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
import xendit

# --- KONFIGURASI ---
# Kunci-kunci ini diambil dari informasi yang Anda berikan.
# !!! PERINGATAN PENTING: Kunci-kunci ini sudah terekspos ke publik.
# WAJIB ganti dengan yang baru setelah bot Anda berhasil di-hosting.
# Nanti kita akan pindahkan ini ke Environment Variables di Railway agar aman.

TELEGRAM_TOKEN = "7810672201:AAGmx5O0Tn-rZ2J3s7AU8QToNfrl3DMAo-U"
ADMIN_CHAT_ID = "7801979990"
XENDIT_API_KEY = "xnd_development_PMz8LY3LE4GKhCi90pEyblvqqgQFo5TwPcINoX0EdCxQTWxVjF8Gj5mzzRpu85"
# Buat token rahasia ini sendiri. Ganti dengan teks acak yang panjang dan sulit ditebak.
XENDIT_WEBHOOK_VERIFICATION_TOKEN = "0000222224444"


# Inisialisasi Logging untuk memantau aktivitas dan error bot.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inisialisasi Xendit dengan API Key Anda.
xendit.api_key = XENDIT_API_KEY

# Inisialisasi Web Server Flask.
app = Flask(__name__)

# --- FUNGSI-FUNGSI BANTUAN (DATABASE JSON & STOK) ---
def muat_data(file_path):
    """Fungsi untuk memuat data dari file JSON."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Jika file tidak ada atau kosong, kembalikan list/dict kosong.
        return [] if file_path.endswith('s.json') else {}

def simpan_data(data, file_path):
    """Fungsi untuk menyimpan data ke file JSON."""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

def ambil_akun_dari_stok(produk_id):
    """Mengambil satu akun dari stok dan menyimpannya kembali."""
    products = muat_data('products.json')
    for p in products:
        if p['id'] == produk_id and p.get('stok_akun'):
            akun = p['stok_akun'].pop(0)  # Ambil dan hapus akun pertama.
            simpan_data(products, 'products.json')
            return akun
    return None

# --- BAGIAN TELEGRAM BOT (Perintah dan Tombol) ---
async def start_command(update: Update, context: application.context_types.DEFAULT_TYPE):
    """Handler untuk perintah /start."""
    keyboard = [[InlineKeyboardButton("🛒 Beli Akun Premium", callback_data='beli_produk')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Selamat datang di Skynexio Store! Silakan pilih menu:", reply_markup=reply_markup)

async def button_handler(update: Update, context: application.context_types.DEFAULT_TYPE):
    """Handler untuk semua interaksi tombol inline."""
    query = update.callback_query
    await query.answer()
    
    # Menampilkan daftar produk
    if query.data == 'beli_produk':
        products = muat_data('products.json')
        keyboard = []
        for p in products:
            if p.get('stok_akun'): # Hanya tampilkan produk yang stoknya ada.
                label = f"{p['nama']} - Rp{p['harga']:,}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"order_{p['id']}")])
        
        if not keyboard:
            await query.edit_message_text("Mohon maaf, semua produk sedang habis.")
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Silakan pilih produk yang Anda inginkan:", reply_markup=reply_markup)

    # Membuat invoice saat produk dipilih
    elif query.data.startswith('order_'):
        produk_id = query.data.split('_')[1]
        products = muat_data('products.json')
        produk = next((p for p in products if p['id'] == produk_id), None)
        
        if not produk:
            await query.edit_message_text("Produk tidak ditemukan.")
            return

        await query.edit_message_text(f"⏳ Sedang membuat invoice untuk {produk['nama']}...")

        # Membuat Invoice di Xendit
        try:
            external_id = f"skynexio-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=f"Pembelian {produk['nama']} oleh {update.effective_user.full_name}",
                customer={'given_names': update.effective_user.full_name}
            )
            
            # Simpan data pesanan yang sedang berlangsung.
            orders = muat_data('orders.json')
            orders.append({
                'external_id': external_id,
                'user_id': update.effective_user.id,
                'produk_id': produk_id,
                'status': 'PENDING'
            })
            simpan_data(orders, 'orders.json')

            pesan = f"✅ Invoice berhasil dibuat!\n\nSilakan selesaikan pembayaran Anda melalui link berikut:\n{invoice.invoice_url}"
            await query.edit_message_text(pesan)

        except Exception as e:
            logger.error(f"Gagal membuat invoice Xendit: {e}")
            await query.edit_message_text("❌ Maaf, terjadi kesalahan saat membuat invoice. Silakan coba lagi.")

# --- BAGIAN FLASK WEB SERVER (Menerima Webhook dari Xendit) ---
@app.route('/')
def index():
    """Halaman depan untuk cek status server."""
    return "Skynexio Store Bot server is alive!"

@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    """Endpoint untuk menerima notifikasi pembayaran dari Xendit."""
    try:
        # Verifikasi webhook untuk keamanan.
        received_token = request.headers.get('x-callback-token')
        if received_token != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
            logger.warning("Webhook verification failed: token salah.")
            return jsonify({'status': 'error', 'message': 'Invalid verification token'}), 403

        data = request.json
        logger.info(f"Webhook diterima dari Xendit: {data}")

        # Cek jika event adalah pembayaran invoice yang sudah lunas ('PAID').
        if data.get('status') == 'PAID':
            external_id = data.get('external_id')
            
            orders = muat_data('orders.json')
            order_index, order_data = next(
                ((i, o) for i, o in enumerate(orders) if o.get('external_id') == external_id), 
                (None, None)
            )

            # Pastikan order ada dan statusnya masih PENDING untuk mencegah proses ganda.
            if order_data and order_data.get('status') == 'PENDING':
                # Update status order menjadi PAID.
                orders[order_index]['status'] = 'PAID'
                simpan_data(orders, 'orders.json')

                # Ambil satu akun dari stok.
                akun = ambil_akun_dari_stok(order_data['produk_id'])

                if akun:
                    # Kirim akun ke pengguna.
                    pesan_sukses = f"🎉 Pembayaran Lunas!\n\nTerima kasih. Berikut detail akun Anda:\n\n`{akun}`\n\nHarap segera amankan akun Anda."
                    await bot.send_message(
                        chat_id=order_data['user_id'],
                        text=pesan_sukses,
                        parse_mode='Markdown'
                    )
                    # Kirim notifikasi ke admin.
                    await bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan sukses!\nID Pesanan: {external_id}\nAkun: {akun}\nTelah dikirim ke user ID: {order_data['user_id']}")
                else:
                    # Kasus darurat jika stok habis setelah user bayar.
                    await bot.send_message(order_data['user_id'], "Pembayaran Anda berhasil, namun mohon maaf stok kami mendadak habis. Admin akan segera menghubungi Anda untuk refund atau solusi lainnya.")
                    await bot.send_message(ADMIN_CHAT_ID, f"‼️ STOK HABIS ‼️\nID Pesanan: {external_id}\nPembayaran sudah masuk tapi stok kosong! Harap segera hubungi user ID: {order_data['user_id']}")
        
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"Error pada webhook Xendit: {e}")
        return jsonify({'status': 'error', 'message': 'Internal Server Error'}), 500

# --- Inisialisasi dan Menjalankan Aplikasi ---
# Buat instance aplikasi bot
bot = Bot(token=TELEGRAM_TOKEN)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
# Daftarkan handler
bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CallbackQueryHandler(button_handler))

async def run_telegram_bot():
    """Menjalankan bot Telegram."""
    logger.info("Starting Telegram bot...")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    logger.info("Telegram bot started.")

# Jalankan bot di awal saat server startup
asyncio.create_task(run_telegram_bot())