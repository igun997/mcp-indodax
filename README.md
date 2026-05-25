# Indodax MCP Server 🚀

Expose semua *Private REST API* Indodax sebagai **MCP tools** (bisa dipakai Claude Code atau agen AI lain). Fokus: cepat dipakai, mudah dipahami.

---

## 1. Persiapan Cepat
```bash
# clone & masuk repo
git clone https://github.com/adhinugroho1711/mcp-indodax.git
cd mcp-indodax

# buat virtual-env
python -m venv .venv && source .venv/bin/activate

# install paket
pip install -r requirements.txt
```

## 2. Isi Kredensial
Buat `.env` (tidak akan ter-push ke git):
```ini
# Indodax API
INDODAX_API_KEY=YOUR_API_KEY
INDODAX_API_SECRET=YOUR_SECRET

# HTTP Basic Auth — wajib saat pakai HTTP transport (uvicorn)
# Diabaikan saat transport stdio
MCP_AUTH_USER=admin
MCP_AUTH_PASSWORD=ganti_dengan_password_kuat
```

## 3. Jalankan

### stdio (default — untuk Claude Code / editor lokal)
```bash
python server.py
```
Tidak butuh Basic Auth. Proses lokal, tidak ada port terbuka.

### HTTP Streamable (direkomendasikan untuk remote/server)
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```
Setiap request **wajib** membawa header:
```
Authorization: Basic <base64(MCP_AUTH_USER:MCP_AUTH_PASSWORD)>
```

### HTTP SSE (legacy clients)
```bash
uvicorn server:sse_app --host 0.0.0.0 --port 8000
```

## 4. Autentikasi HTTP Basic Auth

Basic Auth aktif otomatis bila `MCP_AUTH_USER` dan `MCP_AUTH_PASSWORD` di-set di `.env`.  
Bila tidak di-set, HTTP transport tetap jalan tanpa auth (hati-hati untuk deployment publik).

| Transport | Basic Auth |
|-----------|------------|
| `stdio` (python server.py) | ❌ Tidak berlaku |
| `HTTP streamable` (uvicorn server:app) | ✅ Aktif bila env var di-set |
| `HTTP SSE` (uvicorn server:sse_app) | ✅ Aktif bila env var di-set |

### Cara generate password kuat
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Contoh request curl dengan Basic Auth
```bash
curl -u admin:your_password http://localhost:8000/
```

### Contoh konfigurasi client MCP (HTTP)
```json
{
  "mcpServers": {
    "indodax": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Basic YWRtaW46eW91cl9wYXNzd29yZA=="
      }
    }
  }
}
```
> Base64 dari `admin:your_password` — generate: `echo -n "user:pass" | base64`

## 5. Integrasi Editor (Claude Code) — stdio

Gunakan transport stdio agar tidak perlu Basic Auth:

```json
{
  "mcpServers": {
    "indodax": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/TO/mcp-indodax", "run", "server.py"]
    }
  }
}
```

Simpan sebagai `mcp_servers.json` di root proyek, lalu:
- **VS Code**: Command Palette → `Claude: Start MCP Server` → pilih `indodax`
- **JetBrains**: Tools → Claude → **Start MCP Server** → pilih `indodax`
- **Neovim**: simpan di `~/.config/claude/` → `:ClaudeStartServer indodax`

---

## 6. Contoh Pakai Tool
```python
from server import get_info, trade
import asyncio, json

async def demo():
    print(json.dumps(await get_info(), indent=2))
    # order beli BTC 50k IDR
    # await trade("btc_idr", "buy", price=500000000, idr=50000)
asyncio.run(demo())
```

---

## Daftar Lengkap MCP Tools

### Public (tanpa API key)
| Tool | Deskripsi |
|------|-----------|
| `server_time()` | Waktu server bursa |
| `pairs()` | Daftar pair tersedia |
| `price_increments()` | Kelipatan harga tiap pair |
| `summaries()` | Ringkasan market seluruh pair |
| `ticker(pair_id)` | Harga terkini satu pair |
| `ticker_all()` | Harga seluruh pair |
| `trades(pair_id)` | Transaksi terakhir |

### Private (butuh `INDODAX_API_KEY` + `INDODAX_API_SECRET`)
| Tool | Deskripsi |
|------|-----------|
| `get_info()` | Info akun & saldo |
| `trans_history(start, end)` | Histori transaksi |
| `trade(pair, type, price, idr, crypto)` | Buat order beli/jual |
| `open_orders(pair)` | Lihat order aktif |
| `order_history(...)` | Histori order |
| `get_order(order_id)` | Detail order by ID |
| `get_order_by_client_order_id(id)` | Detail order by client ID |
| `cancel_order(order_id)` | Batalkan order by ID |
| `cancel_by_client_order_id(id)` | Batalkan order by client ID |
| `withdraw_coin(currency, amount, address, ...)` | Tarik kripto |
| `withdraw_fee(currency, amount, address, ...)` | Estimasi fee tarik |
| `list_downline()` | Daftar referral (partner) |
| `check_downline(username)` | Cek apakah user downline |
| `create_voucher(amount, description)` | Buat voucher (partner) |

---

## Contoh Trading

### Cek harga & buat order
```python
import asyncio
from server import ticker, trade, open_orders

async def main():
    btc = await ticker("btcidr")
    print(f"Harga BTC: {int(btc['last']):,} IDR")

    # Beli BTC senilai 100.000 IDR
    order = await trade("btcidr", "buy", price=int(btc['last']), idr=100000)
    print("Order:", order)

asyncio.run(main())
```

### Lihat & batalkan order aktif
```python
import asyncio
from server import open_orders, cancel_order

async def main():
    orders = await open_orders()
    for pair, order_list in orders.items():
        for o in order_list:
            print(f"{pair} | {o['type']} | {o['order_id']}")
            # await cancel_order(order_id=int(o['order_id']))

asyncio.run(main())
```

---

## Struktur Proyek

```
├── server.py          # MCP tools + BasicAuthMiddleware
├── requirements.txt   # Dependensi Python
├── mcp_servers.json   # Contoh konfigurasi runner (stdio)
├── .gitignore         # Mengabaikan .env, .venv, dsb
└── README.md          # Dokumentasi ini
```

## Lisensi

MIT © 2025 Prihanantho Adhi Nugroho
