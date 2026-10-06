# -*- coding: utf-8 -*-
"""
BOT TELEGRAM ĐA NĂNG - BẢN HOÀN CHỈNH
TikTok no-logo (Snaptik) + MP3 | Bán Data/VPN/Proxy | AI Gemini | SePay | Admin Panel | Bot con
"""
import os, io, re, time, html, hmac, sqlite3, logging, threading, urllib.parse, json
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta

import requests, telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from flask import Flask, request, jsonify

try:
    from google import genai
except Exception:
    genai = None

# ══════════════════════════ CẤU HÌNH ══════════════════════════
def env(k, d=""): return os.environ.get(k, d).strip()

BOT_TOKEN      = env("BOT_TOKEN") or exit("❌ Thiếu BOT_TOKEN")
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL   = env("GEMINI_MODEL", "gemini-2.5-flash")
SEPAY_API_KEY  = env("SEPAY_API_KEY")
ADMIN_ID       = int(env("ADMIN_ID", "8909964397"))
BOT_USERNAME   = env("BOT_USERNAME", "@dangphuongvu_bot")
ADMIN_USERNAME = env("ADMIN_USERNAME", "@dpvuuu")
BANK_NAME      = env("BANK_NAME", "TPBank")
ACCOUNT_NO     = env("ACCOUNT_NO", "10005824236")
ACCOUNT_NAME   = env("ACCOUNT_NAME", "DANG PHUONG VU")
CREATE_BOT_FEE = int(env("CREATE_BOT_FEE", "20000"))
AI_COOLDOWN    = int(env("AI_COOLDOWN", "4"))
DB_PATH        = env("DB_PATH") or ("/var/data/bot_database.db" if os.path.isdir("/var/data") else "bot_database.db")
PORT           = int(env("PORT", "8080"))
PROXY_URL      = env("PROXY_URL")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

main_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=8)
app      = Flask(__name__)

ai_client = None
if genai and GEMINI_API_KEY:
    try: ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e: log.warning("Gemini init: %s", e)

user_states, active_child_bots = {}, {}
child_lock, inflight_lock, proxy_lock = threading.Lock(), threading.Lock(), threading.Lock()
ai_last_call = {}
webhook_log  = deque(maxlen=30)
inflight     = set()

# ══════════════════════════ DATABASE ══════════════════════════
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try: yield conn; conn.commit()
    except Exception: conn.rollback(); raise
    finally: conn.close()

def cur_month(): return datetime.now().strftime("%Y-%m")

def init_db():
    d = os.path.dirname(DB_PATH)
    if d: os.makedirs(d, exist_ok=True)
    with db() as c:
        try: c.execute("PRAGMA journal_mode=WAL")
        except Exception: pass

        c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
            balance INTEGER DEFAULT 0, total_recharged INTEGER DEFAULT 0,
            month_recharged INTEGER DEFAULT 0, month_key TEXT DEFAULT '')""")
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        if "month_key" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN month_key TEXT DEFAULT ''")

        c.execute("""CREATE TABLE IF NOT EXISTS user_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            bot_token TEXT UNIQUE, bot_username TEXT,
            status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            amount INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS transactions (
            tx_id TEXT PRIMARY KEY, user_id INTEGER, amount INTEGER,
            kind TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT DEFAULT '',
            price INTEGER NOT NULL, category TEXT DEFAULT 'Data 4G',
            image_url TEXT DEFAULT '',
            delivery_type TEXT DEFAULT 'text',
            delivery_data TEXT DEFAULT '',
            stock INTEGER DEFAULT -1, sold INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, product_id INTEGER, product_name TEXT,
            price INTEGER, status TEXT DEFAULT 'paid',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS proxy_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL, port INTEGER NOT NULL,
            username TEXT DEFAULT '', password TEXT DEFAULT '',
            protocol TEXT DEFAULT 'HTTP',
            region TEXT DEFAULT '', isp TEXT DEFAULT '',
            status TEXT DEFAULT 'available',
            sold_to INTEGER DEFAULT 0,
            sold_at TEXT DEFAULT '',
            expires_at TEXT DEFAULT '',
            product_id INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_status ON proxy_stock(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_soldto ON proxy_stock(sold_to)")

        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT DEFAULT '')""")
        defaults = {
            "home_title":    "🚀 HỆ THỐNG BOT ĐA NĂNG",
            "home_subtitle": "TikTok • Data 4G • Proxy • AI",
            "welcome_msg":   "Chào mừng bạn! Nhắn tin bất kỳ để chat với AI, gửi link TikTok để tải video.",
            "shop_title":    "🛒 CỬA HÀNG DATA / VPN / PROXY",
            "support_text":  "Nhắn admin để được hỗ trợ nhanh nhất!",
            "footer_note":   "Cảm ơn bạn đã sử dụng dịch vụ! ❤️",
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v))

        c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)",
                  (ADMIN_ID, "", "Admin"))

        cnt = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if cnt == 0:
            seed = [
                ("🌐 Data Viettel 30K – Không giới hạn", "Gói data Viettel KHÔNG GIỚI HẠN data, tốc độ cao, dùng 30 ngày. Hỗ trợ 4G/5G.", 30000, "Data 4G", "text", "Viettel 30K – Không giới hạn", -1),
                ("🌐 Data Viettel 50K – Không giới hạn", "Gói data Viettel KHÔNG GIỚI HẠN data, tốc độ cao, dùng 30 ngày. Hỗ trợ 4G/5G.", 50000, "Data 4G", "text", "Viettel 50K – Không giới hạn", -1),
                ("📱 Data VinaPhone 30K – Không giới hạn", "Gói data VinaPhone KHÔNG GIỚI HẠN data, dùng 30 ngày. Hỗ trợ 4G/5G.", 30000, "Data 4G", "text", "VinaPhone 30K – Không giới hạn", -1),
                ("📱 Data VinaPhone 50K – Không giới hạn", "Gói data VinaPhone KHÔNG GIỚI HẠN data, dùng 30 ngày. Hỗ trợ 4G/5G.", 50000, "Data 4G", "text", "VinaPhone 50K – Không giới hạn", -1),
                ("📶 Data MobiFone 30K – Không giới hạn", "Gói data MobiFone KHÔNG GIỚI HẠN data, dùng 30 ngày. Hỗ trợ 4G/5G.", 30000, "Data 4G", "text", "MobiFone 30K – Không giới hạn", -1),
                ("📶 Data MobiFone 50K – Không giới hạn", "Gói data MobiFone KHÔNG GIỚI HẠN data, dùng 30 ngày. Hỗ trợ 4G/5G.", 50000, "Data 4G", "text", "MobiFone 50K – Không giới hạn", -1),
                ("🌐 Proxy dân cư Việt Nam 30 ngày", "Proxy dân cư Việt Nam, KHÔNG GIỚI HẠN băng thông, hỗ trợ HTTP/SOCKS5. IP sạch, tốc độ cao, phù hợp nuôi tài khoản, chạy tool.", 50000, "Proxy", "proxy", "30", -1),
                ("🌐 Proxy dân cư Việt Nam 7 ngày", "Proxy dân cư Việt Nam, KHÔNG GIỚI HẠN băng thông, hỗ trợ HTTP/SOCKS5. Dùng 7 ngày.", 20000, "Proxy", "proxy", "7", -1),
                ("🔒 VPN cao cấp 1 tháng", "VPN tốc độ cao, không giới hạn dung lượng, hỗ trợ đa nền tảng. Dùng 30 ngày.", 80000, "VPN", "text", "VPN 1 tháng", -1),
            ]
            for row in seed:
                c.execute("""INSERT INTO products
                    (name,description,price,category,delivery_type,delivery_data,stock)
                    VALUES (?,?,?,?,?,?,?)""", row)
            log.info("✅ Đã seed 9 sản phẩm mặc định (data + proxy + VPN)")

# ─────────────── USER ───────────────
def get_or_create_user(uid, username, full_name):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)",
                  (uid, username, full_name))
        c.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?",
                  (username, full_name, uid))
        row = c.execute("SELECT balance,total_recharged,month_recharged,month_key FROM users WHERE user_id=?",
                        (uid,)).fetchone()
    month = row[2] if row[3] == cur_month() else 0
    return {"id": uid, "balance": row[0], "total": row[1], "month": month}

def _credit(c, uid, amount):
    mk = cur_month()
    c.execute("""UPDATE users SET balance=balance+?, total_recharged=total_recharged+?,
                 month_recharged=CASE WHEN month_key=? THEN month_recharged+? ELSE ? END,
                 month_key=? WHERE user_id=?""",
              (amount, amount, mk, amount, amount, mk, uid))

def admin_add_money(uid, amount):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id,username,full_name) VALUES (?, '', '')", (uid,))
        if amount >= 0: _credit(c, uid, amount)
        else: c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))

def process_deposit(tx_id, uid, amount):
    with db() as c:
        cur = c.execute("INSERT OR IGNORE INTO transactions (tx_id,user_id,amount,kind) VALUES (?,?,?,'deposit')",
                        (tx_id, uid, amount))
        if cur.rowcount == 0: return False
        c.execute("INSERT OR IGNORE INTO users (user_id,username,full_name) VALUES (?, '', '')", (uid,))
        _credit(c, uid, amount); return True

def process_donation(tx_id, uid, amount):
    with db() as c:
        cur = c.execute("INSERT OR IGNORE INTO transactions (tx_id,user_id,amount,kind) VALUES (?,?,?,'donate')",
                        (tx_id, uid, amount))
        if cur.rowcount == 0: return False
        c.execute("INSERT INTO donations (user_id,amount) VALUES (?,?)", (uid, amount)); return True

def token_exists(t):
    with db() as c:
        return c.execute("SELECT 1 FROM user_bots WHERE bot_token=?", (t,)).fetchone() is not None

def save_user_bot(uid, token, uname):
    with db() as c:
        c.execute("INSERT INTO user_bots (user_id,bot_token,bot_username,status) VALUES (?,?,?,'active')",
                  (uid, token, uname))

def deactivate_bot(token):
    with db() as c:
        c.execute("UPDATE user_bots SET status='inactive' WHERE bot_token=?", (token,))

# ─────────────── SETTINGS ───────────────
def setting_get(key, default=""):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] else default

def setting_set(key, value):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))

def setting_all():
    with db() as c:
        rows = c.execute("SELECT key,value FROM settings").fetchall()
    return {r[0]: r[1] for r in rows}

# ─────────────── SHOP ───────────────
def shop_get(pid):
    with db() as c:
        r = c.execute("""SELECT id,name,description,price,category,image_url,
                         delivery_type,delivery_data,stock,sold,active FROM products WHERE id=?""",
                      (pid,)).fetchone()
    if not r: return None
    return dict(zip(["id","name","description","price","category","image_url",
                     "delivery_type","delivery_data","stock","sold","active"], r))

def shop_list(category=None, only_active=True, limit=50):
    with db() as c:
        q = "SELECT id,name,price,category,image_url,stock,sold,active FROM products WHERE 1=1"
        p = []
        if only_active: q += " AND active=1"
        if category and category != "Tất cả":
            q += " AND category=?"; p.append(category)
        q += " ORDER BY id ASC LIMIT ?"; p.append(limit)
        rows = c.execute(q, p).fetchall()
    return [dict(zip(["id","name","price","category","image_url","stock","sold","active"], r)) for r in rows]

def shop_top(limit=8):
    with db() as c:
        rows = c.execute("""SELECT id,name,price,category,image_url,stock,sold,active
                            FROM products WHERE active=1 ORDER BY sold DESC LIMIT ?""",
                         (limit,)).fetchall()
    return [dict(zip(["id","name","price","category","image_url","stock","sold","active"], r)) for r in rows]

def shop_categories():
    with db() as c:
        rows = c.execute("SELECT DISTINCT category FROM products WHERE active=1").fetchall()
    return ["Tất cả"] + [r[0] for r in rows if r[0]]

def shop_purchase(uid, pid):
    with db() as c:
        r = c.execute("SELECT name,price,stock,active,delivery_type,delivery_data FROM products WHERE id=?",
                      (pid,)).fetchone()
        if not r: return False, "Không tìm thấy sản phẩm"
        name, price, stock, active, dtype, ddata = r
        if not active: return False, "Sản phẩm đã ngừng bán"
        if stock == 0: return False, "Sản phẩm đã hết hàng"
        cur = c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                        (price, uid, price))
        if cur.rowcount == 0: return False, "Số dư không đủ"
        if stock > 0:
            c.execute("UPDATE products SET stock=stock-1, sold=sold+1 WHERE id=?", (pid,))
        else:
            c.execute("UPDATE products SET sold=sold+1 WHERE id=?", (pid,))
        c.execute("INSERT INTO orders (user_id,product_id,product_name,price) VALUES (?,?,?,?)",
                  (uid, pid, name, price))
    return True, {"id": pid, "name": name, "price": price,
                  "delivery_type": dtype, "delivery_data": ddata}

def shop_myorders(uid, limit=10):
    with db() as c:
        rows = c.execute("""SELECT id,product_name,price,created_at FROM orders
                            WHERE user_id=? ORDER BY id DESC LIMIT ?""", (uid, limit)).fetchall()
    return rows

def shop_stats():
    with db() as c:
        total = c.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders").fetchone()
        today = c.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders WHERE DATE(created_at)=DATE('now')").fetchone()
        top = c.execute("""SELECT product_name, COUNT(*), SUM(price) FROM orders
                           GROUP BY product_name ORDER BY COUNT(*) DESC LIMIT 5""").fetchall()
    return {"total_count": total[0], "total_revenue": total[1],
            "today_count": today[0], "today_revenue": today[1], "top": top}

def product_delete(pid):
    with db() as c:
        c.execute("DELETE FROM products WHERE id=?", (pid,))

def product_toggle(pid):
    with db() as c:
        row = c.execute("SELECT active FROM products WHERE id=?", (pid,)).fetchone()
        if not row: return None
        new = 0 if row[0] else 1
        c.execute("UPDATE products SET active=? WHERE id=?", (new, pid))
        return new

def product_update_field(pid, field, value):
    allowed = {"name", "description", "price", "category", "stock",
               "delivery_data", "delivery_type"}
    if field not in allowed: return False
    with db() as c:
        c.execute(f"UPDATE products SET {field}=? WHERE id=?", (value, pid))
    return True

# ─────────────── PROXY ───────────────
def proxy_import(lines):
    added, errs = 0, []
    with db() as c:
        for i, line in enumerate(lines, 1):
            line = (line or "").strip()
            if not line or line.startswith("#"): continue
            try:
                meta = line.split("|")
                core = meta[0].strip()
                region = meta[1].strip() if len(meta) > 1 else ""
                isp    = meta[2].strip() if len(meta) > 2 else ""
                proto  = meta[3].strip().upper() if len(meta) > 3 else "HTTP"
                parts = core.split(":")
                if len(parts) < 2:
                    errs.append(f"Dòng {i}: thiếu port"); continue
                ip, port = parts[0].strip(), int(parts[1])
                pu = parts[2].strip() if len(parts) > 2 else ""
                pp = parts[3].strip() if len(parts) > 3 else ""
                if not ip or not (1 <= port <= 65535):
                    errs.append(f"Dòng {i}: ip/port lỗi"); continue
                dup = c.execute("SELECT 1 FROM proxy_stock WHERE ip=? AND port=?",
                                (ip, port)).fetchone()
                if dup: errs.append(f"Dòng {i}: trùng {ip}:{port}"); continue
                c.execute("""INSERT INTO proxy_stock
                    (ip,port,username,password,protocol,region,isp)
                    VALUES (?,?,?,?,?,?,?)""", (ip, port, pu, pp, proto, region, isp))
                added += 1
            except Exception as e:
                errs.append(f"Dòng {i}: {e}")
    return added, errs

def proxy_stock_count():
    with db() as c:
        avail = c.execute("SELECT COUNT(*) FROM proxy_stock WHERE status='available'").fetchone()[0]
        sold  = c.execute("SELECT COUNT(*) FROM proxy_stock WHERE status='sold'").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM proxy_stock").fetchone()[0]
    return {"available": avail, "sold": sold, "total": total}

def proxy_buy(uid, product_id):
    with proxy_lock:
        with db() as c:
            p = c.execute("""SELECT name,price,active,delivery_type,delivery_data
                             FROM products WHERE id=?""", (product_id,)).fetchone()
            if not p: return False, "Sản phẩm không tồn tại", None
            name, price, active, dtype, ddata = p
            if not active: return False, "Sản phẩm đã ngừng bán", None
            if dtype != "proxy": return False, "Không phải sản phẩm proxy", None
            try: days = int(ddata or 30)
            except Exception: days = 30
            avail = c.execute("SELECT COUNT(*) FROM proxy_stock WHERE status='available'").fetchone()[0]
            if avail <= 0: return False, "Kho proxy đã hết. Vui lòng liên hệ admin!", None
            cur = c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                            (price, uid, price))
            if cur.rowcount == 0: return False, "Số dư không đủ", None
            row = c.execute("""SELECT id,ip,port,username,password,protocol,region,isp
                               FROM proxy_stock WHERE status='available'
                               ORDER BY id LIMIT 1""").fetchone()
            if not row:
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (price, uid))
                return False, "Kho proxy vừa hết. Tiền đã hoàn lại.", None
            pid, ip, port, pu, pp, proto, region, isp = row
            exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""UPDATE proxy_stock SET status='sold', sold_to=?, sold_at=CURRENT_TIMESTAMP,
                         expires_at=?, product_id=? WHERE id=?""", (uid, exp, product_id, pid))
            c.execute("""INSERT INTO orders (user_id,product_id,product_name,price)
                         VALUES (?,?,?,?)""", (uid, product_id, name, price))
    return True, "", {"id": pid, "ip": ip, "port": port, "username": pu, "password": pp,
                      "protocol": proto, "region": region, "isp": isp,
                      "expires_at": exp, "days": days, "name": name, "price": price}

