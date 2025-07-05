# main.py - VERSI FINAL DENGAN CEK STOK & PERBAIKAN

import os
import logging
import json
import asyncio
import time
import random
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "username_admin_anda")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Inisialisasi
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- FUNGSI DATABASE & STOK ---
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

# --- PERINTAH ADMIN --- (Tidak ada perubahan di sini)
def is_admin(update: Update): return str(update.effective_user.id) == ADMIN_CHAT_ID
async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, akun_baru = context.args[0], " ".join(context.args[1:])
        if not akun_baru: await update.message.reply_text("Format salah."); return
        products = muat_data('products.json')
        produk_ditemukan = False
        for p in products:
            if p['id'] == produk_id: p.setdefault('stok_akun', []).append(akun_baru); produk_ditemukan = True; break
        if produk_ditemukan: simpan_data(products, 'products.json'); await update.message.reply_text(f"✅ Stok ditambahkan ke: {produk_id}")
        else: await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except (ValueError, IndexError): await update.message.reply_text("Format: /add <id_produk> <detail_akun>")
async def new_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        id_produk, nama_produk, harga, deskripsi = [x.strip() for x in " ".join(context.args).split('|')]
        products = muat_data('products.json')
        if any(p['id'] == id_produk for p in products): await update.message.reply_text(f"❌ ID '{id_produk}' sudah ada."); return
        products.append({"id": id_produk, "nama": nama_produk, "harga": int(harga), "deskripsi": deskripsi, "stok_akun": []})
        simpan_data(products, 'products.json'); await update.message.reply_text(f"✅ Produk '{nama_produk}' dibuat.")
    except Exception as e: logger.error(f"Error newproduct: {e}"); await update.message.reply_text("Format: /newproduct <id> | <nama> | <harga> | <deskripsi>")
async def del_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id_to_del = context.args[0]
        products = muat_data('products.json')
        original_len = len(products)
        products = [p for p in products if p['id'] != produk_id_to_del]
        if len(products) < original_len: simpan_data(products, 'products.json'); await update.message.reply_text(f"✅ Produk '{produk_id_to_del}' dihapus.")
        else: await update.message.reply_text(f"❌ Produk ID '{produk_id_to_del}' tidak ditemukan.")
    except IndexError: await update.message.reply_text("Format: /delproduct <id_produk>")
async def edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, field, new_value = context.args[0], context.args[1].lower(), " ".join(context.args[2:])
        if field not in ['nama', 'harga', 'deskripsi']: await update.message.reply_text("Field: 'nama', 'harga', 'deskripsi'."); return
        products = muat_data('products.json')
        produk_ditemukan = False
        for p in products:
            if p['id'] == produk_id: p[field] = int(new_value) if field == 'harga' else new_value; produk_ditemukan = True; break
        if produk_ditemukan: simpan_data(products, 'products.json'); await update.message.reply_text(f"✅ Produk '{produk_id}' diupdate.")
        else: await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except Exception as e: logger.error(f"Error editproduct: {e}"); await update.message.reply_text("Format: /edit <id_produk> <field> <nilai_baru>")
async def info_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = muat_data('products.json')
    if not products: await update.message.reply_text("Belum ada produk."); return
    pesan_stok = "📦 **Laporan Stok Saat Ini** 📦\n\n"
    for p in products: pesan_stok += f"- `{p['id']}`\n  Nama: {p['nama']}\n  Stok: **{len(p.get('stok_akun', []))}** akun\n\n"
    await update.message.reply_text(pesan_stok, parse_mode='Markdown')

