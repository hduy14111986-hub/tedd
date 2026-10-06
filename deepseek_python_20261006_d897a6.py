# -*- coding: utf-8 -*-
"""Bot Telegram ALL-IN-ONE: TikTok no-logo + MP3 | Bypass link | Bán data 4G/VPN | AI | SePay."""
import os, io, re, time, html, hmac, sqlite3, logging, threading, urllib.parse
from collections import deque
from contextlib import contextmanager
from datetime import datetime

import requests, telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from flask import Flask, request, jsonify

try:
    from google import genai
except Exception:
    genai = None

# ====================== CONFIG ======================
def env(k, d=""): return os.environ.get(k, d).strip()

BOT_TOKEN     = env("BOT_TOKEN") or exit("Thiếu BOT_TOKEN")
GEMINI_API_KEY= env("GEMINI_API_KEY")
GEMINI_MODEL  = env("GEMINI_MODEL", "gemini-2.5-flash")
SEPAY_API_KEY = env("SEPAY_API_KEY")
ADMIN_ID      = int(env("ADMIN_ID", "8909964397"))
BOT_USERNAME  = env("BOT_USERNAME", "@dangphuongvu_bot")
ADMIN_USERNAME= env("ADMIN_USERNAME", "@dpvuuu")
BANK_NAME     = env("BANK_NAME", "TPBank")
ACCOUNT_NO    = env("ACCOUNT_NO", "10005824236")
ACCOUNT_NAME  = env("ACCOUNT_NAME", "DANG PHUONG VU")
CREATE_BOT_FEE= int(env("CREATE_BOT_FEE", "20000"))
AI_COOLDOWN   = int(env("AI_COOLDOWN", "4"))

DB_PATH = env("DB_PATH") or ("/var/data/bot_database.db" if os.path.isdir("/var/data") else "bot_database.db")
PORT    = int(env("PORT", "8080"))
PROXY_URL = env("PROXY_URL")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

main_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=8)
app      = Flask(__name__)

ai_client = None
if genai and GEMINI_API_KEY:
    try: ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e: log.warning("Gemini init: %s", e)

user_states, active_child_bots = {}, {}
child_lock, inflight_lock = threading.Lock(), threading.Lock()
ai_last_call = {}
webhook_log  = deque(maxlen=30)
inflight     = set()

# ================================ DB ================================
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
        c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)",
                  (ADMIN_ID, "", "Admin"))
        # Seed 6 gói data mặc định nếu chưa có sản phẩm nào
        cnt = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if cnt == 0:
            seed = [
                ("🌐 Data Viettel 30K – Không giới hạn", "Gói data Viettel không giới hạn data, tốc độ cao, dùng 30 ngày.", 30000, "Data 4G", "text", "Viettel 30K\nSoạn: DATA30 gửi 191\nHoặc liên hệ admin để kích hoạt.", -1),
                ("🌐 Data Viettel 50K – Không giới hạn", "Gói data Viettel không giới hạn data, tốc độ cao, dùng 30 ngày.", 50000, "Data 4G", "text", "Viettel 50K\nSoạn: DATA50 gửi 191\nHoặc liên hệ admin để kích hoạt.", -1),
                ("📱 Data VinaPhone 30K – Không giới hạn", "Gói data VinaPhone không giới hạn, dùng 30 ngày.", 30000, "Data 4G", "text", "VinaPhone 30K\nSoạn: DK D30 gửi 888\nHoặc liên hệ admin.", -1),
                ("📱 Data VinaPhone 50K – Không giới hạn", "Gói data VinaPhone không giới hạn, dùng 30 ngày.", 50000, "Data 4G", "text", "VinaPhone 50K\nSoạn: DK D50 gửi 888\nHoặc liên hệ admin.", -1),
                ("📶 Data MobiFone 30K – Không giới hạn", "Gói data MobiFone không giới hạn, dùng 30 ngày.", 30000, "Data 4G", "text", "MobiFone 30K\nSoạn: DK D30 gửi 999\nHoặc liên hệ admin.", -1),
                ("📶 Data MobiFone 50K – Không giới hạn", "Gói data MobiFone không giới hạn, dùng 30 ngày.", 50000, "Data 4G", "text", "MobiFone 50K\nSoạn: DK D50 gửi 999\nHoặc liên hệ admin.", -1),
            ]
            for row in seed:
                c.execute("""INSERT INTO products
                    (name,description,price,category,delivery_type,delivery_data,stock)
                    VALUES (?,?,?,?,?,?,?)""", row)
            log.info("Đã seed 6 gói data mặc định")