def proxy_my_list(uid):
    with db() as c:
        rows = c.execute("""SELECT id,ip,port,username,password,protocol,region,isp,
                            expires_at FROM proxy_stock WHERE sold_to=? ORDER BY id DESC""", (uid,)).fetchall()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = []
    for r in rows:
        status = "active" if (r[8] and r[8] > now) else "expired"
        result.append({"id": r[0], "ip": r[1], "port": r[2], "username": r[3], "password": r[4],
                       "protocol": r[5], "region": r[6], "isp": r[7],
                       "expires_at": r[8], "status": status})
    return result

# ══════════════════════════ TIKTOK (SNAPTIK) ══════════════════════════
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
URL_RE = re.compile(r"https?://(?:[\w-]+\.)?tiktok\.com/\S+", re.I)
MAX_UPLOAD = 49 * 1024 * 1024
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

class SnapTikClient:
    """Client tải video TikTok không logo qua snaptik.app"""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(UA)
        if PROXIES:
            self.session.proxies.update(PROXIES)
        self.base_url = "https://dev.snaptik.app"

    def _get_token(self):
        try:
            r = self.session.get(f"{self.base_url}/", timeout=15)
            m = re.search(r'name="token"\s+value="([^"]+)"', r.text)
            if m:
                return m.group(1)
        except Exception as e:
            log.warning("SnapTik get_token: %s", e)
        return None

    def _get_script(self, url):
        token = self._get_token()
        if not token:
            return None
        try:
            r = self.session.post(f"{self.base_url}/abc2.php",
                                  data={"token": token, "url": url},
                                  timeout=25)
            return r.text
        except Exception as e:
            log.warning("SnapTik get_script: %s", e)
            return None

    def _extract_video_url(self, script):
        """Trích xuất URL video HD từ script trả về"""
        # Tìm tokenhd
        m = re.search(r'data-tokenhd="([^"]+)"', script)
        if not m:
            # Thử tìm trong JSON
            m = re.search(r'"tokenhd"\s*:\s*"([^"]+)"', script)
        if not m:
            return None
        tokenhd = m.group(1)

        # Gọi getHdLink.php
        try:
            r = self.session.get(f"{self.base_url}/getHdLink.php?token={tokenhd}", timeout=15)
            data = r.json()
            if data.get("error"):
                return None
            hd_url = data.get("url")
            if hd_url and hd_url.startswith("http"):
                return hd_url
        except Exception as e:
            log.warning("SnapTik getHdLink: %s", e)

        # Fallback: tìm URL video trực tiếp trong script
        urls = re.findall(r'https?://[^\s"\']+\.mp4[^\s"\']*', script)
        for u in urls:
            if "watermark" not in u.lower() and "logo" not in u.lower():
                return u
        return urls[0] if urls else None

    def fetch(self, url):
        """Lấy link video không logo"""
        script = self._get_script(url)
        if not script:
            return None
        video_url = self._extract_video_url(script)
        if not video_url:
            return None
        return {
            "id": re.search(r'/video/(\d+)', url) or "",
            "title": "TikTok Video",
            "author": {"nickname": ""},
            "hdplay": video_url,
            "play": video_url,
            "music": None,
            "images": []
        }

snaptik_client = SnapTikClient()

def abs_url(u):
    if not u: return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"):  return "https://www.tikwm.com" + u
    return u

def download_file(url, name):
    if not url: return None
    try:
        with requests.get(url, headers=UA, stream=True,
                          timeout=(10,60), proxies=PROXIES) as r:
            r.raise_for_status()
            if int(r.headers.get("Content-Length") or 0) > MAX_UPLOAD: return None
            buf, total = io.BytesIO(), 0
            for chunk in r.iter_content(256*1024):
                total += len(chunk)
                if total > MAX_UPLOAD: return None
                buf.write(chunk)
        buf.seek(0); buf.name = name
        return buf
    except Exception as e:
        log.warning("Tải file lỗi: %s", e); return None

def cache_put(vid, url):
    if len(link_cache) > 2000: link_cache.clear()
    link_cache[vid] = url

def mp3_markup(vid, extra_url=None):
    m = types.InlineKeyboardMarkup(row_width=1)
    if extra_url: m.add(types.InlineKeyboardButton("📥 Mở link video", url=extra_url))
    if vid: m.add(types.InlineKeyboardButton("🎵 Tải nhạc MP3", callback_data=f"dl_mp3|{vid}"))
    return m

def safe_edit(bot, chat_id, mid, text):
    try:
        if mid: bot.edit_message_text(text, chat_id, mid); return
    except Exception: pass
    try: bot.send_message(chat_id, text)
    except Exception: pass

def deliver_tiktok(bot, chat_id, url):
    """Tải video TikTok không logo qua Snaptik"""
    data = snaptik_client.fetch(url)
    if not data or not data.get("hdplay"):
        return False, "❌ Không tải được. Video phải công khai và link đúng dạng TikTok!"

    vid = str(data.get("id") or "")
    if vid: cache_put(vid, url)
    title  = (data.get("title") or "TikTok").strip()
    author = (data.get("author") or {}).get("nickname") or ""
    caption = f"🎬 <b>{html.escape(title[:200])}</b>"
    if author: caption += f"\n👤 {html.escape(author)}"
    caption += "\n\n✨ <i>Đã gỡ logo thành công!</i>"

    candidates = []
    for key in ("hdplay", "play"):
        u = data.get(key)
        if u and u not in candidates: candidates.append(u)
    if not candidates: return False, "❌ Không tìm thấy video."

    try: bot.send_chat_action(chat_id, "upload_video")
    except Exception: pass
    for u in candidates:
        f = download_file(u, "tiktok.mp4")
        if not f: continue
        try:
            bot.send_video(chat_id, f, caption=caption, supports_streaming=True, reply_markup=mp3_markup(vid))
            return True, ""
        except Exception as e: log.warning("send_video: %s", e)
    bot.send_message(chat_id, caption + "\n\n⚠️ Không gửi trực tiếp được, bấm nút bên dưới.",
                     reply_markup=mp3_markup(vid, extra_url=candidates[0]))
    return True, ""

def deliver_mp3(bot, chat_id, vid):
    """Tách nhạc MP3 (dùng tikwm vì snaptik không hỗ trợ trực tiếp)"""
    url = link_cache.get(vid) or f"https://www.tiktok.com/@tiktok/video/{vid}"
    # Thử tikwm cho MP3
    try:
        r = requests.post("https://www.tikwm.com/api/", data={"url": url, "hd": 1},
                          headers={**UA, "Referer": "https://www.tikwm.com/"},
                          timeout=25, proxies=PROXIES)
        j = r.json()
        if j.get("code") == 0 and j.get("data"):
            data = j["data"]
            info = data.get("music_info") or {}
            music = abs_url(data.get("music") or info.get("play"))
            f = download_file(music, "tiktok_audio.mp3")
            if f:
                try: bot.send_chat_action(chat_id, "upload_audio")
                except Exception: pass
                bot.send_audio(chat_id, f,
                               title=(info.get("title") or data.get("title") or "TikTok Audio")[:60],
                               performer=(info.get("author") or "TikTok")[:60],
                               caption="🎵 <i>Đã tách nhạc thành công!</i>")
                return
    except Exception as e:
        log.warning("MP3 fallback: %s", e)
    bot.send_message(chat_id, "❌ Không tải được nhạc (video không có nhạc?).")

