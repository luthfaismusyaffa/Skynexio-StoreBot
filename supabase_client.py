# supabase_client.py

import os
import requests

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

def get_products():
    res = requests.get(f"{SUPABASE_URL}/rest/v1/products?select=*", headers=HEADERS)
    res.raise_for_status()
    return res.json()

def get_stock(produk_id):
    params = {"produk_id": f"eq.{produk_id}", "is_sold": "eq.false"}
    res = requests.get(f"{SUPABASE_URL}/rest/v1/stok_akun?select=id", headers=HEADERS, params=params)
    res.raise_for_status()
    return res.json()

def pop_one_akun(produk_id):
    stok = get_stock(produk_id)
    if not stok: return None
    
    akun_id = stok[0]['id']
    patch_data = {"is_sold": True}
    res = requests.patch(f"{SUPABASE_URL}/rest/v1/stok_akun?id=eq.{akun_id}", headers=HEADERS, json=patch_data)
    res.raise_for_status()
    
    return res.json()[0]

def insert_order(external_id, user_id, produk_id, harga):
    data = {"external_id": external_id, "user_id": user_id, "produk_id": produk_id, "harga": harga}
    requests.post(f"{SUPABASE_URL}/rest/v1/orders", headers=HEADERS, json=data)

def update_order_status(external_id, akun_id):
    payload = {"status": "PAID", "akun_id": akun_id}
    requests.patch(f"{SUPABASE_URL}/rest/v1/orders?external_id=eq.{external_id}", headers=HEADERS, json=payload)

def get_order_user(external_id):
    params = {"external_id": f"eq.{external_id}", "select": "user_id,status"}
    res = requests.get(f"{SUPABASE_URL}/rest/v1/orders", headers=HEADERS, params=params)
    res.raise_for_status()
    return res.json()