# ---- User ----
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

# ================================ SHOP DB ================================
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
        q = "SELECT id,name,price,category,image_url,stock,sold FROM products WHERE 1=1"
        p = []
        if only_active: q += " AND active=1"
        if category and category != "Tất cả":
            q += " AND category=?"; p.append(category)
        q += " ORDER BY id ASC LIMIT ?"; p.append(limit)
        rows = c.execute(q, p).fetchall()
    return [dict(zip(["id","name","price","category","image_url","stock","sold"], r)) for r in rows]

def shop_top(limit=8):
    with db() as c:
        rows = c.execute("""SELECT id,name,price,category,image_url,stock,sold
                            FROM products WHERE active=1 ORDER BY sold DESC LIMIT ?""",
                         (limit,)).fetchall()
    return [dict(zip(["id","name","price","category","image_url","stock","sold"], r)) for r in rows]

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

# ================================ TIKTOK ================================
TIKWM = "https://www.tikwm.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
URL_RE = re.compile(r"https?://(?:[\w-]+\.)?tiktok\.com/\S+", re.I)
MAX_UPLOAD = 49 * 1024 * 1024
TIKWM_HEADERS = {**UA, "Referer": TIKWM+"/", "Origin": TIKWM,
                 "Accept": "application/json, text/plain, */*"}
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
_tikwm_lock, _tikwm_next = threading.Lock(), 0.0
link_cache = {}
last_tikwm_error = ""

def abs_url(u):
    if not u: return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"):  return TIKWM + u
    return u

def _tikwm_slot():
    global _tikwm_next
    with _tikwm_lock:
        now = time.time()
        start = max(now, _tikwm_next)
        _tikwm_next = start + 1.2
    if start > now: time.sleep(start - now)

def tikwm_fetch(url):
    global last_tikwm_error
    for attempt in range(3):
        _tikwm_slot()
        try:
            r = requests.post(f"{TIKWM}/api/", data={"url": url, "hd": 1},
                              headers=TIKWM_HEADERS, timeout=25, proxies=PROXIES)
        except Exception as e:
            last_tikwm_error = f"không kết nối tikwm: {e}"; continue
        try: j = r.json()
        except ValueError:
            last_tikwm_error = f"HTTP {r.status_code} non-JSON"
            if r.status_code in (401, 403): break
            continue
        if j.get("code") == 0 and j.get("data"):
            last_tikwm_error = ""; return j["data"]
        last_tikwm_error = f"HTTP {r.status_code}, code={j.get('code')}, msg={j.get('msg')}"
        if "limit" in str(j.get("msg") or "").lower():
            time.sleep(2*(attempt+1)); continue
        break
    return None