def register_downloader(bot):
    @bot.message_handler(func=lambda m: bool(URL_RE.search(m.text or "")))
    def _on_link(m):
        url = URL_RE.search(m.text).group(0).rstrip(").,]!?")
        try: wait = bot.reply_to(m, "⏳ Đang gỡ logo...")
        except Exception: wait = None
        wait_id = wait.message_id if wait else None
        try: ok, err = deliver_tiktok(bot, m.chat.id, url)
        except Exception as e:
            log.exception("deliver_tiktok: %s", e); ok, err = False, "❌ Có lỗi!"
        if ok:
            if wait_id:
                try: bot.delete_message(m.chat.id, wait_id)
                except Exception: pass
        else: safe_edit(bot, m.chat.id, wait_id, err)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("dl_mp3|"))
    def _on_mp3(c):
        vid = c.data.split("|", 1)[1]
        key = (c.message.chat.id, vid)
        with inflight_lock:
            if key in inflight:
                bot.answer_callback_query(c.id, "Đang xử lý!"); return
            inflight.add(key)
        try:
            bot.answer_callback_query(c.id, "🎵 Đang tách nhạc...")
            deliver_mp3(bot, c.message.chat.id, vid)
        except Exception as e: log.exception("MP3: %s", e)
        finally:
            with inflight_lock: inflight.discard(key)

# ══════════════════════════ AI ══════════════════════════
PERSONA = ("Bạn là trợ lý chatbot hài hước, lầy lội, thân thiện, trả lời tiếng Việt ngắn gọn "
           "(dưới 150 từ). Nếu khách hỏi về data 4G/VPN/Proxy, hãy tư vấn nhiệt tình và "
           "hướng dẫn họ vào mục Cửa hàng. Câu hỏi:")

def ask_gemini(text):
    if not ai_client: return "AI chưa cấu hình, nhưng bot vẫn hoạt động bình thường! 😎"
    try:
        r = ai_client.models.generate_content(model=GEMINI_MODEL, contents=f"{PERSONA}\n\n{text}")
        return (r.text or "").strip() or "Hỏi lại nhé! 🤖"
    except Exception as e:
        log.warning("Gemini: %s", e)
        return "Não AI đang bận, thử lại sau! 🤖"

def split_text(t, size=4000):
    return [t[i:i+size] for i in range(0, len(t), size)] or [""]

def reply_ai(bot, m):
    uid = m.from_user.id if m.from_user else m.chat.id
    text = (m.text or "").strip()
    if len(text) < 2:
        bot.reply_to(m, "Bạn muốn hỏi gì cụ thể hơn không? 😊"); return
    now = time.time()
    if now - ai_last_call.get((id(bot), uid), 0) < AI_COOLDOWN:
        bot.reply_to(m, f"⏳ Đợi {AI_COOLDOWN} giây nhé!"); return
    ai_last_call[(id(bot), uid)] = now
    try: bot.send_chat_action(m.chat.id, "typing")
    except Exception: pass
    answer = html.escape(ask_gemini(text))
    for i, part in enumerate(split_text(answer)):
        if i == 0: bot.reply_to(m, part)
        else: bot.send_message(m.chat.id, part)

# ══════════════════════════ BOT CON ══════════════════════════
def register_child_handlers(bot):
    @bot.message_handler(commands=["start", "help"])
    def _start(m):
        bot.send_message(m.chat.id,
            "<b>🤖 CHÀO MỪNG!</b>\n\n<blockquote>"
            "✨ Gửi link TikTok → tải video không logo + MP3\n"
            "💬 Hoặc chat với AI!</blockquote>",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("💬 Liên hệ Admin",
                    url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}")))
    register_downloader(bot)
    @bot.message_handler(func=lambda m: bool(m.text) and not m.text.startswith("/"))
    def _ai(m):
        try: reply_ai(bot, m)
        except Exception as e: log.warning("AI bot con: %s", e)

def run_child_polling(token, bot):
    first = True
    while token in active_child_bots:
        try:
            try: bot.remove_webhook()
            except Exception: pass
            bot.polling(non_stop=False, skip_pending=first, timeout=20, long_polling_timeout=20)
            first = False; time.sleep(1)
        except ApiTelegramException as e:
            if e.error_code in (401, 404):
                log.warning("Bot con %s token hỏng.", token[:10])
                with child_lock: active_child_bots.pop(token, None)
                deactivate_bot(token); return
            first = False; time.sleep(5)
        except Exception as e:
            log.warning("Bot con lỗi: %s", e); first = False; time.sleep(5)

def start_child_bot(token):
    with child_lock:
        if token in active_child_bots: return
        bot = telebot.TeleBot(token, parse_mode="HTML", threaded=True, num_threads=2)
        register_child_handlers(bot)
        active_child_bots[token] = bot
    threading.Thread(target=run_child_polling, args=(token, bot), daemon=True).start()

def load_all_child_bots():
    with db() as c:
        rows = c.execute("SELECT bot_token FROM user_bots WHERE status='active'").fetchall()
    for (tk,) in rows:
        try: start_child_bot(tk)
        except Exception as e: log.warning("Bot con: %s", e)
        time.sleep(0.2)
    log.info("Đã khởi động %d bot con", len(rows))

# ══════════════════════════ UI ══════════════════════════
def fmt(n): return f"{int(n):,}".replace(",", ".")

def back_markup(cb="menu_back"):
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🔙 Quay Lại", callback_data=cb))

def main_menu_keyboard(uid=None):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("👤 Tài khoản", callback_data="menu_profile"),
          types.InlineKeyboardButton("🛒 Cửa Hàng", callback_data="shop_home"))
    m.add(types.InlineKeyboardButton("📥 Tải TikTok", callback_data="menu_tiktok_guide"),
          types.InlineKeyboardButton("🌐 Proxy của tôi", callback_data="proxy_my"))
    m.add(types.InlineKeyboardButton(f"🤖 Tạo Bot ({CREATE_BOT_FEE//1000}k)", callback_data="menu_create_bot"),
          types.InlineKeyboardButton("💰 Nạp tiền", callback_data="menu_deposit"))
    m.add(types.InlineKeyboardButton("❤️ Donate", callback_data="menu_donate"),
          types.InlineKeyboardButton("🎛️ Hỗ trợ", callback_data="menu_support"))
    if uid == ADMIN_ID:
        m.add(types.InlineKeyboardButton("👑 ADMIN PANEL", callback_data="adm_panel"))
    return m

def home_text(u, is_admin=False):
    title    = setting_get("home_title", "🚀 HỆ THỐNG BOT ĐA NĂNG")
    subtitle = setting_get("home_subtitle", "TikTok • Data 4G • Proxy • AI")
    footer   = setting_get("footer_note", "")
    base = (
        f"<b>{html.escape(title)}</b>\n"
        f"<i>{html.escape(subtitle)}</i>\n\n<blockquote>"
        f"🤖 <b>Bot:</b> {BOT_USERNAME}\n"
        f"👑 <b>Admin:</b> {ADMIN_USERNAME}\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>Tổng nạp:</b> {fmt(u['total'])}đ\n"
        f"💰 <b>Tháng này:</b> {fmt(u['month'])}đ\n"
        f"🏦 <b>Số dư:</b> {fmt(u['balance'])}đ</blockquote>\n\n"
        "🎯 <b>Bạn có thể:</b>\n"
        "• 💬 <b>Chat AI</b> — nhắn tin bất kỳ\n"
        "• 📥 Tải TikTok không logo + MP3\n"
        "• 🛒 Mua Data 4G / VPN / Proxy\n"
        "• 🤖 Tạo bot riêng (20k)"
    )
    if is_admin:
        base += "\n\n👑 <b>Bạn là ADMIN</b> — bấm <b>ADMIN PANEL</b> để quản lý"
    if footer:
        base += f"\n\n<i>{html.escape(footer)}</i>"
    return base

def shop_home_markup():
    cats = shop_categories()
    m = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(f"📂 {c}", callback_data=f"shop_cat|{c}") for c in cats[:10]]
    if btns: m.add(*btns)
    m.add(types.InlineKeyboardButton("🔥 Bán chạy", callback_data="shop_top"),
          types.InlineKeyboardButton("🛍 Đơn của tôi", callback_data="shop_myorders"))
    m.add(types.InlineKeyboardButton("🌐 Proxy của tôi", callback_data="proxy_my"),
          types.InlineKeyboardButton("🔙 Menu Chính", callback_data="menu_back"))
    return m

def shop_home_text():
    prods = shop_list()
    title = setting_get("shop_title", "🛒 CỬA HÀNG DATA / VPN / PROXY")
    return (f"<b>{html.escape(title)}</b>\n\n<blockquote>"
            f"📦 Có <b>{len(prods)}</b> sản phẩm đang bán\n"
            f"💰 Thanh toán bằng số dư ví\n"
            f"📱 Viettel • VinaPhone • MobiFone</blockquote>\n\n"
            f"👉 Chọn <b>danh mục</b> hoặc xem <b>bán chạy</b>:")

def product_detail_text(p):
    stock_txt = "♾️ Vô hạn" if p["stock"] < 0 else ("❌ Hết hàng" if p["stock"] == 0 else f"📦 Còn {p['stock']}")
    return (f"<b>📦 {html.escape(p['name'])}</b>\n\n<blockquote>"
            f"{html.escape(p['description'][:500])}\n\n"
            f"📂 Danh mục: <b>{html.escape(p['category'])}</b>\n"
            f"💵 Giá: <b>{fmt(p['price'])}đ</b>\n"
            f"{stock_txt}  |  🔥 Đã bán: <b>{p['sold']}</b></blockquote>")

def product_markup(pid, stock):
    m = types.InlineKeyboardMarkup(row_width=1)
    if stock != 0:
        m.add(types.InlineKeyboardButton("🛒 Mua Ngay", callback_data=f"shop_buy|{pid}"))
    m.add(types.InlineKeyboardButton("🔙 Về Cửa Hàng", callback_data="shop_home"))
    return m

