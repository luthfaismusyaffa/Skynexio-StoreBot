# supabase_client.py

import os
import requests

# Ambil URL dan Kunci dari Environment Variables di hosting Anda
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation" # Meminta Supabase mengembalikan data yang diubah
}

def get_products():
    """Mengambil semua data produk."""
    res = requests.get(f"{SUPABASE_URL}/rest/v1/products?select=*", headers=HEADERS)
    res.raise_for_status() # Akan error jika permintaan gagal
    return res.json()

def get_stock(produk_id):
    """Mengecek jumlah stok yang tersedia untuk sebuah produk."""
    params = {"produk_id": f"eq.{produk_id}", "is_sold": "eq.false"}
    res = requests.get(f"{SUPABASE_URL}/rest/v1/stok_akun?select=id", headers=HEADERS, params=params)
    res.raise_for_status()
    return res.json()

def pop_one_akun(produk_id):
    """Mengambil satu akun dari stok dan menandainya sebagai terjual."""
    stok = get_stock(produk_id)
    if not stok:
        return None
    
    akun_to_sell = stok[0]
    akun_id = akun_to_sell['id']
    
    # Update status is_sold menjadi true dan ambil detail akunnya
    patch_data = {"is_sold": True}
    res = requests.patch(f"{SUPABASE_URL}/rest/v1/stok_akun?id=eq.{akun_id}", headers=HEADERS, json=patch_data)
    res.raise_for_status()
    
    updated_akun = res.json()
    return updated_akun[0] # Kembalikan data akun yang baru diupdate

def insert_order(external_id, user_id, produk_id, harga):
    """Memasukkan data pesanan baru."""
    data = {"external_id": external_id, "user_id": user_id, "produk_id": produk_id, "harga": harga, "status": "PENDING"}
    requests.post(f"{SUPABASE_URL}/rest/v1/orders", headers=HEADERS, json=data)

def update_order_status(external_id, akun_id=None):
    """Mengubah status pesanan menjadi PAID dan mencatat akun yang terjual."""
    payload = {"status": "PAID"}
    if akun_id:
        payload["akun_id"] = akun_id
    requests.patch(f"{SUPABASE_URL}/rest/v1/orders?external_id=eq.{external_id}", headers=HEADERS, json=payload)

def get_order_user(external_id):
    """Mengambil data pesanan berdasarkan external_id dari Xendit."""
    params = {"external_id": f"eq.{external_id}"}
    res = requests.get(f"{SUPABASE_URL}/rest/v1/orders?select=user_id,status", headers=HEADERS, params=params)
    res.raise_for_status()
    return res.json()