def download_file(url, name):
    if not url: return None
    try:
        with requests.get(url, headers=TIKWM_HEADERS, stream=True,
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
    data = tikwm_fetch(url)
    if not data:
        return False, "❌ Không tải được. Video phải công khai và link đúng dạng TikTok!"
    vid = str(data.get("id") or "")
    if vid: cache_put(vid, url)
    title  = (data.get("title") or "TikTok").strip()
    author = (data.get("author") or {}).get("nickname") or ""
    caption = f"🎬 <b>{html.escape(title[:200])}</b>"
    if author: caption += f"\n👤 {html.escape(author)}"
    caption += "\n\n✨ <i>Đã gỡ logo thành công!</i>"

    images = data.get("images") or []
    if images:
        imgs = [abs_url(i) for i in images]
        try:
            for i in range(0, len(imgs), 10):
                group = [types.InputMediaPhoto(u,
                    caption=caption if (i==0 and k==0) else None,
                    parse_mode="HTML" if (i==0 and k==0) else None)
                    for k, u in enumerate(imgs[i:i+10])]
                bot.send_media_group(chat_id, group)
            bot.send_message(chat_id, "🎵 Muốn lấy nhạc nền không?",
                             reply_markup=mp3_markup(vid))
            return True, ""
        except Exception as e:
            log.warning("send_media_group: %s", e)
            return False, "❌ Gửi ảnh thất bại!"

    candidates = []
    for key in ("hdplay", "play"):
        u = abs_url(data.get(key))
        if u and u not in candidates: candidates.append(u)
    if not candidates: return False, "❌ Không tìm thấy video."
    try: bot.send_chat_action(chat_id, "upload_video")
    except Exception: pass
    for u in candidates:
        f = download_file(u, "tiktok.mp4")
        if not f: continue
        try:
            bot.send_video(chat_id, f, caption=caption,
                           supports_streaming=True, reply_markup=mp3_markup(vid))
            return True, ""
        except Exception as e: log.warning("send_video: %s", e)
    bot.send_message(chat_id, caption + "\n\n⚠️ Không gửi trực tiếp được, bấm nút bên dưới.",
                     reply_markup=mp3_markup(vid, extra_url=candidates[0]))
    return True, ""

def deliver_mp3(bot, chat_id, vid):
    url = link_cache.get(vid) or f"https://www.tiktok.com/@tiktok/video/{vid}"
    data = tikwm_fetch(url)
    if not data: bot.send_message(chat_id, "❌ Không trích được nhạc!"); return
    info = data.get("music_info") or {}
    music = abs_url(data.get("music") or info.get("play"))
    f = download_file(music, "tiktok_audio.mp3")
    if not f: bot.send_message(chat_id, "❌ Không tải được nhạc (video không có nhạc?)."); return
    try: bot.send_chat_action(chat_id, "upload_audio")
    except Exception: pass
    bot.send_audio(chat_id, f,
                   title=(info.get("title") or data.get("title") or "TikTok Audio")[:60],
                   performer=(info.get("author") or "TikTok")[:60],
                   caption="🎵 <i>Đã tách nhạc thành công!</i>")

# ================================ BYPASS LINK ================================
BYPASS_DOMAINS = [
    "link4m.com", "link4m.net", "link4m.co",
    "link1s.com", "link1s.net",
    "exe.io", "exee.io", "exey.io",
    "shrtfly.com", "shrtfly.net", "shrtfly.vip",
    "megaurl.in", "megaurl.io",
    "layarkaca21.com", "sub2unlock.com", "sub2unlock.net",
    "yeumoney.com", "yeumoney.net",
    "linkvip.net", "linkviplam.net",
    "traffic1s.com", "traffic1s.net",
    "link68.net", "link4m.org",
    "shortearn.eu", "shortearn.in",
    "adf.ly", "ouo.io", "ouo.press",
    "mboost.me", "fc.lc", "fc.lc",
]
BYPASS_RE = re.compile(r"https?://(?:[\w.-]*\.)?(" + "|".join(
    re.escape(d).replace(r"\.", r"\.") for d in BYPASS_DOMAINS) + r")/\S+", re.I)

BYPASS_APIS = [
    "https://api.bypass.vip/bypass?url=",
    "https://bypass.city/api/bypass?url=",
]

def bypass_link(url):
    """Thử nhiều API bypass, trả về URL cuối hoặc None."""
    for api in BYPASS_APIS:
        try:
            r = requests.get(api + urllib.parse.quote(url, safe=""), timeout=20)
            j = r.json()
            res = j.get("result") or j.get("destination") or j.get("url")
            if res and res.startswith("http") and res != url:
                return res
        except Exception as e:
            log.warning("bypass API %s lỗi: %s", api, e)
    return None

def deliver_bypass(bot, chat_id, url):
    try: wait = bot.send_message(chat_id, "🔓 Đang bypass link, đợi chút nhé...")
    except Exception: wait = None
    result = bypass_link(url)
    if wait:
        try: bot.delete_message(chat_id, wait.message_id)
        except Exception: pass
    if not result:
        bot.send_message(chat_id,
            "❌ Không bypass được link này!\n"
            "👉 Có thể link đã hết hạn, API bypass đang bảo trì, hoặc dịch vụ chưa hỗ trợ.\n"
            "Thử lại sau ít phút nhé!")
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔗 Mở link gốc", url=result))
    bot.send_message(chat_id,
        f"<b>✅ BYPASS THÀNH CÔNG!</b>\n\n"
        f"🔗 Link gốc:\n<code>{html.escape(result)}</code>\n\n"
        f"👉 Bấm nút bên dưới để mở.",
        reply_markup=kb, disable_web_page_preview=True)

def register_downloader(bot):
    @bot.message_handler(func=lambda m: bool(BYPASS_RE.search(m.text or "")))
    def _on_bypass(m):
        url = BYPASS_RE.search(m.text).group(0).rstrip(").,]!?")
        threading.Thread(target=deliver_bypass, args=(bot, m.chat.id, url), daemon=True).start()

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

# ================================ AI ================================
PERSONA = ("Bạn là trợ lý chatbot hài hước, lầy lội, thân thiện, trả lời tiếng Việt. "
           "Trả lời ngắn gọn, vui nhộn. Câu hỏi:")

def ask_gemini(text):
    if not ai_client: return "AI chưa cấu hình, nhưng tải TikTok vẫn ngon! 😎"
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
    now = time.time()
    if now - ai_last_call.get((id(bot), uid), 0) < AI_COOLDOWN:
        bot.reply_to(m, f"⏳ Đợi {AI_COOLDOWN} giây nhé!"); return
    ai_last_call[(id(bot), uid)] = now
    try: bot.send_chat_action(m.chat.id, "typing")
    except Exception: pass
    answer = html.escape(ask_gemini(m.text))
    for i, part in enumerate(split_text(answer)):
        if i == 0: bot.reply_to(m, part)
        else: bot.send_message(m.chat.id, part)

# ================================ BOT CON ================================
def register_child_handlers(bot):
    @bot.message_handler(commands=["start", "help"])
    def _start(m):
        bot.send_message(m.chat.id,
            "<b>🤖 CHÀO MỪNG!</b>\n\n<blockquote>"
            "✨ Gửi link TikTok → tải video không logo + MP3\n"
            "🔓 Gửi link rút gọn (link4m, link1s...) → bypass tự động\n"
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

# ================================ UI ================================
def fmt(n): return f"{int(n):,}".replace(",", ".")

def back_markup(cb="menu_back"):
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🔙 Quay Lại", callback_data=cb))

def main_menu_keyboard():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("👤 Tài khoản", callback_data="menu_profile"),
          types.InlineKeyboardButton("🛒 Cửa Hàng Data/VPN", callback_data="shop_home"))
    m.add(types.InlineKeyboardButton("📥 Tải TikTok Không Logo", callback_data="menu_tiktok_guide"),
          types.InlineKeyboardButton("🔓 Bypass Link", callback_data="menu_bypass_guide"))
    m.add(types.InlineKeyboardButton(f"🤖 Tạo Bot ({CREATE_BOT_FEE//1000}k)", callback_data="menu_create_bot"),
          types.InlineKeyboardButton("💰 Nạp tiền", callback_data="menu_deposit"))
    m.add(types.InlineKeyboardButton("❤️ Donate", callback_data="menu_donate"),
          types.InlineKeyboardButton("🎛️ Hỗ trợ", callback_data="menu_support"))
    return m

def home_text(u):
    return ("<b>🚀 HỆ THỐNG BOT ĐA NĂNG</b>\n\n<blockquote>"
            f"🤖 <b>Bot:</b> {BOT_USERNAME}\n👑 <b>Admin:</b> {ADMIN_USERNAME}\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>Tổng nạp:</b> {fmt(u['total'])}đ\n"
            f"💰 <b>Tháng này:</b> {fmt(u['month'])}đ\n"
            f"🏦 <b>Số dư:</b> {fmt(u['balance'])}đ</blockquote>\n\n"
            "🎯 <b>Chức năng:</b>\n"
            "• 📥 Tải TikTok không logo + nhạc MP3\n"
            "• 🔓 Bypass link rút gọn (link4m, link1s...)\n"
            "• 🛒 Bán Data 4G/5G + VPN cho 3 nhà mạng\n"
            "• 💬 Chat AI thông minh\n"
            "• 🤖 Tạo bot riêng cho bạn")

# ================================ SHOP UI ================================
def shop_home_markup():
    cats = shop_categories()
    m = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(f"📂 {c}", callback_data=f"shop_cat|{c}")
            for c in cats[:10]]
    if btns: m.add(*btns)
    m.add(types.InlineKeyboardButton("🔥 Bán chạy", callback_data="shop_top"),
          types.InlineKeyboardButton("🛍 Đơn của tôi", callback_data="shop_myorders"))
    m.add(types.InlineKeyboardButton("🔙 Menu Chính", callback_data="menu_back"))
    return m