# --- HANDLER PENGGUNA ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 5530); counters.setdefault('total_turnover', 54000000)
    counters['total_orders'] += random.randint(1, 3)
    simpan_data(counters, 'counter.json')
    # --- PERUBAHAN: Tombol Menu Baru ---
    keyboard = [[InlineKeyboardButton("✅ Cek Stok Ready", callback_data='cek_stok')]]
    total_orders_formatted = f"{counters['total_orders']:,}"
    total_turnover_formatted = f"Rp{counters['total_turnover']:,}"
    pesan_selamat_datang = (f"**Selamat Datang di Skynexio Store!** ✨\n\nPusatnya akun premium untuk segala kebutuhan digitalmu!\n\n---\n"
                          f"📈 Total Pesanan Dilayani: **{total_orders_formatted}**\n"
                          f"💰 Total Transaksi: **{total_turnover_formatted}**\n---\n\n"
                          "Kami siap melayani Anda 24/7 dengan proses instan. Yuk, pilih produk jagoanmu di bawah!")
    await update.message.reply_photo(photo=LOGO_URL, caption=pesan_selamat_datang, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    chat_id = query.message.chat_id

    # --- PERUBAHAN: Logika Tombol Baru untuk Cek Stok ---
    if query.data == 'cek_stok':
        await query.message.delete()
        products = muat_data('products.json')
        keyboard = []
        for p in products:
            if p.get('stok_akun'): keyboard.append([InlineKeyboardButton(f"✅ {p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        if not keyboard:
            await context.bot.send_message(chat_id=chat_id, text="Yah, amunisi lagi kosong nih. Cek lagi nanti ya! 🙏"); return
        keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Awal", callback_data='kembali_ke_awal')])
        await context.bot.send_message(chat_id=chat_id, text="Ini dia daftar 'amunisi' premium kita yang ready. Pilih jagoanmu! 👇", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'kembali_ke_awal':
        await query.message.delete()
        # Memanggil fungsi start_command memerlukan objek 'update' yang memiliki 'message'
        # Kita buat objek tiruan sederhana untuk memanggilnya
        class MockMessage:
            def __init__(self, original_message):
                self.message = original_message
        await start_command(MockMessage(query.message), context)

    elif query.data.startswith('order_'):
        produk_id = query.data.split('_')[1]
        produk = next((p for p in muat_data('products.json') if p['id'] == produk_id), None)
        if not produk:
            # --- PERBAIKAN: Mengirim pesan baru, bukan mengedit ---
            await context.bot.send_message(chat_id=chat_id, text="Waduh, produknya udah gaib atau stoknya baru saja habis. Coba /start lagi.")
            await query.message.delete()
            return
        await query.edit_message_text(f"Oke, siap! Pesananmu lagi dibuatin tiketnya... ⏳")
        try:
            external_id = f"skynexio-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(external_id=external_id, amount=produk['harga'], description=f"Pembelian {produk['nama']}", customer={'given_names': update.effective_user.full_name})
            orders = muat_data('orders.json')
            orders.append({'external_id': external_id, 'user_id': update.effective_user.id, 'produk_id': produk_id, 'harga': produk['harga'], 'status': 'PENDING'})
            simpan_data(orders, 'orders.json')
            await query.edit_message_text(f"Tiket nontonmu sudah siap! ✅\n\nKlik link di bawah untuk bayar!\n\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(f"Gagal buat invoice: {e}"); await query.edit_message_text("❌ Oops, mesin tiketnya ngambek.")

# Daftarkan semua handler
bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CommandHandler("add", add_stock)); bot_app.add_handler(CommandHandler("newproduct", new_product))
bot_app.add_handler(CommandHandler("delproduct", del_product)); bot_app.add_handler(CommandHandler("edit", edit_product))
bot_app.add_handler(CommandHandler("infostok", info_stock)); bot_app.add_handler(CallbackQueryHandler(button_handler))

# --- WEB SERVER & WEBHOOK ---
@app.route('/')
def index(): return "Skynexio Store Bot server is alive and well!"
@app.route(f'/telegram', methods=['POST'])
async def telegram_webhook():
    try: await bot_app.initialize(); await bot_app.process_update(Update.de_json(request.get_json(force=True), bot_app.bot)); return jsonify({'status': 'ok'})
    except Exception as e: logger.error(f"Error webhook Telegram: {e}"); return jsonify({'status': 'error'}), 500
@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN: return jsonify({'status': 'error'}), 403
    data = request.json
    if data.get('status') == 'PAID':
        external_id = data.get('external_id')
        orders = muat_data('orders.json')
        order_data = next((o for o in orders if o.get('external_id') == external_id and o.get('status') == 'PENDING'), None)
        if order_data:
            await bot_app.initialize(); order_data['status'] = 'PAID'
            counters = muat_data('counter.json'); counters['total_orders'] += 1; counters['total_turnover'] += order_data.get('harga', 0)
            simpan_data(counters, 'counter.json'); simpan_data(orders, 'orders.json')
            akun = ambil_akun_dari_stok(order_data['produk_id'])
            link_garansi = f"https://t.me/{ADMIN_USERNAME}"
            if akun:
                parts = akun.split('|'); login = parts[0]
                pesan_akun = f"Login: `{login}`"
                if len(parts) > 1: pesan_akun += f"\nProfil: **{parts[1]}**"
                if len(parts) > 2: pesan_akun += f"\nPIN: `{parts[2]}`"
                pesan_sukses = (f"Yess, pembayaran lunas! 🎉\n\nIni dia akses VIP kamu:\n\n{pesan_akun}\n\n---\n"
                              f"Ada masalah? Garansi berlaku jika Anda mengirimkan bukti screenshot setelah berhasil login ke [Admin]({link_garansi}) untuk konfirmasi.")
                await bot_app.bot.send_message(order_data['user_id'], pesan_sukses, parse_mode='Markdown')
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan sukses!\nID: {external_id}\nAkun: {akun}\nUser: {order_data['user_id']}")
            else:
                await bot_app.bot.send_message(order_data['user_id'], "Pembayaran berhasil, namun stok habis. Admin akan segera menghubungi Anda."); await bot_app.bot.send_message(ADMIN_CHAT_ID, f"‼️ STOK HABIS ‼️\nID: {external_id} lunas tapi stok kosong! Hubungi user: {order_data['user_id']}")
    return jsonify({'status': 'success'}), 200

# --- FUNGSI UTAMA ---
async def setup():
    await bot_app.initialize()
    webhook_url = f"{WEBHOOK_URL}/telegram"
    await bot_app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
    logger.info(f"Telegram webhook diatur ke {webhook_url}")
    commands = [BotCommand("start", "🚀 Mulai Bot"), BotCommand("infostok", "📦 (Admin) Cek Laporan Stok")]
    await bot_app.bot.set_my_commands(commands)
    logger.info("Menu perintah berhasil diatur.")
def main():
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)
if __name__ == '__main__':
    main()