# ══════════════════════════ ADMIN UI HELPERS ══════════════════════════
def _show_product_manager(call, page=0):
    prods = shop_list(only_active=False, limit=200)
    per_page = 8
    total_pages = max(1, (len(prods) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = prods[page*per_page:(page+1)*per_page]

    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in chunk:
        icon = "✅" if p.get("active", 1) else "⛔"
        kb.add(types.InlineKeyboardButton(
            f"{icon} #{p['id']} {p['name'][:35]} — {fmt(p['price'])}đ",
            callback_data=f"adm_prod_view|{p['id']}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm_prod_page|{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm_prod_page|{page+1}"))
    if nav: kb.row(*nav)

    kb.add(types.InlineKeyboardButton("🔙 Admin Panel", callback_data="adm_panel"))

    _safe_show(call,
        f"<b>🛍️ QUẢN LÝ SẢN PHẨM</b>\n\n"
        f"📦 Tổng: <b>{len(prods)}</b> sản phẩm\n"
        f"Trang <b>{page+1}/{total_pages}</b>\n\n"
        f"👇 Bấm sản phẩm để <b>sửa / xóa / bật-tắt</b>:\n\n"
        f"💡 Thêm SP mới: <code>/addproduct Tên | giá | danh_mục | dtype | data | mô_tả</code>", kb)


def _show_product_detail_admin(call, pid, note=""):
    p = shop_get(pid)
    if not p:
        _safe_show(call, "❌ Sản phẩm không tồn tại.", back_markup("adm_products")); return
    stock_txt = "♾️ Vô hạn" if p["stock"] < 0 else ("Hết hàng" if p["stock"] == 0 else f"{p['stock']}")
    status = "✅ Đang bán" if p["active"] else "⛔ Đã tắt"
    txt = (
        f"<b>📦 CHI TIẾT SẢN PHẨM #{pid}</b>\n\n"
        + (f"<blockquote>{note}</blockquote>\n\n" if note else "")
        + f"<blockquote>"
        f"📝 Tên: <b>{html.escape(p['name'])}</b>\n"
        f"💵 Giá: <b>{fmt(p['price'])}đ</b>\n"
        f"📂 Danh mục: <b>{html.escape(p['category'])}</b>\n"
        f"📊 Tồn kho: <b>{stock_txt}</b>\n"
        f"🔥 Đã bán: <b>{p['sold']}</b>\n"
        f"🔖 Trạng thái: <b>{status}</b>\n"
        f"🚚 Kiểu giao: <b>{p['delivery_type']}</b>"
        f"</blockquote>\n\n"
        f"<b>Mô tả:</b>\n<i>{html.escape(p['description'][:300])}</i>"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✏️ Sửa tên", callback_data=f"adm_prod_edit|{pid}|name"),
           types.InlineKeyboardButton("💵 Sửa giá", callback_data=f"adm_prod_edit|{pid}|price"))
    kb.add(types.InlineKeyboardButton("📂 Sửa danh mục", callback_data=f"adm_prod_edit|{pid}|category"),
           types.InlineKeyboardButton("📊 Sửa tồn kho", callback_data=f"adm_prod_edit|{pid}|stock"))
    kb.add(types.InlineKeyboardButton("📝 Sửa mô tả", callback_data=f"adm_prod_edit|{pid}|description"),
           types.InlineKeyboardButton("🚚 Sửa nội dung", callback_data=f"adm_prod_edit|{pid}|delivery_data"))
    toggle_txt = "⛔ Tắt bán" if p["active"] else "✅ Bật bán"
    kb.add(types.InlineKeyboardButton(toggle_txt, callback_data=f"adm_prod_toggle|{pid}"))
    kb.add(types.InlineKeyboardButton("🗑️ XÓA SẢN PHẨM NÀY", callback_data=f"adm_prod_del|{pid}"))
    kb.add(types.InlineKeyboardButton("🔙 DS sản phẩm", callback_data="adm_products"))
    _safe_show(call, txt, kb)


def _show_proxy_list_admin(call, page=0, note=""):
    with db() as c:
        rows = c.execute("""SELECT id,ip,port,username,protocol,region,isp,status,
                            sold_to,expires_at FROM proxy_stock
                            ORDER BY status DESC, id DESC LIMIT 200""").fetchall()
    per_page = 8
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = rows[page*per_page:(page+1)*per_page]

    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in chunk:
        icon = "🟢" if r[7] == "available" else "🔴"
        tag = "(trống)" if r[7] == "available" else f"→ {r[8]}"
        kb.add(types.InlineKeyboardButton(
            f"{icon} #{r[0]} {r[1]}:{r[2]} {r[5] or ''} {tag}"[:60],
            callback_data=f"adm_proxy_view|{r[0]}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm_proxy_page|{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm_proxy_page|{page+1}"))
    if nav: kb.row(*nav)

    kb.add(types.InlineKeyboardButton("➕ Nhập thêm proxy", callback_data="adm_proxy_import"))
    kb.add(types.InlineKeyboardButton("🔙 Admin Panel", callback_data="adm_panel"))

    _safe_show(call,
        f"<b>📋 DANH SÁCH PROXY</b>\n\n"
        + (f"<blockquote>{note}</blockquote>\n\n" if note else "")
        + f"Tổng: <b>{len(rows)}</b> | Trang <b>{page+1}/{total_pages}</b>\n\n"
        f"🟢 = còn bán | 🔴 = đã bán\n"
        f"👇 Bấm để xem/xóa:", kb)


def _show_proxy_detail_admin(call, pid):
    with db() as c:
        r = c.execute("""SELECT id,ip,port,username,password,protocol,region,isp,
                         status,sold_to,expires_at,note FROM proxy_stock WHERE id=?""",
                      (pid,)).fetchone()
    if not r:
        _safe_show(call, "❌ Không tìm thấy.", back_markup("adm_proxy_list")); return
    status = "🟢 Còn bán" if r[8] == "available" else f"🔴 Đã bán → <code>{r[9]}</code>"
    txt = (
        f"<b>🌐 CHI TIẾT PROXY #{pid}</b>\n\n<blockquote>"
        f"🌐 IP: <code>{r[1]}</code>\n"
        f"🔌 Port: <code>{r[2]}</code>\n"
    )
    if r[3]: txt += f"👤 User: <code>{r[3]}</code>\n"
    if r[4]: txt += f"🔑 Pass: <code>{r[4]}</code>\n"
    txt += f"📡 Protocol: <b>{r[5]}</b>\n"
    if r[6]: txt += f"📍 Khu vực: <b>{r[6]}</b>\n"
    if r[7]: txt += f"🏢 Nhà mạng: <b>{r[7]}</b>\n"
    txt += f"📊 Trạng thái: <b>{status}</b>\n"
    if r[10]: txt += f"📅 Hết hạn: <b>{r[10]}</b>\n"
    txt += "</blockquote>"

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🗑️ XÓA PROXY NÀY", callback_data=f"adm_proxy_del|{pid}"))
    kb.add(types.InlineKeyboardButton("🔙 DS proxy", callback_data="adm_proxy_list"))
    _safe_show(call, txt, kb)


def _ui_text():
    s = setting_all()
    txt = "<b>🎨 TÙY CHỈNH GIAO DIỆN</b>\n\n"
    txt += "<i>Bấm vào mục để sửa nội dung hiển thị cho khách:</i>\n\n"
    items = [
        ("home_title",    "🏠 Tiêu đề trang chủ"),
        ("home_subtitle", "📝 Phụ đề trang chủ"),
        ("welcome_msg",   "👋 Lời chào /start"),
        ("shop_title",    "🛒 Tiêu đề cửa hàng"),
        ("support_text",  "🎛️ Nội dung hỗ trợ"),
        ("footer_note",   "🔖 Ghi chú cuối"),
    ]
    for k, label in items:
        v = (s.get(k) or "")[:60]
        txt += f"{label}\n<i>→ {html.escape(v)}</i>\n\n"
    return txt


def _ui_markup():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("🏠 Sửa tiêu đề", callback_data="adm_ui_edit|home_title"),
           types.InlineKeyboardButton("📝 Sửa phụ đề", callback_data="adm_ui_edit|home_subtitle"))
    kb.add(types.InlineKeyboardButton("👋 Sửa lời chào", callback_data="adm_ui_edit|welcome_msg"),
           types.InlineKeyboardButton("🛒 Sửa tên shop", callback_data="adm_ui_edit|shop_title"))
    kb.add(types.InlineKeyboardButton("🎛️ Sửa hỗ trợ", callback_data="adm_ui_edit|support_text"),
           types.InlineKeyboardButton("🔖 Sửa ghi chú", callback_data="adm_ui_edit|footer_note"))
    kb.add(types.InlineKeyboardButton("🔄 Khôi phục mặc định", callback_data="adm_ui_reset"))
    kb.add(types.InlineKeyboardButton("🔙 Admin Panel", callback_data="adm_panel"))
    return kb


def admin_panel_text():
    with db() as c:
        total_p = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        active_p = c.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0]
        total_u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_o = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        total_rev = c.execute("SELECT COALESCE(SUM(price),0) FROM orders").fetchone()[0]
        total_bal = c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0]
    s = proxy_stock_count()
    return (
        "<b>👑 BẢNG ĐIỀU KHIỂN ADMIN</b>\n\n<blockquote>"
        f"👥 Người dùng: <b>{total_u}</b>\n"
        f"📦 Sản phẩm: <b>{total_p}</b> (đang bán: <b>{active_p}</b>)\n"
        f"🛒 Đơn hàng: <b>{total_o}</b>\n"
        f"💰 Doanh thu: <b>{fmt(total_rev)}đ</b>\n"
        f"🏦 Tổng số dư user: <b>{fmt(total_bal)}đ</b>\n"
        f"🌐 Proxy tồn: <b>{s['available']}</b> / đã bán <b>{s['sold']}</b>"
        "</blockquote>\n\n"
        "👇 <b>Chọn chức năng bên dưới:</b>"
    )

def admin_panel_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🛍️ Quản lý sản phẩm", callback_data="adm_products"),
          types.InlineKeyboardButton("🌐 Quản lý Proxy", callback_data="adm_proxy"))
    m.add(types.InlineKeyboardButton("💰 Cấp tiền user", callback_data="adm_grant"),
          types.InlineKeyboardButton("📊 Thống kê chi tiết", callback_data="adm_stats"))
    m.add(types.InlineKeyboardButton("🎨 Đổi giao diện", callback_data="adm_ui"),
          types.InlineKeyboardButton("📣 Gửi thông báo", callback_data="adm_broadcast"))
    m.add(types.InlineKeyboardButton("💾 Sao lưu dữ liệu", callback_data="adm_export"),
          types.InlineKeyboardButton("⚙️ Cấu hình bot", callback_data="adm_config"))
    m.add(types.InlineKeyboardButton("🔙 Về Menu chính", callback_data="menu_back"))
    return m


def _safe_show(call, text, markup=None):
    cid, mid = call.message.chat.id, call.message.message_id
    if call.message.content_type == "text":
        try:
            main_bot.edit_message_text(text, cid, mid, reply_markup=markup)
            return
        except ApiTelegramException as e:
            if "not modified" in str(e): return
        except Exception: pass
    try: main_bot.delete_message(cid, mid)
    except Exception: pass
    try: main_bot.send_message(cid, text, reply_markup=markup)
    except Exception as e: log.warning("_safe_show: %s", e)

# ══════════════════════════ MAIN HANDLERS ══════════════════════════
def user_from(tg):
    return get_or_create_user(tg.id, tg.username or "", tg.first_name or "Khách")

@main_bot.message_handler(commands=["start", "menu"])
def send_welcome(m):
    user_states.pop(m.from_user.id, None)
    u = user_from(m.from_user)
    is_admin = m.from_user.id == ADMIN_ID
    welcome = setting_get("welcome_msg", "")
    if welcome:
        try: main_bot.send_message(m.chat.id, html.escape(welcome))
        except Exception: pass
    main_bot.send_message(m.chat.id, home_text(u, is_admin),
                          reply_markup=main_menu_keyboard(m.from_user.id))

def show(call, text, markup=None):
    cid, mid = call.message.chat.id, call.message.message_id
    if call.message.content_type == "text":
        try: main_bot.edit_message_text(text, cid, mid, reply_markup=markup); return
        except ApiTelegramException as e:
            if "not modified" in str(e): return
        except Exception: pass
    try: main_bot.delete_message(cid, mid)
    except Exception: pass
    main_bot.send_message(cid, text, reply_markup=markup)

def send_qr(call, amount, memo, title, note):
    params = {"acc": ACCOUNT_NO, "bank": BANK_NAME, "template": "compact", "des": memo}
    if amount: params["amount"] = amount
    qr = "https://qr.sepay.vn/img?" + urllib.parse.urlencode(params)
    caption = (f"<b>{title}</b>\n\n<blockquote>"
               f"🏦 Ngân hàng: <b>{BANK_NAME}</b>\n"
               f"💳 STK: <code>{ACCOUNT_NO}</code>\n"
               f"👤 Chủ TK: <b>{ACCOUNT_NAME}</b>\n"
               + (f"💵 Số tiền: <b>{fmt(amount)}đ</b>\n" if amount else "💵 Số tiền: <b>tùy bạn</b>\n")
               + f"📝 Nội dung: <code>{memo}</code></blockquote>\n\n{note}")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔄 Mở ảnh QR", url=qr),
           types.InlineKeyboardButton("🔙 Quay Lại Menu", callback_data="menu_back"))
    try: main_bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception: pass
    try: main_bot.send_photo(call.message.chat.id, qr, caption=caption, reply_markup=kb)
    except Exception as e:
        log.warning("QR lỗi: %s", e)
        main_bot.send_message(call.message.chat.id, caption, reply_markup=kb)

# ══════════════════════════ CALLBACK LISTENER ══════════════════════════
@main_bot.callback_query_handler(func=lambda c: (c.data or "") == "noop")
def _noop(c):
    try: main_bot.answer_callback_query(c.id, "Trang hiện tại")
    except Exception: pass