def shop_home_text():
    prods = shop_list()
    return (f"<b>🛒 CỬA HÀNG DATA / VPN</b>\n\n<blockquote>"
            f"📦 Có <b>{len(prods)}</b> sản phẩm đang bán\n"
            f"💰 Thanh toán bằng số dư ví (nạp ở menu chính)\n"
            f"📱 Hỗ trợ Viettel • VinaPhone • MobiFone</blockquote>\n\n"
            f"👉 Chọn <b>danh mục</b> hoặc xem <b>bán chạy</b> bên dưới:")

def product_detail_text(p):
    stock_txt = "♾️ Vô hạn" if p["stock"] < 0 else \
                ("❌ Hết hàng" if p["stock"] == 0 else f"📦 Còn {p['stock']}")
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

def deliver_product(bot, chat_id, product):
    dtype = product["delivery_type"]
    data  = product["delivery_data"]
    name  = product["name"]
    try:
        if dtype == "link":
            bot.send_message(chat_id,
                f"<b>✅ Mua thành công: {html.escape(name)}</b>\n\n"
                f"🔗 Link của bạn:\n{html.escape(data)}",
                disable_web_page_preview=False)
        elif dtype == "file":
            bot.send_document(chat_id, data,
                caption=f"<b>✅ Mua thành công: {html.escape(name)}</b>\n\n📁 File bên dưới.")
        else:
            bot.send_message(chat_id,
                f"<b>✅ Mua thành công: {html.escape(name)}</b>\n\n"
                f"📝 Hướng dẫn kích hoạt:\n<pre>{html.escape(data)}</pre>")
    except Exception as e:
        log.warning("deliver_product: %s", e)
        bot.send_message(chat_id, f"⚠️ Không gửi được nội dung. Liên hệ admin: {ADMIN_USERNAME}")

