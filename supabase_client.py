import os
import requests

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def get_products():
    res = requests.get(f"{SUPABASE_URL}/rest/v1/products", headers=HEADERS)
    return res.json()

def get_stock(produk_id):
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/stok_akun",
        headers=HEADERS,
        params={"produk_id": f"eq.{produk_id}", "sold": "eq.false"}
    )
    return res.json()

def pop_one_akun(produk_id):
    stok = get_stock(produk_id)
    if not stok:
        return None
    akun = stok[0]
    id_akun = akun["id"]
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/stok_akun?id=eq.{id_akun}",
        headers=HEADERS,
        json={"sold": True}
    )
    return akun

def insert_order(external_id, user_id, produk_id, harga):
    data = {
        "external_id": external_id,
        "user_id": user_id,
        "produk_id": produk_id,
        "harga": harga,
        "status": "PENDING"
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/orders", headers=HEADERS, json=data)

def update_order_status(external_id, akun_id=None):
    data = {"status": "PAID"}
    if akun_id:
        data["akun_id"] = akun_id
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/orders?external_id=eq.{external_id}",
        headers=HEADERS,
        json=data
    )

def get_order_user(external_id):
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/orders",
        headers=HEADERS,
        params={"external_id": f"eq.{external_id}"}
    )
    return res.json()