@main_bot.callback_query_handler(func=lambda c: True)
def callback_listener(call):
    data = call.data or ""
    if data == "noop": return
    uid = call.from_user.id
    is_admin = uid == ADMIN_ID
    u = user_from(call.from_user)

    if not data.startswith(("menu_", "dep|", "shop_", "proxy_", "adm_", "dl_")):
        try: main_bot.answer_callback_query(call.id)
        except Exception: pass
        return

    try: main_bot.answer_callback_query(call.id)
    except Exception: pass

    # ═══════════ ADMIN ═══════════
    if data == "adm_panel":
        if not is_admin: return
        show(call, admin_panel_text(), admin_panel_markup())

    elif data == "adm_grant":
        if not is_admin: return
        user_states[uid] = "ADMIN_WAITING_GRANT"
        show(call, "<b>💰 CẤP TIỀN CHO USER</b>\n\n"
                   "Gửi tin theo cú pháp:\n"
                   "<code>&lt;user_id hoặc @username&gt; &lt;số_tiền&gt;</code>\n\n"
                   "Ví dụ:\n"
                   "<code>123456789 50000</code>\n"
                   "<code>@nguyenvana 100000</code>\n\n"
                   "💡 Nhập số âm để <b>trừ tiền</b>.\n"
                   "Gõ /cancel để hủy.", back_markup("adm_panel"))

    elif data == "adm_stats":
        if not is_admin: return
        with db() as c:
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            bots  = c.execute("SELECT COUNT(*) FROM user_bots WHERE status='active'").fetchone()[0]
            dep   = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='deposit'").fetchone()[0]
            orders = c.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders").fetchone()
            top_u = c.execute("""SELECT user_id, balance FROM users
                                 ORDER BY balance DESC LIMIT 5""").fetchall()
        s = proxy_stock_count()
        txt = (f"<b>📊 THỐNG KÊ CHI TIẾT</b>\n\n<blockquote>"
               f"👥 Users: <b>{users}</b>\n"
               f"🤖 Bot con: <b>{bots}</b>\n"
               f"💰 Tổng nạp: <b>{fmt(dep)}đ</b>\n"
               f"🛒 Đơn hàng: <b>{orders[0]}</b> – <b>{fmt(orders[1])}đ</b>\n"
               f"🌐 Proxy tồn: <b>{s['available']}</b> / đã bán <b>{s['sold']}</b>\n"
               f"💾 DB: <code>{html.escape(DB_PATH)}</code>"
               f"</blockquote>\n\n<b>🏆 Top 5 user giàu nhất:</b>\n")
        for uu, bal in top_u:
            txt += f"• <code>{uu}</code> – <b>{fmt(bal)}đ</b>\n"
        show(call, txt, back_markup("adm_panel"))

    elif data == "adm_broadcast":
        if not is_admin: return
        user_states[uid] = "ADMIN_WAITING_BROADCAST"
        show(call, "<b>📣 GỬI THÔNG BÁO</b>\n\n"
                   "Gửi tin nhắn bạn muốn gửi tới <b>tất cả user</b>.\n"
                   "Gõ /cancel để hủy.", back_markup("adm_panel"))

    elif data == "adm_products":
        if not is_admin: return
        _show_product_manager(call, page=0)

    elif data.startswith("adm_prod_page|"):
        if not is_admin: return
        _show_product_manager(call, page=int(data.split("|")[1]))

    elif data.startswith("adm_prod_view|"):
        if not is_admin: return
        _show_product_detail_admin(call, int(data.split("|")[1]))

    elif data.startswith("adm_prod_del|"):
        if not is_admin: return
        pid = int(data.split("|")[1])
        p = shop_get(pid)
        if not p:
            _safe_show(call, "❌ Sản phẩm không tồn tại.", back_markup("adm_products")); return
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ XÁC NHẬN XÓA", callback_data=f"adm_prod_delok|{pid}"),
               types.InlineKeyboardButton("❌ Hủy", callback_data=f"adm_prod_view|{pid}"))
        _safe_show(call,
            f"<b>⚠️ XÁC NHẬN XÓA</b>\n\n"
            f"Bạn có chắc muốn xóa vĩnh viễn:\n<b>{html.escape(p['name'])}</b>\n\n"
            f"❌ Thao tác này KHÔNG thể hoàn tác!", kb)

    elif data.startswith("adm_prod_delok|"):
        if not is_admin: return
        pid = int(data.split("|")[1])
        p = shop_get(pid)
        if p:
            product_delete(pid)
            _safe_show(call,
                f"✅ <b>ĐÃ XÓA SẢN PHẨM</b>\n\n📦 {html.escape(p['name'])}",
                types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 DS sản phẩm", callback_data="adm_products")))
        else:
            _safe_show(call, "❌ Đã bị xóa trước đó.", back_markup("adm_products"))

    elif data.startswith("adm_prod_toggle|"):
        if not is_admin: return
        pid = int(data.split("|")[1])
        new = product_toggle(pid)
        if new is None:
            _safe_show(call, "❌ Không tìm thấy.", back_markup("adm_products")); return
        status = "✅ Đang bán" if new else "⛔ Đã tắt"
        _show_product_detail_admin(call, pid, note=f"Trạng thái: {status}")

    elif data.startswith("adm_prod_edit|"):
        if not is_admin: return
        parts_d = data.split("|")
        pid = int(parts_d[1])
        field = parts_d[2]
        user_states[uid] = f"ADMIN_EDIT_PRODUCT|{pid}|{field}"
        field_vn = {"name": "Tên sản phẩm", "price": "Giá (VNĐ)",
                    "description": "Mô tả", "category": "Danh mục",
                    "stock": "Tồn kho (-1 = vô hạn)",
                    "delivery_data": "Nội dung giao hàng"}.get(field, field)
        p = shop_get(pid)
        cur_val = ""
        if p:
            if field == "price": cur_val = fmt(p["price"]) + "đ"
            elif field == "stock": cur_val = "Vô hạn" if p["stock"] < 0 else str(p["stock"])
            else: cur_val = str(p.get(field, ""))[:300]
        _safe_show(call,
            f"<b>✏️ SỬA: {field_vn}</b>\n\n"
            f"<b>Giá trị hiện tại:</b>\n<blockquote>{html.escape(cur_val)}</blockquote>\n\n"
            f"Nhập giá trị mới vào ô chat.\n"
            f"Gõ /cancel để hủy.",
            back_markup(f"adm_prod_view|{pid}"))

    elif data == "adm_proxy":
        if not is_admin: return
        s = proxy_stock_count()
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("➕ Nhập proxy", callback_data="adm_proxy_import"),
               types.InlineKeyboardButton("📋 DS proxy", callback_data="adm_proxy_list"))
        kb.add(types.InlineKeyboardButton("🗑️ Xóa proxy hết hạn", callback_data="adm_proxy_clean"),
               types.InlineKeyboardButton("🔙 Admin Panel", callback_data="adm_panel"))
        show(call,
            f"<b>🌐 QUẢN LÝ KHO PROXY</b>\n\n<blockquote>"
            f"✅ Còn bán: <b>{s['available']}</b>\n"
            f"💰 Đã bán: <b>{s['sold']}</b>\n"
            f"📊 Tổng: <b>{s['total']}</b></blockquote>\n\n"
            "👇 Chọn thao tác:", kb)

    elif data == "adm_proxy_import":
        if not is_admin: return
        user_states[uid] = "ADMIN_IMPORT_PROXY"
        _safe_show(call,
            "<b>📥 NHẬP PROXY VÀO KHO</b>\n\n"
            "Gửi danh sách proxy, mỗi dòng 1 proxy theo cú pháp:\n"
            "<code>ip:port:user:pass | Khu vực | Nhà mạng | Giao thức</code>\n\n"
            "<b>Ví dụ:</b>\n"
            "<code>113.22.55.10:8080:user1:pass123 | Hà Nội | Viettel | HTTP</code>\n"
            "<code>27.72.99.5:3128:: | HCM | Vinaphone | SOCKS5</code>\n\n"
            "💡 Có thể bỏ trống user/pass, khu vực, nhà mạng.\n"
            "Gõ /cancel để hủy.", back_markup("adm_proxy"))

    elif data == "adm_proxy_list":
        if not is_admin: return
        _show_proxy_list_admin(call, page=0)

    elif data.startswith("adm_proxy_page|"):
        if not is_admin: return
        _show_proxy_list_admin(call, page=int(data.split("|")[1]))

    elif data.startswith("adm_proxy_view|"):
        if not is_admin: return
        _show_proxy_detail_admin(call, int(data.split("|")[1]))

    elif data.startswith("adm_proxy_del|"):
        if not is_admin: return
        pid = int(data.split("|")[1])
        with db() as c:
            c.execute("DELETE FROM proxy_stock WHERE id=?", (pid,))
        _show_proxy_list_admin(call, page=0, note=f"✅ Đã xóa proxy #{pid}")

    elif data == "adm_proxy_clean":
        if not is_admin: return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db() as c:
            cur = c.execute("""DELETE FROM proxy_stock
                               WHERE status='sold' AND expires_at != '' AND expires_at < ?""",
                            (now,))
            n = cur.rowcount
        show(call, f"✅ Đã xóa <b>{n}</b> proxy hết hạn.", back_markup("adm_proxy"))

    elif data == "adm_ui":
        if not is_admin: return
        show(call, _ui_text(), _ui_markup())

    elif data.startswith("adm_ui_edit|"):
        if not is_admin: return
        key = data.split("|", 1)[1]
        user_states[uid] = f"ADMIN_EDIT_SETTING|{key}"
        key_vn = {"home_title": "Tiêu đề trang chủ", "home_subtitle": "Phụ đề trang chủ",
                  "welcome_msg": "Lời chào /start", "shop_title": "Tiêu đề cửa hàng",
                  "support_text": "Nội dung hỗ trợ", "footer_note": "Ghi chú cuối trang"}.get(key, key)
        cur_val = setting_get(key, "")
        show(call,
            f"<b>🎨 SỬA GIAO DIỆN</b>\n\n"
            f"📝 Mục: <b>{key_vn}</b>\n\n"
            f"<b>Giá trị hiện tại:</b>\n<blockquote>{html.escape(cur_val[:300])}</blockquote>\n\n"
            f"Nhập nội dung mới.\nHỗ trợ emoji, không hỗ trợ HTML.\n"
            f"Gõ /cancel để hủy.", back_markup("adm_ui"))

    elif data == "adm_ui_reset":
        if not is_admin: return
        defaults = {
            "home_title":    "🚀 HỆ THỐNG BOT ĐA NĂNG",
            "home_subtitle": "TikTok • Data 4G • Proxy • AI",
            "welcome_msg":   "Chào mừng bạn! Nhắn tin bất kỳ để chat với AI, gửi link TikTok để tải video.",
            "shop_title":    "🛒 CỬA HÀNG DATA / VPN / PROXY",
            "support_text":  "Nhắn admin để được hỗ trợ nhanh nhất!",
            "footer_note":   "Cảm ơn bạn đã sử dụng dịch vụ! ❤️",
        }
        for k, v in defaults.items(): setting_set(k, v)
        show(call, "✅ Đã khôi phục giao diện mặc định.", back_markup("adm_ui"))

    elif data == "adm_config":
        if not is_admin: return
        show(call,
            "<b>⚙️ CẤU HÌNH BOT</b>\n\n<blockquote>"
            f"👑 Admin ID: <code>{ADMIN_ID}</code>\n"
            f"🤖 Bot: {BOT_USERNAME}\n"
            f"🏦 Ngân hàng: <b>{BANK_NAME}</b>\n"
            f"💳 STK: <code>{ACCOUNT_NO}</code>\n"
            f"👤 Chủ TK: <b>{ACCOUNT_NAME}</b>\n"
            f"💰 Phí tạo bot: <b>{fmt(CREATE_BOT_FEE)}đ</b>\n"
            f"⏱ Cooldown AI: <b>{AI_COOLDOWN}s</b>"
            "</blockquote>\n\n"
            "💡 Đổi cấu hình → sửa biến môi trường trên Render rồi deploy lại.",
            back_markup("adm_panel"))

    elif data == "adm_export":
        if not is_admin: return
        try:
            main_bot.send_document(uid, open(DB_PATH, "rb"),
                caption=f"💾 Sao lưu DB — {datetime.now():%Y-%m-%d %H:%M}")
        except Exception as e:
            main_bot.send_message(uid, f"❌ Lỗi: {e}")

    # ═══════════ MAIN MENU ═══════════
    elif data == "menu_profile":
        show(call,
            f"<b>📊 THÔNG TIN TÀI KHOẢN</b>\n\n<blockquote>"
            f"🆔 <b>ID:</b> <code>{uid}</code>\n"
            f"👤 <b>Họ tên:</b> {html.escape(call.from_user.first_name or 'Khách')}\n"
            f"🏦 <b>Số dư:</b> {fmt(u['balance'])}đ\n"
            f"🏆 <b>Tổng nạp:</b> {fmt(u['total'])}đ\n"
            f"📅 <b>Tháng này:</b> {fmt(u['month'])}đ</blockquote>", back_markup())

    elif data == "menu_create_bot":
        if not is_admin and u["balance"] < CREATE_BOT_FEE:
            miss = CREATE_BOT_FEE - u["balance"]
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("💳 Nạp Tiền Ngay", callback_data="menu_deposit"),
                   types.InlineKeyboardButton("🔙 Quay Lại", callback_data="menu_back"))
            show(call, f"<b>⚠️ TẠO BOT TỰ ĐỘNG</b>\n\n💰 Phí: {fmt(CREATE_BOT_FEE)}đ\n"
                       f"❌ Bạn thiếu: <b>{fmt(miss)}đ</b>", kb)
        else:
            user_states[uid] = "WAITING_BOT_TOKEN"
            show(call, f"<b>🤖 TẠO BOT TỰ ĐỘNG</b>\n\n"
                       f"💰 Phí {fmt(CREATE_BOT_FEE)}đ (trừ sau khi kích hoạt)\n\n"
                       "1️⃣ Mở @BotFather → /newbot\n"
                       "2️⃣ Copy Token và gửi vào đây:", back_markup())

    elif data == "menu_tiktok_guide":
        show(call, "<b>📥 TẢI TIKTOK KHÔNG LOGO</b>\n\n<blockquote>"
                   "Gửi link TikTok vào khung chat → bot tự trả video không logo.\n"
                   "🎵 Bấm nút <b>Tải nhạc MP3</b> dưới video.\n"
                   "📸 Slideshow ảnh cũng được hỗ trợ!</blockquote>", back_markup())

    elif data == "menu_deposit":
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(*[types.InlineKeyboardButton(f"{a//1000}k", callback_data=f"dep|{a}")
                 for a in (20000, 30000, 50000, 100000, 200000, 500000)])
        kb.add(types.InlineKeyboardButton("✏️ Số tiền khác", callback_data="dep|0"),
               types.InlineKeyboardButton("🔙 Quay Lại", callback_data="menu_back"))
        show(call, "<b>💰 NẠP TIỀN TỰ ĐỘNG</b>\n\nChọn số tiền:", kb)

    elif data.startswith("dep|"):
        amount = int(data.split("|")[1])
        send_qr(call, amount, f"NAP{uid}", "💰 NẠP TIỀN TỰ ĐỘNG",
                "⚡ Chuyển <b>đúng nội dung</b>, số dư tự cộng sau 10–30 giây.")

    elif data == "menu_donate":
        send_qr(call, 0, f"DONATE{uid}", "❤️ DONATE ỦNG HỘ", "🙏 Cảm ơn bạn!")

    elif data == "menu_support":
        txt = setting_get("support_text", "Nhắn admin để được hỗ trợ!")
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("💬 Nhắn Admin",
                url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}"),
               types.InlineKeyboardButton("🔙 Quay Lại", callback_data="menu_back"))
        show(call, f"<b>🎛️ HỖ TRỢ</b>\n\n{html.escape(txt)}\n\n👑 Admin: {ADMIN_USERNAME}", kb)

    elif data == "menu_back":
        user_states.pop(uid, None)
        show(call, home_text(u, is_admin), main_menu_keyboard(uid))

    # ═══════════ SHOP ═══════════
    elif data == "shop_home":
        show(call, shop_home_text(), shop_home_markup())

    elif data.startswith("shop_cat|"):
        cat = data.split("|", 1)[1]
        prods = shop_list(cat)
        if not prods:
            show(call, f"<b>📂 {html.escape(cat)}</b>\n\nChưa có sản phẩm nào.",
                 types.InlineKeyboardMarkup().add(
                     types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for p in prods[:20]:
            stock_tag = "" if p["stock"] != 0 else " (hết)"
            kb.add(types.InlineKeyboardButton(
                f"📦 {p['name'][:40]} – {fmt(p['price'])}đ{stock_tag}",
                callback_data=f"shop_view|{p['id']}"))
        kb.add(types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home"))
        show(call, f"<b>📂 DANH MỤC: {html.escape(cat)}</b>\n\nCó <b>{len(prods)}</b> sản phẩm:", kb)

    elif data == "shop_top":
        prods = shop_top(8)
        if not prods:
            show(call, "🔥 Chưa có sản phẩm nào bán.",
                 types.InlineKeyboardMarkup().add(
                     types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for p in prods:
            kb.add(types.InlineKeyboardButton(
                f"🔥 {p['name'][:40]} – {fmt(p['price'])}đ (đã bán {p['sold']})",
                callback_data=f"shop_view|{p['id']}"))
        kb.add(types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home"))
        show(call, "<b>🔥 SẢN PHẨM BÁN CHẠY</b>", kb)

    elif data.startswith("shop_view|"):
        pid = int(data.split("|", 1)[1])
        p = shop_get(pid)
        if not p:
            show(call, "❌ Sản phẩm không tồn tại.",
                 types.InlineKeyboardMarkup().add(
                     types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return
        show(call, product_detail_text(p), product_markup(pid, p["stock"]))

    elif data.startswith("shop_buy|"):
        pid = int(data.split("|", 1)[1])
        p = shop_get(pid)
        if not p:
            show(call, "❌ Sản phẩm không tồn tại.",
                 types.InlineKeyboardMarkup().add(
                     types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return
        if u["balance"] < p["price"]:
            miss = p["price"] - u["balance"]
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("💳 Nạp Tiền Ngay", callback_data="menu_deposit"),
                   types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home"))
            show(call, f"<b>⚠️ SỐ DƯ KHÔNG ĐỦ</b>\n\n"
                       f"💰 Cần: {fmt(p['price'])}đ\n"
                       f"🏦 Bạn có: {fmt(u['balance'])}đ\n"
                       f"❌ Thiếu: <b>{fmt(miss)}đ</b>", kb)
            return

        try: main_bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass

        # ─── PROXY ───
        if p["delivery_type"] == "proxy":
            ok, err, info = proxy_buy(uid, pid)
            if not ok:
                main_bot.send_message(call.message.chat.id, f"❌ {err}",
                    reply_markup=types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
                return
            main_bot.send_message(call.message.chat.id,
                f"<b>🎉 ĐẶT HÀNG PROXY THÀNH CÔNG!</b>\n\n"
                f"🏦 Số dư còn: <b>{fmt(u['balance'] - info['price'])}đ</b>")
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("🌐 Proxy của tôi", callback_data="proxy_my"))
            line = (f"{info['protocol'].lower()}://{info['username']}:{info['password']}@{info['ip']}:{info['port']}"
                    if info['username'] else f"{info['protocol'].lower()}://{info['ip']}:{info['port']}")
            txt = (f"<b>📦 {html.escape(info['name'])}</b>\n\n<blockquote>"
                   f"⏱ Hạn: <b>{info['days']} ngày</b>\n"
                   f"📅 Hết hạn: <b>{info['expires_at']}</b>\n"
                   f"🌐 IP: <code>{info['ip']}</code>\n"
                   f"🔌 Port: <code>{info['port']}</code>\n")
            if info['username']: txt += f"👤 User: <code>{info['username']}</code>\n"
            if info['password']: txt += f"🔑 Pass: <code>{info['password']}</code>\n"
            txt += f"📡 Protocol: <b>{info['protocol']}</b>\n"
            if info['region']: txt += f"📍 Region: <b>{info['region']}</b>\n"
            if info['isp']:    txt += f"🏢 ISP: <b>{info['isp']}</b>\n"
            txt += f"</blockquote>\n\n<b>📖 Chuỗi kết nối:</b>\n<code>{html.escape(line)}</code>"
            main_bot.send_message(call.message.chat.id, txt, reply_markup=kb)
            try:
                main_bot.send_message(ADMIN_ID,
                    f"💰 <b>ĐƠN PROXY MỚI</b>\n"
                    f"👤 <code>{uid}</code> ({html.escape(call.from_user.first_name or '')})\n"
                    f"📦 {html.escape(info['name'])}\n"
                    f"💵 {fmt(info['price'])}đ\n"
                    f"🌐 <code>{info['ip']}:{info['port']}</code>")
            except Exception: pass
            return

        # ─── SẢN PHẨM THƯỜNG ───
        ok, res = shop_purchase(uid, pid)
        if not ok:
            main_bot.send_message(call.message.chat.id, f"❌ Mua thất bại: {res}",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return

        with db() as c:
            row = c.execute("SELECT id FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1",
                            (uid,)).fetchone()
        order_id = row[0] if row else 0

        kb_user = types.InlineKeyboardMarkup(row_width=1)
        kb_user.add(types.InlineKeyboardButton(
            "💬 Liên hệ Admin nhận gói",
            url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}"))
        main_bot.send_message(call.message.chat.id,
            f"<b>🎉 ĐẶT HÀNG THÀNH CÔNG!</b>\n\n<blockquote>"
            f"🧾 Mã đơn: <code>#{order_id}</code>\n"
            f"📦 Sản phẩm: <b>{html.escape(res['name'])}</b>\n"
            f"💵 Giá: <b>{fmt(res['price'])}đ</b>\n"
            f"🏦 Số dư còn: <b>{fmt(u['balance'] - res['price'])}đ</b>"
            f"</blockquote>\n\n"
            f"<b>⚠️ VUI LÒNG LIÊN HỆ ADMIN ĐỂ NHẬN GÓI</b>\n\n"
            f"👑 Admin: {ADMIN_USERNAME}\n"
            f"📌 Gửi kèm mã đơn <code>#{order_id}</code> để được xử lý nhanh!",
            reply_markup=kb_user)
        try:
            uname = call.from_user.username
            uname_str = f"@{uname}" if uname else "(không có username)"
            main_bot.send_message(ADMIN_ID,
                f"<b>🔔 ĐƠN HÀNG MỚI</b>\n\n<blockquote>"
                f"🧾 Mã đơn: <code>#{order_id}</code>\n"
                f"👤 Khách: <a href='tg://user?id={uid}'>{html.escape(call.from_user.first_name or 'Khách')}</a>\n"
                f"🆔 ID: <code>{uid}</code>\n"
                f"📛 Username: {html.escape(uname_str)}\n"
                f"📦 Sản phẩm: <b>{html.escape(res['name'])}</b>\n"
                f"💵 Giá: <b>{fmt(res['price'])}đ</b>"
                f"</blockquote>")
        except Exception as e:
            log.warning("Báo admin: %s", e)

    elif data == "shop_myorders":
        rows = shop_myorders(uid, 10)
        if not rows:
            show(call, "🛍 Bạn chưa có đơn hàng nào.",
                 types.InlineKeyboardMarkup().add(
                     types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return
        txt = "<b>🛍 ĐƠN HÀNG GẦN ĐÂY</b>\n\n<blockquote>"
        for r in rows:
            txt += f"• #{r[0]} {html.escape(r[1])} – {fmt(r[2])}đ\n  <i>{r[3]}</i>\n"
        txt += "</blockquote>"
        show(call, txt, back_markup("shop_home"))

    # ═══════════ PROXY ═══════════
    elif data == "proxy_my":
        rows = proxy_my_list(uid)
        if not rows:
            show(call, "<b>🌐 PROXY CỦA TÔI</b>\n\nBạn chưa mua proxy nào.\n\n"
                       "👉 Vào Cửa hàng → chọn mục <b>Proxy</b> để mua.",
                 types.InlineKeyboardMarkup(row_width=1).add(
                     types.InlineKeyboardButton("🛒 Vào Cửa Hàng", callback_data="shop_home"),
                     types.InlineKeyboardButton("🔙 Menu Chính", callback_data="menu_back")))
            return
        active  = [r for r in rows if r["status"] == "active"]
        expired = [r for r in rows if r["status"] == "expired"]
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in rows[:10]:
            icon = "🟢" if r["status"] == "active" else "🔴"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {r['ip']}:{r['port']} ({r['protocol']})",
                callback_data=f"proxy_view|{r['id']}"))
        kb.add(types.InlineKeyboardButton("🔙 Menu Chính", callback_data="menu_back"))
        show(call,
            f"<b>🌐 PROXY CỦA TÔI</b>\n\n<blockquote>"
            f"🟢 Còn hạn: <b>{len(active)}</b>\n"
            f"🔴 Hết hạn: <b>{len(expired)}</b>\n"
            f"📦 Tổng: <b>{len(rows)}</b></blockquote>\n\n👉 Bấm vào proxy để xem chi tiết:", kb)

    elif data.startswith("proxy_view|"):
        pid = int(data.split("|", 1)[1])
        with db() as c:
            r = c.execute("""SELECT ip,port,username,password,protocol,region,isp,
                             expires_at FROM proxy_stock WHERE id=? AND sold_to=?""",
                          (pid, uid)).fetchone()
        if not r:
            show(call, "❌ Không tìm thấy proxy.", back_markup("proxy_my")); return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        is_active = r[7] and r[7] > now
        status_txt = "🟢 Còn hạn" if is_active else "🔴 Đã hết hạn"
        line = (f"{r[4].lower()}://{r[2]}:{r[3]}@{r[0]}:{r[1]}" if r[2]
                else f"{r[4].lower()}://{r[0]}:{r[1]}")
        txt = (f"<b>🌐 CHI TIẾT PROXY</b>\n\n<blockquote>"
               f"Trạng thái: <b>{status_txt}</b>\n"
               f"📅 Hết hạn: <b>{r[7]}</b>\n"
               f"🌐 IP: <code>{r[0]}</code>\n"
               f"🔌 Port: <code>{r[1]}</code>\n")
        if r[2]: txt += f"👤 User: <code>{r[2]}</code>\n"
        if r[3]: txt += f"🔑 Pass: <code>{r[3]}</code>\n"
        txt += f"📡 Protocol: <b>{r[4]}</b>\n"
        if r[5]: txt += f"📍 Region: <b>{r[5]}</b>\n"
        if r[6]: txt += f"🏢 ISP: <b>{r[6]}</b>\n"
        txt += f"</blockquote>\n\n<b>📖 Chuỗi kết nối:</b>\n<code>{html.escape(line)}</code>"
        show(call, txt, back_markup("proxy_my"))

# ══════════════════════════ STATE HANDLERS ══════════════════════════
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")

@main_bot.message_handler(commands=["cancel"])
def cmd_cancel(m):
    user_states.pop(m.from_user.id, None)
    main_bot.send_message(m.chat.id, "✅ Đã hủy. Bấm /menu để mở menu.")

@main_bot.message_handler(
    func=lambda m: m.from_user is not None
    and user_states.get(m.from_user.id) == "WAITING_BOT_TOKEN"
    and bool(m.text) and not m.text.startswith("/")
)
def handle_bot_token_input(message):
    uid = message.from_user.id
    token = message.text.strip()
    is_admin = uid == ADMIN_ID
    try: main_bot.delete_message(message.chat.id, message.message_id)
    except Exception: pass
    def say(text): main_bot.send_message(message.chat.id, text, reply_markup=back_markup())
    if not TOKEN_RE.match(token):
        say("❌ <b>Token không đúng định dạng!</b>"); return
    if token == BOT_TOKEN or token_exists(token):
        say("❌ Token này đã được dùng rồi!"); return
    try: info = telebot.TeleBot(token).get_me()
    except Exception: say("❌ <b>Token không hợp lệ!</b>"); return
    u = user_from(message.from_user)
    if not is_admin:
        with db() as c:
            cur = c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                            (CREATE_BOT_FEE, uid, CREATE_BOT_FEE))
            ok = cur.rowcount == 1
        if not ok:
            user_states.pop(uid, None)
            say(f"❌ Số dư không đủ ({fmt(u['balance'])}đ). Nạp thêm nhé!"); return
    try:
        save_user_bot(uid, token, info.username); start_child_bot(token)
    except Exception as e:
        log.exception("Bot con lỗi: %s", e)
        if not is_admin:
            with db() as c:
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (CREATE_BOT_FEE, uid))
        say("❌ Kích hoạt thất bại, tiền đã hoàn lại."); return
    user_states.pop(uid, None)
    paid = "Miễn phí (admin)" if is_admin else f"-{fmt(CREATE_BOT_FEE)}đ"
    say(f"<b>🚀 KÍCH HOẠT THÀNH CÔNG!</b>\n\n🤖 Bot: @{info.username}\n💸 Phí: {paid}\n\nBot đã chạy!")

@main_bot.message_handler(
    func=lambda m: m.from_user is not None and m.from_user.id == ADMIN_ID
    and user_states.get(m.from_user.id) == "ADMIN_WAITING_GRANT"
    and bool(m.text) and not m.text.startswith("/")
)
def admin_grant_input(m):
    parts = m.text.strip().split()
    if len(parts) < 2:
        main_bot.reply_to(m, "❌ Cú pháp: <code>&lt;uid/@username&gt; &lt;số_tiền&gt;</code>"); return
    target, amount_str = parts[0], parts[1]
    try: amount = int(amount_str)
    except Exception:
        main_bot.reply_to(m, "❌ Số tiền không hợp lệ!"); return
    if target.startswith("@"):
        with db() as c:
            row = c.execute("SELECT user_id FROM users WHERE username=?", (target[1:],)).fetchone()
        if not row: main_bot.reply_to(m, "❌ Không tìm thấy user"); return
        uid = row[0]
    else:
        try: uid = int(target)
        except Exception:
            main_bot.reply_to(m, "❌ ID không hợp lệ!"); return
    admin_add_money(uid, amount)
    u = get_or_create_user(uid, "", "")
    user_states.pop(m.from_user.id, None)
    main_bot.reply_to(m, f"✅ <b>ĐÃ CẬP NHẬT SỐ DƯ</b>\n\n"
                        f"👤 User: <code>{uid}</code>\n"
                        f"💵 Thay đổi: <b>{'+' if amount >= 0 else ''}{fmt(amount)}đ</b>\n"
                        f"🏦 Số dư mới: <b>{fmt(u['balance'])}đ</b>",
                     reply_markup=back_markup("adm_panel"))
    try:
        main_bot.send_message(uid,
            f"<b>💰 SỐ DƯ ĐÃ THAY ĐỔI</b>\n\n"
            f"{'✅ Admin vừa cộng' if amount >= 0 else '⚠️ Admin vừa trừ'} "
            f"<b>{fmt(abs(amount))}đ</b>\n"
            f"🏦 Số dư hiện tại: <b>{fmt(u['balance'])}đ</b>")
    except Exception: pass

@main_bot.message_handler(
    func=lambda m: m.from_user is not None and m.from_user.id == ADMIN_ID
    and user_states.get(m.from_user.id) == "ADMIN_WAITING_BROADCAST"
    and bool(m.text) and not m.text.startswith("/")
)
def admin_broadcast_input(m):
    text = m.text
    user_states.pop(m.from_user.id, None)
    def worker():
        with db() as c:
            ids = [r[0] for r in c.execute("SELECT user_id FROM users").fetchall()]
        ok = 0
        for uid in ids:
            try: main_bot.send_message(uid, text); ok += 1
            except Exception: pass
            time.sleep(0.05)
        main_bot.send_message(m.chat.id, f"📣 Đã gửi {ok}/{len(ids)} người.")
    threading.Thread(target=worker, daemon=True).start()
    main_bot.reply_to(m, "📣 Đang gửi...", reply_markup=back_markup("adm_panel"))

@main_bot.message_handler(
    func=lambda m: m.from_user is not None and m.from_user.id == ADMIN_ID
    and user_states.get(m.from_user.id) == "ADMIN_IMPORT_PROXY"
    and bool(m.text) and not m.text.startswith("/")
)
def admin_import_proxy_handler(m):
    lines = m.text.split("\n")
    added, errs = proxy_import(lines)
    user_states.pop(m.from_user.id, None)
    s = proxy_stock_count()
    txt = f"<b>✅ ĐÃ IMPORT PROXY</b>\n\n<blockquote>➕ Thêm: <b>{added}</b>\n"
    txt += f"📦 Tồn kho: <b>{s['available']}</b> khả dụng / {s['total']} tổng</blockquote>"
    if errs:
        txt += "\n\n<b>⚠️ Lỗi:</b>\n" + "\n".join(f"• {html.escape(e)}" for e in errs[:15])
    main_bot.reply_to(m, txt, reply_markup=back_markup("adm_proxy"))

@main_bot.message_handler(
    func=lambda m: m.from_user is not None and m.from_user.id == ADMIN_ID
    and (user_states.get(m.from_user.id) or "").startswith("ADMIN_EDIT_PRODUCT|")
    and bool(m.text) and not m.text.startswith("/")
)
def admin_edit_product_input(m):
    state = user_states.get(m.from_user.id, "")
    try:
        _, pid_s, field = state.split("|")
        pid = int(pid_s)
    except Exception:
        user_states.pop(m.from_user.id, None); return
    raw = m.text.strip()
    if field == "price":
        try: value = int(re.sub(r"[^\d]", "", raw))
        except Exception:
            main_bot.reply_to(m, "❌ Giá không hợp lệ. Nhập số nguyên, vd: 50000"); return
    elif field == "stock":
        try: value = int(raw)
        except Exception:
            main_bot.reply_to(m, "❌ Tồn kho phải là số (-1 = vô hạn)"); return
    else:
        value = raw
    product_update_field(pid, field, value)
    user_states.pop(m.from_user.id, None)
    field_vn = {"name": "Tên", "price": "Giá", "description": "Mô tả",
                "category": "Danh mục", "stock": "Tồn kho",
                "delivery_data": "Nội dung"}.get(field, field)
    main_bot.reply_to(m,
        f"✅ Đã cập nhật <b>{field_vn}</b> cho sản phẩm #{pid}.",
        reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
            types.InlineKeyboardButton("👁️ Xem lại sản phẩm",
                callback_data=f"adm_prod_view|{pid}"),
            types.InlineKeyboardButton("🔙 DS sản phẩm",
                callback_data="adm_products")))

@main_bot.message_handler(
    func=lambda m: m.from_user is not None and m.from_user.id == ADMIN_ID
    and (user_states.get(m.from_user.id) or "").startswith("ADMIN_EDIT_SETTING|")
    and bool(m.text) and not m.text.startswith("/")
)
def admin_edit_setting_input(m):
    state = user_states.get(m.from_user.id, "")
    try:
        key = state.split("|", 1)[1]
    except Exception:
        user_states.pop(m.from_user.id, None); return
    value = m.text.strip()
    setting_set(key, value)
    user_states.pop(m.from_user.id, None)
    main_bot.reply_to(m,
        f"✅ Đã cập nhật giao diện <b>{key}</b>.\n\n👉 Bấm /menu để xem thay đổi.",
        reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
            types.InlineKeyboardButton("🎨 Về giao diện", callback_data="adm_ui"),
            types.InlineKeyboardButton("🔙 Admin Panel", callback_data="adm_panel")))

# ══════════════════════════ ADMIN COMMANDS ══════════════════════════
@main_bot.message_handler(commands=["addmoney","stats","broadcast","testtiktok","lastwebhook",
                                     "shopstats","addproduct","delproduct","listproducts",
                                     "importproxy","proxystock","clearexpiredproxy","admin"])
def admin_commands(m):
    if m.from_user.id != ADMIN_ID: return
    cmd = m.text.split()[0].split("@")[0].lower()
    parts = m.text.split(maxsplit=2)

    if cmd == "/admin":
        main_bot.send_message(m.chat.id, admin_panel_text(), reply_markup=admin_panel_markup())

    elif cmd == "/addmoney":
        try: uid, amount = int(parts[1]), int(parts[2])
        except Exception:
            main_bot.reply_to(m, "Cú pháp: <code>/addmoney &lt;uid&gt; &lt;số_tiền&gt;</code>"); return
        admin_add_money(uid, amount)
        u = get_or_create_user(uid, "", "")
        main_bot.reply_to(m, f"✅ Đã cập nhật số dư <code>{uid}</code>.\n"
                             f"Số dư mới: <b>{fmt(u['balance'])}đ</b>")
        try:
            main_bot.send_message(uid, f"<b>💰 Admin vừa cập nhật số dư!</b>\n"
                                       f"🏦 Hiện có: <b>{fmt(u['balance'])}đ</b>")
        except Exception: pass

    elif cmd == "/stats":
        with db() as c:
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            bots  = c.execute("SELECT COUNT(*) FROM user_bots WHERE status='active'").fetchone()[0]
            dep   = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='deposit'").fetchone()[0]
        main_bot.reply_to(m, f"📊 <b>THỐNG KÊ</b>\n\n"
                             f"👥 Users: <b>{users}</b>\n🤖 Bot con: <b>{bots}</b>\n"
                             f"💰 Tổng nạp: <b>{fmt(dep)}đ</b>\n"
                             f"💾 DB: <code>{html.escape(DB_PATH)}</code>")

    elif cmd == "/testtiktok":
        if len(parts) < 2:
            main_bot.reply_to(m, "Cú pháp: <code>/testtiktok &lt;link&gt;</code>"); return
        data = snaptik_client.fetch(parts[1].strip())
        if not data or not data.get("hdplay"):
            main_bot.reply_to(m, "❌ Snaptik không trả dữ liệu."); return
        link = data["hdplay"]
        f = download_file(link, "test.mp4") if link else None
        if f: main_bot.reply_to(m, f"✅ OK ({f.getbuffer().nbytes//1024} KB)")
        else: main_bot.reply_to(m, f"⚠️ Snaptik OK, tải file lỗi\nLink: <code>{html.escape((link or '')[:150])}</code>")

    elif cmd == "/lastwebhook":
        body = html.escape("\n".join(webhook_log))
        main_bot.reply_to(m, "<b>📨 Webhook gần nhất:</b>\n" + (body or "Chưa có webhook."))

    elif cmd == "/broadcast":
        if len(parts) < 2:
            main_bot.reply_to(m, "Cú pháp: <code>/broadcast nội dung</code>"); return
        text = m.text.split(maxsplit=1)[1]
        def worker():
            with db() as c:
                ids = [r[0] for r in c.execute("SELECT user_id FROM users").fetchall()]
            ok = 0
            for uid in ids:
                try: main_bot.send_message(uid, text); ok += 1
                except Exception: pass
                time.sleep(0.05)
            main_bot.send_message(m.chat.id, f"📣 Đã gửi {ok}/{len(ids)} người.")
        threading.Thread(target=worker, daemon=True).start()
        main_bot.reply_to(m, "📣 Đang gửi...")

    elif cmd == "/shopstats":
        s = shop_stats()
        txt = (f"<b>📊 THỐNG KÊ BÁN HÀNG</b>\n\n<blockquote>"
               f"🛒 Tổng đơn: <b>{s['total_count']}</b>\n"
               f"💰 Tổng doanh thu: <b>{fmt(s['total_revenue'])}đ</b>\n"
               f"📅 Hôm nay: <b>{s['today_count']}</b> đơn – <b>{fmt(s['today_revenue'])}đ</b>"
               f"</blockquote>\n\n<b>🔥 Top 5:</b>\n")
        for name, cnt, rev in s["top"]:
            txt += f"• {html.escape(name)} – {cnt} đơn ({fmt(rev)}đ)\n"
        main_bot.reply_to(m, txt)

    elif cmd == "/listproducts":
        prods = shop_list(only_active=False, limit=100)
        if not prods:
            main_bot.reply_to(m, "Chưa có sản phẩm nào."); return
        txt = "<b>📦 DANH SÁCH SẢN PHẨM</b>\n\n"
        for p in prods:
            icon = "✅" if p.get("active", 1) else "⛔"
            txt += f"{icon} <code>{p['id']:>3}</code> | {html.escape(p['name'][:40])} | {fmt(p['price'])}đ | {p['category']}\n"
        main_bot.reply_to(m, txt)

    elif cmd == "/delproduct":
        try: pid = int(parts[1])
        except Exception:
            main_bot.reply_to(m, "Cú pháp: <code>/delproduct &lt;id&gt;</code>"); return
        p = shop_get(pid)
        product_delete(pid)
        main_bot.reply_to(m, f"✅ Đã xóa sản phẩm #{pid}" +
                         (f": {html.escape(p['name'])}" if p else ""))

    elif cmd == "/addproduct":
        if len(parts) < 3:
            main_bot.reply_to(m,
                "<b>Cú pháp:</b>\n<code>/addproduct Tên | giá | danh_mục | dtype | data | mô_tả</code>\n\n"
                "<b>dtype:</b> <code>text</code> / <code>link</code> / <code>file</code> / <code>proxy</code>\n"
                "• <code>text</code>: nội dung text (dùng \\n xuống dòng)\n"
                "• <code>link</code>: URL\n"
                "• <code>file</code>: file_id (gửi file trước cho bot)\n"
                "• <code>proxy</code>: data = số ngày (vd: 30)\n\n"
                "<b>Ví dụ:</b>\n"
                "<code>/addproduct VPN 1 tháng | 50000 | VPN | text | User: abc\\nPass: 123 | VPN tốc độ cao</code>")
            return
        try:
            fields = [f.strip() for f in m.text.split("|")]
            name = fields[0].replace("/addproduct", "").strip()
            price = int(fields[1])
            category = fields[2] if len(fields) > 2 else "Khác"
            dtype = fields[3] if len(fields) > 3 else "text"
            ddata = fields[4].replace("\\n", "\n") if len(fields) > 4 else ""
            desc = fields[5] if len(fields) > 5 else ""
        except Exception as e:
            main_bot.reply_to(m, f"❌ Lỗi định dạng: {e}"); return
        with db() as c:
            cur = c.execute("""INSERT INTO products (name,description,price,category,
                               delivery_type,delivery_data) VALUES (?,?,?,?,?,?)""",
                            (name, desc, price, category, dtype, ddata))
            pid = cur.lastrowid
        main_bot.reply_to(m, f"✅ Đã thêm sản phẩm #{pid}: <b>{html.escape(name)}</b>")

    elif cmd == "/importproxy":
        user_states[m.from_user.id] = "ADMIN_IMPORT_PROXY"
        main_bot.reply_to(m,
            "<b>📥 IMPORT PROXY</b>\n\n"
            "Gửi danh sách proxy (mỗi dòng 1 proxy):\n"
            "<code>ip:port:user:pass | region | isp | protocol</code>\n\n"
            "<b>Ví dụ:</b>\n"
            "<code>113.22.55.10:8080:user1:pass123 | Hà Nội | Viettel | HTTP</code>\n\n"
            "Gõ /cancel để hủy.")

    elif cmd == "/proxystock":
        s = proxy_stock_count()
        main_bot.reply_to(m,
            f"<b>📦 TỒN KHO PROXY</b>\n\n<blockquote>"
            f"✅ Còn bán: <b>{s['available']}</b>\n"
            f"💰 Đã bán: <b>{s['sold']}</b>\n"
            f"📊 Tổng: <b>{s['total']}</b></blockquote>")

    elif cmd == "/clearexpiredproxy":
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db() as c:
            cur = c.execute("""DELETE FROM proxy_stock
                               WHERE status='sold' AND expires_at != '' AND expires_at < ?""",
                            (now,))
            n = cur.rowcount
        main_bot.reply_to(m, f"✅ Đã xóa <b>{n}</b> proxy hết hạn.")

# ══════════════════════════ FALLBACK ══════════════════════════
@main_bot.message_handler(content_types=["document","photo","video","audio"])
def catch_media(m):
    if m.from_user and m.from_user.id == ADMIN_ID:
        fid = None
        if m.document: fid = m.document.file_id
        elif m.video: fid = m.video.file_id
        elif m.audio: fid = m.audio.file_id
        elif m.photo: fid = m.photo[-1].file_id
        if fid:
            main_bot.reply_to(m, f"📎 File ID:\n<code>{fid}</code>\n\n"
                                 f"Dùng:\n<code>/addproduct Tên | giá | danh_mục | file | {fid} | mô_tả</code>")

@main_bot.message_handler(
    func=lambda m: bool(m.text) and m.chat.type == "private" and not m.text.startswith("/")
)
def chat_or_fallback(m):
    if URL_RE.search(m.text): return
    if m.from_user and user_states.get(m.from_user.id):
        return
    low = m.text.strip().lower()
    if low in ("menu", "help", "giúp", "tro giup", "trợ giúp"):
        main_bot.reply_to(m, "Bấm /menu để mở menu chính nhé! 😉"); return
    try:
        reply_ai(main_bot, m)
    except Exception as e:
        log.exception("Chat AI bot chính lỗi: %s", e)
        main_bot.reply_to(m, "🤖 Bot đang bận, thử lại sau nhé!")

# ══════════════════════════ SEPAY WEBHOOK ══════════════════════════
def wh_note(status, detail=""):
    line = f"{datetime.now():%H:%M:%S} [{status}] {detail}"[:220]
    webhook_log.appendleft(line)
    log.info("SePay: %s", line)

@app.route("/sepaywebhook", methods=["POST"])
def sepay_webhook():
    if not SEPAY_API_KEY:
        wh_note("503", "chưa set SEPAY_API_KEY")
        return jsonify({"success": False}), 503
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(auth.encode(), f"Apikey {SEPAY_API_KEY}".encode()):
        wh_note("401", "sai Authorization")
        return jsonify({"success": False, "message": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    if str(data.get("transferType", "in")).lower() != "in":
        wh_note("SKIP", "tiền ra"); return jsonify({"success": True}), 200

    try: amount = int(float(data.get("transferAmount") or 0))
    except Exception: amount = 0
    tx_id = str(data.get("id") or data.get("referenceCode") or "")
    raw = " ".join(str(data.get(k) or "") for k in ("content","code","description"))
    text = raw.upper()
    text_clean = re.sub(r"[^A-Z0-9]", "", text)

    if amount <= 0 or not tx_id:
        wh_note("SKIP", f"amount={amount} id={tx_id!r}")
        return jsonify({"success": True}), 200

    m_nap = re.search(r"NAP(\d{5,13})", text_clean)
    m_don = re.search(r"DONATE(\d{5,13})", text_clean)

    if m_nap:
        uid = int(m_nap.group(1))
        if process_deposit(f"sepay:{tx_id}", uid, amount):
            wh_note("OK", f"nạp +{amount} → {uid}")
            try:
                u = get_or_create_user(uid, "", "")
                main_bot.send_message(uid,
                    f"<b>✅ NẠP TIỀN THÀNH CÔNG!</b>\n\n<blockquote>"
                    f"💵 Cộng: <b>+{fmt(amount)}đ</b>\n"
                    f"🏦 Số dư mới: <b>{fmt(u['balance'])}đ</b></blockquote>")
            except Exception: pass
            try: main_bot.send_message(ADMIN_ID, f"💰 +{fmt(amount)}đ từ <code>{uid}</code>")
            except Exception: pass
        else: wh_note("DUP", f"tx {tx_id}")
        return jsonify({"success": True}), 200

    if m_don:
        uid = int(m_don.group(1))
        if process_donation(f"sepay:{tx_id}", uid, amount):
            wh_note("OK", f"donate {amount} từ {uid}")
            for tgt in (uid, ADMIN_ID):
                try:
                    msg = (f"<b>❤️ Cảm ơn bạn donate {fmt(amount)}đ!</b>" if tgt == uid
                           else f"❤️ Donate {fmt(amount)}đ từ <code>{uid}</code>")
                    main_bot.send_message(tgt, msg)
                except Exception: pass
        else: wh_note("DUP", f"tx {tx_id}")
        return jsonify({"success": True}), 200

    wh_note("NOCODE", f"{amount}đ | {raw[:100]}")
    try: main_bot.send_message(ADMIN_ID,
        f"⚠️ Có tiền vào <b>{fmt(amount)}đ</b> nhưng không khớp NAP/DONATE:\n"
        f"<code>{html.escape(raw[:150])}</code>")
    except Exception: pass
    return jsonify({"success": True}), 200

@app.route("/")
def home(): return "Bot Server Active", 200

@app.route("/health")
def health(): return "ok", 200

# ══════════════════════════ KEEP ALIVE ══════════════════════════
def keep_alive():
    url = env("RENDER_EXTERNAL_URL") or ("https://" + env("RENDER_EXTERNAL_HOSTNAME") if env("RENDER_EXTERNAL_HOSTNAME") else "")
    if not url:
        log.warning("⚠️ Không có RENDER_EXTERNAL_URL → keep_alive TẮT.")
        return
    ping_url = url.rstrip("/") + "/health"
    log.info("🔄 Keep-alive → ping %s mỗi 5 phút", ping_url)
    stats = {"ok": 0, "fail": 0}
    time.sleep(30)
    while True:
        try:
            r = requests.get(ping_url, timeout=15, headers={"User-Agent": "RenderKeepAlive/1.0"})
            if r.status_code == 200:
                stats["ok"] += 1
                if stats["ok"] % 12 == 1:
                    log.info("💓 Keep-alive OK (lần %d)", stats["ok"])
            else:
                stats["fail"] += 1
                log.warning("⚠️ Keep-alive HTTP %s", r.status_code)
        except Exception as e:
            stats["fail"] += 1
            log.warning("⚠️ Keep-alive lỗi: %s", e)
        time.sleep(300)

def run_main_polling():
    while True:
        try:
            main_bot.remove_webhook()
            main_bot.infinity_polling(skip_pending=True, timeout=20,
                                      long_polling_timeout=20, logger_level=logging.WARNING)
        except Exception as e:
            log.warning("Polling bot chính: %s", e); time.sleep(5)

def main():
    init_db()
    if not SEPAY_API_KEY:
        log.warning("⚠️ Chưa set SEPAY_API_KEY!")
    if not GEMINI_API_KEY:
        log.warning("⚠️ Chưa set GEMINI_API_KEY → AI sẽ không hoạt động!")
    if env("RENDER") and not DB_PATH.startswith("/var/data"):
        log.warning("⚠️ DB ở %s → MẤT DATA mỗi lần deploy! Gắn Render Disk /var/data.", DB_PATH)
    try:
        main_bot.set_my_commands([
            types.BotCommand("start", "Mở menu chính"),
            types.BotCommand("menu",  "Mở menu chính"),
            types.BotCommand("admin", "Admin Panel (chỉ admin)"),
        ])
    except Exception: pass

    threading.Thread(target=load_all_child_bots, daemon=True).start()
    threading.Thread(target=run_main_polling,    daemon=True).start()
    threading.Thread(target=keep_alive,          daemon=True).start()
    log.info("✅ Bot đã chạy. DB: %s | Port: %s", DB_PATH, PORT)

    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