# ================================ MAIN HANDLERS ================================
def user_from(tg):
    return get_or_create_user(tg.id, tg.username or "", tg.first_name or "Khách")

@main_bot.message_handler(commands=["start", "menu"])
def send_welcome(m):
    user_states.pop(m.from_user.id, None)
    main_bot.send_message(m.chat.id, home_text(user_from(m.from_user)),
                          reply_markup=main_menu_keyboard())

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

@main_bot.callback_query_handler(func=lambda c: (c.data or "").startswith(("menu_", "dep|", "shop_")))
def callback_listener(call):
    try: main_bot.answer_callback_query(call.id)
    except Exception: pass
    uid = call.from_user.id
    u   = user_from(call.from_user)
    data= call.data
    is_admin = uid == ADMIN_ID

    # ---------- MAIN MENU ----------
    if data == "menu_profile":
        text = (f"<b>📊 THÔNG TIN TÀI KHOẢN</b>\n\n<blockquote>"
                f"🆔 <b>ID:</b> <code>{uid}</code>\n"
                f"👤 <b>Họ tên:</b> {html.escape(call.from_user.first_name or 'Khách')}\n"
                f"🏦 <b>Số dư:</b> {fmt(u['balance'])}đ\n"
                f"🏆 <b>Tổng nạp:</b> {fmt(u['total'])}đ\n"
                f"📅 <b>Tháng này:</b> {fmt(u['month'])}đ</blockquote>")
        show(call, text, back_markup())

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
                       f"💰 Phí {fmt(CREATE_BOT_FEE)}đ (trừ sau khi kích hoạt thành công)\n\n"
                       "1️⃣ Mở @BotFather → /newbot\n"
                       "2️⃣ Copy Token và gửi vào đây:", back_markup())

    elif data == "menu_tiktok_guide":
        show(call, "<b>📥 TẢI TIKTOK KHÔNG LOGO</b>\n\n<blockquote>"
                   "Gửi link TikTok vào khung chat → bot tự trả video không logo.\n"
                   "🎵 Bấm nút <b>Tải nhạc MP3</b> dưới video.\n"
                   "📸 Slideshow ảnh cũng được hỗ trợ!</blockquote>", back_markup())

    elif data == "menu_bypass_guide":
        doms = ", ".join(BYPASS_DOMAINS[:8]) + "..."
        show(call, "<b>🔓 BYPASS LINK RÚT GỌN</b>\n\n<blockquote>"
                   f"Hỗ trợ: <b>{doms}</b>\n\n"
                   "Chỉ cần gửi link rút gọn vào chat, bot tự bypass.</blockquote>", back_markup())

    elif data == "menu_deposit":
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(*[types.InlineKeyboardButton(f"{a//1000}k", callback_data=f"dep|{a}")
                 for a in (20000, 30000, 50000, 100000, 200000, 500000)])
        kb.add(types.InlineKeyboardButton("✏️ Số tiền khác", callback_data="dep|0"),
               types.InlineKeyboardButton("🔙 Quay Lại", callback_data="menu_back"))
        show(call, "<b>💰 NẠP TIỀN TỰ ĐỘNG</b>\n\nChọn số tiền, tiền cộng tự động sau khi CK:", kb)

    elif data.startswith("dep|"):
        amount = int(data.split("|")[1])
        send_qr(call, amount, f"NAP{uid}", "💰 NẠP TIỀN TỰ ĐỘNG",
                "⚡ Chuyển <b>đúng nội dung</b>, số dư tự cộng sau 10–30 giây.")

    elif data == "menu_donate":
        send_qr(call, 0, f"DONATE{uid}", "❤️ DONATE ỦNG HỘ", "🙏 Cảm ơn bạn!")

    elif data == "menu_support":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("💬 Nhắn Admin",
                url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}"),
               types.InlineKeyboardButton("🔙 Quay Lại", callback_data="menu_back"))
        show(call, f"<b>🎛️ HỖ TRỢ</b>\n\nAdmin: {ADMIN_USERNAME}", kb)

    elif data == "menu_back":
        user_states.pop(uid, None)
        show(call, home_text(u), main_menu_keyboard())

    # ---------- SHOP ----------
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
        show(call, f"<b>📂 DANH MỤC: {html.escape(cat)}</b>\n\n"
                   f"Có <b>{len(prods)}</b> sản phẩm:", kb)

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
        ok, res = shop_purchase(uid, pid)
        if not ok:
            show(call, f"❌ Mua thất bại: {res}",
                 types.InlineKeyboardMarkup().add(
                     types.InlineKeyboardButton("🔙 Cửa Hàng", callback_data="shop_home")))
            return
        # Gửi nội dung + xóa tin nhắn cũ
        try: main_bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass
        main_bot.send_message(call.message.chat.id,
            f"<b>🎉 ĐẶT HÀNG THÀNH CÔNG!</b>\n\n<blockquote>"
            f"📦 Sản phẩm: <b>{html.escape(res['name'])}</b>\n"
            f"💵 Giá: <b>{fmt(res['price'])}đ</b>\n"
            f"🏦 Số dư còn: <b>{fmt(u['balance'] - res['price'])}đ</b></blockquote>")
        deliver_product(main_bot, call.message.chat.id, res)
        # Báo admin
        try:
            main_bot.send_message(ADMIN_ID,
                f"💰 <b>ĐƠN HÀNG MỚI</b>\n"
                f"👤 <code>{uid}</code> ({html.escape(call.from_user.first_name or '')})\n"
                f"📦 {html.escape(res['name'])}\n"
                f"💵 {fmt(res['price'])}đ")
        except Exception: pass

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

# ================================ TOKEN CREATE BOT ================================
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")

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
    try:
        info = telebot.TeleBot(token).get_me()
    except Exception:
        say("❌ <b>Token không hợp lệ!</b>"); return

    u = user_from(message.from_user)
    if not is_admin:
        ok = charge_safe = None
        with db() as c:
            cur = c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                            (CREATE_BOT_FEE, uid, CREATE_BOT_FEE))
            ok = cur.rowcount == 1
        if not ok:
            user_states.pop(uid, None)
            say(f"❌ Số dư không đủ ({fmt(u['balance'])}đ). Nạp thêm nhé!"); return

    try:
        save_user_bot(uid, token, info.username)
        start_child_bot(token)
    except Exception as e:
        log.exception("Kích hoạt bot con lỗi: %s", e)
        if not is_admin:
            with db() as c:
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (CREATE_BOT_FEE, uid))
        say("❌ Kích hoạt thất bại, tiền đã hoàn lại."); return

    user_states.pop(uid, None)
    paid = "Miễn phí (admin)" if is_admin else f"-{fmt(CREATE_BOT_FEE)}đ"
    say(f"<b>🚀 KÍCH HOẠT THÀNH CÔNG!</b>\n\n"
        f"🤖 Bot: @{info.username}\n💸 Phí: {paid}\n\nBot đã chạy ngay!")

# ================================ ADMIN COMMANDS ================================
@main_bot.message_handler(commands=["addmoney","stats","broadcast","testtiktok","lastwebhook",
                                     "shopstats","addproduct","delproduct","listproducts","testbypass"])
def admin_commands(m):
    if m.from_user.id != ADMIN_ID: return
    cmd = m.text.split()[0].split("@")[0].lower()
    parts = m.text.split(maxsplit=2)

    if cmd == "/addmoney":
        try: uid, amount = int(parts[1]), int(parts[2])
        except Exception:
            main_bot.reply_to(m, "Cú pháp: <code>/addmoney &lt;uid&gt; &lt;số_tiền&gt;</code>"); return
        admin_add_money(uid, amount)
        main_bot.reply_to(m, f"✅ Đã cộng {fmt(amount)}đ cho <code>{uid}</code>")
        try: main_bot.send_message(uid, f"<b>✅ Admin cộng cho bạn {fmt(amount)}đ</b>")
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
        data = tikwm_fetch(parts[1].strip())
        if not data:
            main_bot.reply_to(m, f"❌ tikwm lỗi:\n<code>{html.escape(last_tikwm_error)}</code>"); return
        link = abs_url(data.get("hdplay") or data.get("play"))
        f = download_file(link, "test.mp4") if link else None
        if f: main_bot.reply_to(m, f"✅ OK ({f.getbuffer().nbytes//1024} KB)")
        else: main_bot.reply_to(m, f"⚠️ tikwm OK, tải file lỗi\nLink: <code>{html.escape((link or '')[:150])}</code>")

    elif cmd == "/testbypass":
        if len(parts) < 2:
            main_bot.reply_to(m, "Cú pháp: <code>/testbypass &lt;link&gt;</code>"); return
        r = bypass_link(parts[1].strip())
        main_bot.reply_to(m, f"✅ Kết quả:\n<code>{html.escape(r)}</code>" if r else "❌ Không bypass được")

    elif cmd == "/lastwebhook":
        body = html.escape("\n".join(webhook_log))
        main_bot.reply_to(m, "<b>📨 Webhook gần nhất:</b>\n" + (body or "Chưa có webhook nào."))

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
               f"📅 Hôm nay: <b>{s['today_count']}</b> đơn – <b>{fmt(s['today_revenue'])}đ</b>\n"
               f"</blockquote>\n\n<b>🔥 Top 5 sản phẩm:</b>\n")
        for name, cnt, rev in s["top"]:
            txt += f"• {html.escape(name)} – {cnt} đơn ({fmt(rev)}đ)\n"
        main_bot.reply_to(m, txt)

    elif cmd == "/listproducts":
        prods = shop_list(only_active=False, limit=100)
        if not prods:
            main_bot.reply_to(m, "Chưa có sản phẩm nào."); return
        txt = "<b>📦 DANH SÁCH SẢN PHẨM</b>\n\n"
        for p in prods:
            txt += f"<code>{p['id']:>3}</code> | {html.escape(p['name'][:40])} | {fmt(p['price'])}đ | {p['category']}\n"
        main_bot.reply_to(m, txt)

    elif cmd == "/delproduct":
        try: pid = int(parts[1])
        except Exception:
            main_bot.reply_to(m, "Cú pháp: <code>/delproduct &lt;id&gt;</code>"); return
        with db() as c: c.execute("DELETE FROM products WHERE id=?", (pid,))
        main_bot.reply_to(m, f"✅ Đã xóa sản phẩm #{pid}")

    elif cmd == "/addproduct":
        # /addproduct name | price | category | dtype | delivery_data | description
        if len(parts) < 3:
            main_bot.reply_to(m,
                "Cú pháp:\n<code>/addproduct Tên | giá | danh_mục | link/text/file | dữ_liệu | mô_tả</code>\n\n"
                "Ví dụ:\n<code>/addproduct VPN 1 tháng | 50000 | VPN | text | "
                "User: abc\\nPass: 123 | VPN tốc độ cao</code>\n\n"
                "dtype: <b>text</b> (nội dung), <b>link</b> (URL), <b>file</b> (file_id gửi trước).")
            return
        try:
            fields = [f.strip() for f in m.text.split("|")]
            name = fields[0].replace("/addproduct", "").strip()
            price = int(fields[1])
            category = fields[2] if len(fields) > 2 else "Khác"
            dtype = fields[3] if len(fields) > 3 else "text"
            ddata = fields[4] if len(fields) > 4 else ""
            desc = fields[5] if len(fields) > 5 else ""
        except Exception as e:
            main_bot.reply_to(m, f"❌ Lỗi định dạng: {e}"); return
        with db() as c:
            cur = c.execute("""INSERT INTO products (name,description,price,category,
                               delivery_type,delivery_data) VALUES (?,?,?,?,?,?)""",
                            (name, desc, price, category, dtype, ddata))
            pid = cur.lastrowid
        main_bot.reply_to(m, f"✅ Đã thêm sản phẩm #{pid}: <b>{html.escape(name)}</b>")

# ================================ FALLBACK ================================
@main_bot.message_handler(content_types=["document","photo","video","audio"])
def catch_media(m):
    if m.from_user and m.from_user.id == ADMIN_ID:
        fid = None
        if m.document: fid = m.document.file_id
        elif m.video: fid = m.video.file_id
        elif m.audio: fid = m.audio.file_id
        elif m.photo: fid = m.photo[-1].file_id
        if fid:
            main_bot.reply_to(m, f"📎 File ID của bạn:\n<code>{fid}</code>\n\n"
                                 f"Dùng lệnh:\n<code>/addproduct Tên | giá | danh_mục | file | {fid} | mô_tả</code>")

@main_bot.message_handler(func=lambda m: bool(m.text) and m.chat.type == "private")
def fallback_text(m):
    if m.text and (URL_RE.search(m.text) or BYPASS_RE.search(m.text)): return
    main_bot.reply_to(m, "Gửi link TikTok / link rút gọn để bot xử lý, hoặc bấm /menu 📱")

# ================================ SEPAY WEBHOOK ================================
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
    # Cho phép ngân hàng chèn -, ., space giữa tiền tố và ID
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
            try: main_bot.send_message(uid,
                f"<b>✅ NẠP TIỀN THÀNH CÔNG!</b>\n\n<blockquote>"
                f"💵 Cộng: <b>+{fmt(amount)}đ</b>\n"
                f"💰 Số dư mới: xem /menu</blockquote>")
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

# ================================ START ================================
def keep_alive():
    url = env("RENDER_EXTERNAL_URL")
    if not url:
        log.warning("RENDER_EXTERNAL_URL trống → bot sẽ ngủ sau 15 phút. "
                    "Set biến này hoặc dùng cron-job.org ping /health mỗi 5 phút!")
        return
    while True:
        time.sleep(540)
        try: requests.get(url.rstrip("/") + "/health", timeout=10)
        except Exception as e: log.warning("keep_alive: %s", e)

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
        log.warning("⚠️ Chưa set SEPAY_API_KEY → nạp tiền tự động KHÔNG hoạt động!")
    if env("RENDER") and not DB_PATH.startswith("/var/data"):
        log.warning("⚠️ DB đang ở %s → số dư và đơn hàng SẼ MẤT mỗi lần deploy! "
                    "Gắn Render Disk mount /var/data.", DB_PATH)
    try:
        main_bot.set_my_commands([
            types.BotCommand("start", "Mở menu chính"),
            types.BotCommand("menu", "Mở menu chính"),
        ])
    except Exception: pass

    threading.Thread(target=load_all_child_bots, daemon=True).start()
    threading.Thread(target=run_main_polling, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    log.info("✅ Bot đã chạy. DB: %s | Port: %s", DB_PATH, PORT)

    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()