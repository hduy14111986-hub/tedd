# -*- coding: utf-8 -*-
"""Module Buff Mạng Xã Hội — Auto-detect giá chính xác cho subre247"""
import os, re, time, html, json, sqlite3, logging, threading
from datetime import datetime
import requests
from telebot import types

log = logging.getLogger("smm")

SCHEMA = """
CREATE TABLE IF NOT EXISTS smm_cfg (key TEXT PRIMARY KEY, value TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS smm_services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, name TEXT, api_service TEXT,
  cost INTEGER DEFAULT 0, price INTEGER DEFAULT 0,
  min INTEGER DEFAULT 100, max INTEGER DEFAULT 100000,
  custom_price INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS smm_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, service_id INTEGER, service_name TEXT,
  platform TEXT, link TEXT, quantity INTEGER, price INTEGER,
  api_order TEXT, status TEXT DEFAULT 'pending',
  start_count INTEGER DEFAULT 0, remains INTEGER DEFAULT 0, note TEXT DEFAULT '',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""

PLATFORMS = [("TikTok","🎵"),("Facebook","📘"),("Instagram","📷"),("YouTube","▶️"),
             ("Shopee","🛒"),("Telegram","✈️"),("Twitter","🐦"),("Khác","🌐")]

SUBTYPES = [
    ("Tim",     "❤️", ["tim", "like", "tym", "heart", "cảm xúc"]),
    ("Follow",  "👥", ["follow", "fl ", " fl", "theo dõi", "sub", "follower"]),
    ("Share",   "🔁", ["share", "chia sẻ", "repost", "lan truyền"]),
    ("View",    "👁", ["view", "lượt xem", "xem ", "watch", "play"]),
    ("Comment", "💬", ["comment", "cmt", "bình luận", "bl "]),
    ("Live",    "📡", ["live", "mắt live", "stream"]),
    ("Khác",    "🌐", []),
]

STATUS_VI = {"pending":"⏳ Chờ","processing":"⚙️ Chạy","in progress":"⚙️ Chạy",
             "inprogress":"⚙️ Chạy","completed":"✅ Xong","complete":"✅ Xong",
             "partial":"⚠️ Một phần","canceled":"❌ Hủy","cancelled":"❌ Hủy",
             "refunded":"💸 Hoàn tiền","error":"❌ Lỗi"}

DEFAULT_USD_RATE = 25000
DEFAULT_MARKUP   = 30


def _q(db_path, sql, params=(), fetch=None):
    c = sqlite3.connect(db_path, timeout=30)
    try:
        cur = c.execute(sql, params); c.commit()
        if fetch == "one": return cur.fetchone()
        if fetch == "all": return cur.fetchall()
        return cur.lastrowid
    finally: c.close()

def init_schema(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    try:
        c.executescript(SCHEMA); c.commit()
        try: c.execute("ALTER TABLE smm_services ADD COLUMN custom_price INTEGER DEFAULT 0")
        except: pass
        c.commit()
    finally: c.close()

def cfg_get(p, k, d=""):
    r = _q(p, "SELECT value FROM smm_cfg WHERE key=?", (k,), "one")
    return r[0] if r and r[0] else d
def cfg_set(p, k, v):
    _q(p, "INSERT OR REPLACE INTO smm_cfg (key,value) VALUES (?,?)", (k, v))

def _get_rate(p):
    try: return int(cfg_get(p, "smm_usd_rate", str(DEFAULT_USD_RATE)))
    except: return DEFAULT_USD_RATE
def _get_markup(p):
    try: return float(cfg_get(p, "smm_markup_pct", str(DEFAULT_MARKUP)))
    except: return DEFAULT_MARKUP
def _get_currency(p):
    return (cfg_get(p, "smm_currency_mode", "auto") or "auto").lower()
def _get_mult(p):
    try: return float(cfg_get(p, "smm_rate_multiplier", "1") or 1)
    except: return 1.0


def cache_save(bp, services):
    try:
        cfg_set(bp, "smm_cache_json", json.dumps(services, ensure_ascii=False))
        cfg_set(bp, "smm_cache_time", datetime.now().strftime("%d/%m %H:%M"))
        cfg_set(bp, "smm_cache_count", str(len(services)))
        return True
    except Exception as e:
        log.warning("cache_save: %s", e); return False

def cache_load(bp):
    s = cfg_get(bp, "smm_cache_json", "")
    t = cfg_get(bp, "smm_cache_time", "")
    if not s: return [], t
    try: return json.loads(s), t
    except Exception as e:
        log.warning("cache_load: %s", e); return [], t

def cache_clear(bp):
    cfg_set(bp, "smm_cache_json", "")
    cfg_set(bp, "smm_cache_time", "")
    cfg_set(bp, "smm_cache_count", "0")


def _api(p, action, **params):
    url = cfg_get(p, "smm_api_url"); key = cfg_get(p, "smm_api_key")
    if not url or not key: return {"error": "Chưa cấu hình API"}
    data = {"key": key, "action": action}
    data.update({k: v for k, v in params.items() if v is not None})
    try:
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200: return {"error": f"HTTP {r.status_code}"}
        try: return r.json()
        except: return {"error": f"Không phải JSON: {r.text[:100]}"}
    except Exception as e: return {"error": str(e)[:150]}

def api_balance(p): return _api(p, "balance")

def api_services(p):
    url = cfg_get(p, "smm_api_url"); key = cfg_get(p, "smm_api_key")
    if not url or not key: return {"error": "Chưa cấu hình API"}
    try:
        r = requests.post(url, data={"key": key, "action": "services"}, timeout=30)
        if r.status_code != 200: return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        try: return r.json()
        except: return {"error": f"Không phải JSON: {r.text[:200]}"}
    except Exception as e: return {"error": str(e)[:200]}

def api_debug(p):
    url = cfg_get(p, "smm_api_url"); key = cfg_get(p, "smm_api_key")
    if not url or not key: return 0, "", "Chưa cấu hình API"
    try:
        r = requests.post(url, data={"key": key, "action": "services"}, timeout=30)
        body = r.text[:500]
        try: parsed = r.json()
        except: parsed = f"(không parse được JSON) {body[:200]}"
        return r.status_code, body, parsed
    except Exception as e:
        return 0, "", str(e)[:200]

def api_add(p, sid, link, qty): return _api(p, "add", service=sid, link=link, quantity=qty)
def api_status(p, oid): return _api(p, "status", order=oid)


def svc_list(p, platform=None, only_active=True):
    q = "SELECT id,platform,name,api_service,cost,price,min,max,active,custom_price FROM smm_services WHERE 1=1"
    par = []
    if only_active: q += " AND active=1"
    if platform: q += " AND platform=?"; par.append(platform)
    q += " ORDER BY price ASC LIMIT 500"
    return _q(p, q, tuple(par), "all") or []

def svc_get(p, sid):
    r = _q(p, "SELECT id,platform,name,api_service,cost,price,min,max,active,custom_price FROM smm_services WHERE id=?", (sid,), "one")
    if not r: return None
    return dict(zip(["id","platform","name","api_service","cost","price","min","max","active","custom_price"], r))

def svc_add(p, pl, nm, api, cost, price, mn, mx, custom=0):
    sql = "INSERT INTO smm_services (platform,name,api_service,cost,price,min,max,custom_price) VALUES (?,?,?,?,?,?,?,?)"
    return _q(p, sql, (pl, nm, str(api), cost, price, mn, mx, custom))

def svc_update(p, sid, f, v):
    if f not in ("platform","name","api_service","cost","price","min","max","custom_price","active"): return
    _q(p, f"UPDATE smm_services SET {f}=? WHERE id=?", (v, sid))
def svc_del(p, sid): _q(p, "DELETE FROM smm_services WHERE id=?", (sid,))
def svc_toggle(p, sid):
    r = _q(p, "SELECT active FROM smm_services WHERE id=?", (sid,), "one")
    if not r: return None
    new = 0 if r[0] else 1
    _q(p, "UPDATE smm_services SET active=? WHERE id=?", (new, sid))
    return new

def svc_count(p):
    try:
        r = _q(p, "SELECT COUNT(*) FROM smm_services", fetch="one")
        return r[0] if r else 0
    except: return -1

def svc_exists(bp, api_id):
    return _q(bp, "SELECT 1 FROM smm_services WHERE api_service=?", (api_id,), "one") is not None

def platforms_available(p):
    rows = _q(p, "SELECT DISTINCT platform FROM smm_services WHERE active=1", fetch="all")
    return [r[0] for r in rows] or []


def detect_subtype(name):
    low = (name or "").lower()
    for label, _, keys in SUBTYPES:
        if label == "Khác": continue
        for k in keys:
            if k in low: return label
    return "Khác"

def list_subtypes_sold(bp, platform):
    rows = svc_list(bp, platform)
    groups = {}
    for s in rows:
        label = detect_subtype(s[2])
        if label not in groups: groups[label] = {"count": 0, "min": 10**12}
        groups[label]["count"] += 1
        if s[5] < groups[label]["min"]: groups[label]["min"] = s[5]
    out = []
    for label, icon, _ in SUBTYPES:
        if label in groups:
            out.append((label, icon, groups[label]["count"], groups[label]["min"]))
    return out

def svc_in_subtype(bp, platform, subtype):
    rows = svc_list(bp, platform)
    out = [s for s in rows if detect_subtype(s[2]) == subtype]
    out.sort(key=lambda s: s[5])
    return out


# ═══════════ CORE: PHÂN TÍCH GIÁ ═══════════
def _parse_api_rate(raw_rate_val, usd_rate, currency_mode="auto", multiplier=1.0):
    """
    Phân tích giá API thông minh cho subre247:
    - "13.850" (có dấu chấm ngăn nghìn) → 13,850 VNĐ
    - "131.06" (số thập phân, <1000) → 131,060 VNĐ (đơn vị "nghìn đồng")
    - "13850"  (số nguyên >=1000) → 13,850 VNĐ
    - "0.53"   (số thập phân, <1) → USD, nhân tỷ giá
    """
    raw = str(raw_rate_val or "0").strip()
    raw = re.sub(r"[^\d.,]", "", raw)

    is_vnd_format = False  # True nếu là format VNĐ có dấu phân cách nghìn
    if "." in raw:
        # "13.850" hoặc "1.234.567" → thousand separator
        if re.match(r"^\d{1,3}(\.\d{3})+$", raw):
            raw = raw.replace(".", ""); is_vnd_format = True
    if "," in raw and not is_vnd_format:
        # "13,850" → thousand separator (kiểu Mỹ)
        if re.match(r"^\d{1,3}(,\d{3})+$", raw):
            raw = raw.replace(",", ""); is_vnd_format = True

    try: api_rate = float(raw)
    except: api_rate = 0.0

    mode = (currency_mode or "auto").lower()
    mult = float(multiplier or 1)

    if mode == "vnd":
        vnd_price = api_rate * mult
    elif mode == "usd":
        vnd_price = api_rate * usd_rate * mult
    elif mode == "nghin":  # nghìn đồng
        vnd_price = api_rate * 1000 * mult
    else:  # auto - TỰ ĐỘNG NHẬN DIỆN
        if is_vnd_format:
            # Có dấu phân cách nghìn → đã là VNĐ
            vnd_price = api_rate * mult
        elif api_rate >= 1000:
            # Số nguyên lớn → VNĐ
            vnd_price = api_rate * mult
        elif api_rate >= 1:
            # Số thập phân 1..999 → "nghìn đồng", nhân 1000
            vnd_price = api_rate * 1000 * mult
        else:
            # < 1 → USD
            vnd_price = api_rate * usd_rate * mult

    return int(round(vnd_price)), api_rate

def _parse_service(s, rate, markup, currency_mode="auto", multiplier=1.0):
    nm = str(s.get("name") or "Dịch vụ")[:80]
    cat = str(s.get("category") or s.get("type") or "Khác")[:30]

    cost, api_rate = _parse_api_rate(s.get("rate"), rate, currency_mode, multiplier)

    custom_price = int(s.get("custom_price") or 0)
    if custom_price > 0:
        return nm, cat, cost, custom_price, 10, 100000, api_rate

    price = int(round(cost * (1 + markup / 100.0)))
    if price <= 0: price = 1000
    try: mn = int(float(str(s.get("min") or 100).strip()))
    except: mn = 100
    try: mx = int(float(str(s.get("max") or 100000).strip()))
    except: mx = 100000
    return nm, cat, cost, price, mn, mx, api_rate

def _detect_platform(t):
    t = t.lower()
    if "tiktok" in t: return "TikTok"
    if "facebook" in t or "fb" in t: return "Facebook"
    if "instagram" in t or "ins" in t: return "Instagram"
    if "youtube" in t or "ytb" in t: return "YouTube"
    if "shopee" in t: return "Shopee"
    if "telegram" in t: return "Telegram"
    if "twitter" in t: return "Twitter"
    return "Khác"

def _normalize_platform(raw, name, cat):
    if raw:
        p = str(raw).strip()
        for known, _ in PLATFORMS:
            if p.lower() == known.lower(): return known
        return _detect_platform(p + " " + name + " " + cat)
    return _detect_platform(name + " " + cat)

def _norm_cache_platform(s):
    return _normalize_platform(s.get("platform"), str(s.get("name") or ""), str(s.get("category") or ""))


def order_create(p, uid, svc, link, qty, price, api_o, st="pending"):
    return _q(p, "INSERT INTO smm_orders (user_id,service_id,service_name,platform,link,quantity,price,api_order,status) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
              (uid, svc["id"], svc["name"], svc["platform"], link, qty, price, str(api_o), st))
def order_list_user(p, uid, lim=10):
    return _q(p, "SELECT id,service_name,platform,link,quantity,price,status,created_at "
                 "FROM smm_orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, lim), "all") or []
def order_list_all(p, lim=30):
    return _q(p, "SELECT id,user_id,service_name,platform,quantity,price,status,api_order,created_at "
                 "FROM smm_orders ORDER BY id DESC LIMIT ?", (lim,), "all") or []
def order_get(p, oid):
    r = _q(p, "SELECT id,user_id,service_id,service_name,platform,link,quantity,price,api_order,status,note "
              "FROM smm_orders WHERE id=?", (oid,), "one")
    if not r: return None
    return dict(zip(["id","user_id","service_id","service_name","platform","link",
                     "quantity","price","api_order","status","note"], r))
def order_update(p, oid, st, sc=0, rm=0):
    _q(p, "UPDATE smm_orders SET status=?, start_count=?, remains=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
       (st, sc, rm, oid))
def order_refund(p, oid):
    r = order_get(p, oid)
    if not r or r["status"] == "refunded": return False
    _q(p, "UPDATE users SET balance=balance+? WHERE user_id=?", (r["price"], r["user_id"]))
    _q(p, "UPDATE smm_orders SET status='refunded' WHERE id=?", (oid,))
    return True

def status_vi(s): return STATUS_VI.get((s or "").lower().strip(), s or "—")


def register(bot, h):
    fmt = h["fmt"]; cur_admin = h["cur_admin"]; get_user = h["get_user"]
    show = h["show"]; back_markup = h["back_markup"]; user_states = h["user_states"]
    dbp = h["db_path_fn"]
    admin_cb = h.get("admin_cb") or (lambda: "adm_panel")

    def _safe(fn):
        def w(call):
            try:
                try: bot.answer_callback_query(call.id)
                except: pass
                fn(call)
            except Exception as e:
                log.exception("smm err: %s", e)
                try:
                    bot.send_message(call.message.chat.id,
                        f"❌ Lỗi: <code>{html.escape(str(e)[:200])}</code>")
                except: pass
        w.__name__ = getattr(fn, "__name__", "w")
        return w

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "smm_home")
    @_safe
    def _home(call):
        bp = dbp(); plats = platforms_available(bp)
        if not plats:
            show(call, "<b>🔥 BUFF MẠNG XÃ HỘI</b>\n\n⚠️ Chưa có dịch vụ. Liên hệ admin!", back_markup()); return
        m = types.InlineKeyboardMarkup(row_width=2)
        btns = [types.InlineKeyboardButton(f"{i} {p}", callback_data=f"smm_plat|{p}")
                for p, i in PLATFORMS if p in plats]
        if btns: m.add(*btns)
        m.add(types.InlineKeyboardButton("🛍 Đơn của tôi", callback_data="smm_myorders"),
              types.InlineKeyboardButton("🔙 Menu", callback_data="menu_back"))
        show(call, "<b>🔥 BUFF MẠNG XÃ HỘI</b>\n\n<blockquote>⚡ Tim/Follow/View tự động\n"
                   "💰 Trả bằng số dư\n🚀 Nhận ngay trong 30 giây</blockquote>\n\n👇 Chọn nền tảng:", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("smm_plat|"))
    @_safe
    def _plat(call):
        pl = call.data.split("|", 1)[1]
        bp = dbp()
        subs = list_subtypes_sold(bp, pl)
        if not subs:
            show(call, "Chưa có dịch vụ.", back_markup("smm_home")); return
        m = types.InlineKeyboardMarkup(row_width=2)
        total = sum(x[2] for x in subs)
        for label, icon, count, minp in subs:
            m.add(types.InlineKeyboardButton(
                f"{icon} {label} ({count}) – từ {fmt(minp)}đ",
                callback_data=f"smm_sub|{pl}|{label}"))
        m.add(types.InlineKeyboardButton("🔙 Nền tảng", callback_data="smm_home"))
        show(call, f"<b>🎯 {html.escape(pl)}</b>\n\n"
                   f"<blockquote>📊 {total} dịch vụ\n👇 Chọn loại:</blockquote>", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("smm_sub|"))
    @_safe
    def _sub(call):
        parts = call.data.split("|")
        pl = parts[1]; sub = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 0
        bp = dbp()
        svcs = svc_in_subtype(bp, pl, sub)
        if not svcs:
            show(call, "Chưa có dịch vụ.", back_markup(f"smm_plat|{pl}")); return
        per = 10
        tp = max(1, (len(svcs)+per-1)//per)
        page = max(0, min(page, tp-1))
        chunk = svcs[page*per:(page+1)*per]
        m = types.InlineKeyboardMarkup(row_width=1)
        for s in chunk:
            nm = s[2] if len(s[2]) <= 32 else s[2][:31] + "…"
            m.add(types.InlineKeyboardButton(f"{fmt(s[5])}đ/1k · {nm}",
                  callback_data=f"smm_view|{s[0]}"))
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"smm_sub|{pl}|{sub}|{page-1}"))
        nav.append(types.InlineKeyboardButton(f"{page+1}/{tp}", callback_data="noop"))
        if page < tp-1:
            nav.append(types.InlineKeyboardButton("➡️", callback_data=f"smm_sub|{pl}|{sub}|{page+1}"))
        if nav: m.row(*nav)
        m.add(types.InlineKeyboardButton("🔙 Loại khác", callback_data=f"smm_plat|{pl}"))
        show(call, f"<b>🎯 {html.escape(pl)} · {html.escape(sub)}</b>\n\n"
                   f"<blockquote>📊 {len(svcs)} dịch vụ · Giá rẻ → cao\n"
                   f"📄 Trang {page+1}/{tp}</blockquote>", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("smm_view|"))
    @_safe
    def _view(call):
        sid = int(call.data.split("|")[1]); s = svc_get(dbp(), sid)
        if not s: show(call, "Không thấy.", back_markup("smm_home")); return
        sub = detect_subtype(s["name"])
        txt = (f"<b>🎯 {html.escape(s['name'])}</b>\n\n<blockquote>"
               f"📱 {html.escape(s['platform'])} · {html.escape(sub)}\n"
               f"💵 <b>{fmt(s['price'])}đ / 1000</b>\n"
               f"📊 Min: {fmt(s['min'])} · Max: {fmt(s['max'])}</blockquote>")
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🛒 ĐẶT HÀNG", callback_data=f"smm_buy|{sid}"))
        m.add(types.InlineKeyboardButton("🔙", callback_data=f"smm_sub|{s['platform']}|{sub}"))
        show(call, txt, m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("smm_buy|"))
    @_safe
    def _buy(call):
        sid = int(call.data.split("|")[1]); s = svc_get(dbp(), sid)
        if not s: return
        user_states[call.from_user.id] = f"SMM_LINK|{sid}"
        show(call, f"<b>🛒 ĐẶT HÀNG</b>\n\n<blockquote>🎯 {html.escape(s['name'])}\n"
                   f"💵 {fmt(s['price'])}đ/1k</blockquote>\n\n👉 Gửi <b>link</b> vào chat.\n/cancel hủy.",
             back_markup(f"smm_view|{sid}"))

    @bot.message_handler(func=lambda m: m.from_user and
        (user_states.get(m.from_user.id) or "").startswith("SMM_LINK|") and m.text and not m.text.startswith("/"))
    def _gl(m):
        uid = m.from_user.id; raw = user_states.get(uid, "")
        try: sid = int(raw.split("|")[1])
        except: user_states.pop(uid, None); return
        s = svc_get(dbp(), sid)
        if not s: user_states.pop(uid, None); return
        link = m.text.strip()
        if not link.startswith("http"): bot.reply_to(m, "❌ Link phải bắt đầu bằng http"); return
        user_states[uid] = f"SMM_QTY|{sid}|{link}"
        bot.reply_to(m, f"✅ Đã nhận link.\n\n👉 Gửi <b>số lượng</b> ({fmt(s['min'])}–{fmt(s['max'])}).\n/cancel hủy.")

    @bot.message_handler(func=lambda m: m.from_user and
        (user_states.get(m.from_user.id) or "").startswith("SMM_QTY|") and m.text and not m.text.startswith("/"))
    def _gq(m):
        uid = m.from_user.id; raw = user_states.get(uid, "")
        try: _, sid_s, link = raw.split("|", 2); sid = int(sid_s)
        except: user_states.pop(uid, None); return
        s = svc_get(dbp(), sid)
        if not s: user_states.pop(uid, None); return
        try: qty = int(re.sub(r"[^\d]", "", m.text.strip()))
        except: bot.reply_to(m, "❌ Số không hợp lệ"); return
        if qty < s["min"] or qty > s["max"]:
            bot.reply_to(m, f"❌ Phải trong {fmt(s['min'])}–{fmt(s['max'])}"); return
        price = int(round(qty * s["price"] / 1000))
        u = get_user(uid, m.from_user.username or "", m.from_user.first_name or "")
        if u["balance"] < price:
            user_states.pop(uid, None)
            bot.reply_to(m, f"❌ Thiếu tiền.\n💰 Cần {fmt(price)}đ\n🏦 Có {fmt(u['balance'])}đ"); return
        user_states[uid] = f"SMM_OK|{sid}|{link}|{qty}"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ XÁC NHẬN", callback_data=f"smm_do|{sid}|{qty}"),
               types.InlineKeyboardButton("❌ Hủy", callback_data=f"smm_view|{sid}"))
        bot.reply_to(m, f"<b>📋 XÁC NHẬN</b>\n\n<blockquote>🎯 {html.escape(s['name'])}\n"
                        f"🔗 <code>{html.escape(link[:80])}</code>\n📊 {fmt(qty)}\n"
                        f"💵 <b>{fmt(price)}đ</b></blockquote>", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("smm_do|"))
    @_safe
    def _do(call):
        try: _, sid_s, qty_s = call.data.split("|"); sid = int(sid_s); qty = int(qty_s)
        except: return
        uid = call.from_user.id; raw = user_states.get(uid, "")
        if not raw.startswith(f"SMM_OK|{sid}|"):
            bot.send_message(call.message.chat.id, "⚠️ Phiên đã hết hạn, vui lòng đặt lại."); return
        try: _, _, link, _ = raw.split("|", 3)
        except: user_states.pop(uid, None); return
        bp = dbp(); s = svc_get(bp, sid)
        if not s: user_states.pop(uid, None); return
        price = int(round(qty * s["price"] / 1000))
        c = sqlite3.connect(bp, timeout=30)
        try:
            if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                         (price, uid, price)).rowcount == 0:
                c.rollback(); user_states.pop(uid, None)
                bot.send_message(call.message.chat.id, "❌ Số dư không đủ"); return
            c.commit()
        finally: c.close()
        resp = api_add(bp, s["api_service"], link, qty)
        if isinstance(resp, dict) and resp.get("error"):
            c = sqlite3.connect(bp, timeout=30)
            try:
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (price, uid)); c.commit()
            finally: c.close()
            user_states.pop(uid, None)
            bot.edit_message_text(f"❌ LỖI: {html.escape(str(resp['error'])[:150])}\n💸 Đã hoàn {fmt(price)}đ",
                call.message.chat.id, call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Thử lại", callback_data=f"smm_view|{sid}")))
            return
        api_o = str(resp.get("order") or resp.get("order_id") or "—") if isinstance(resp, dict) else "—"
        try:
            oid = order_create(bp, uid, s, link, qty, price, api_o, "processing")
        except Exception as e:
            log.exception("order_create fail: %s", e)
            user_states.pop(uid, None)
            try:
                bot.send_message(cur_admin(),
                    f"🚨 <b>LỖI GHI ĐƠN SMM</b>\nUser <code>{uid}</code> đã bị trừ {fmt(price)}đ\n"
                    f"🎯 {html.escape(s['name'])}\n📊 {fmt(qty)}\n🔗 <code>{html.escape(link[:80])}</code>\n"
                    f"🆔 Mã đơn NCC: <code>{html.escape(api_o)}</code>")
            except: pass
            bot.send_message(call.message.chat.id,
                "⚠️ Đơn đã gửi đi nhưng hệ thống ghi nhận lỗi. Admin đã được báo, vui lòng liên hệ hỗ trợ.")
            return
        user_states.pop(uid, None)
        u = get_user(uid, call.from_user.username or "", call.from_user.first_name or "")
        bot.edit_message_text(f"<b>🎉 ĐẶT HÀNG OK!</b>\n\n<blockquote>🧾 #{oid}\n"
            f"🎯 {html.escape(s['name'])}\n📊 {fmt(qty)} | 💵 {fmt(price)}đ\n"
            f"🏦 Còn: <b>{fmt(u['balance'])}đ</b></blockquote>\n⏳ Đang xử lý...",
            call.message.chat.id, call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("🛍 Đơn của tôi", callback_data="smm_myorders"),
                types.InlineKeyboardButton("🔙 Menu", callback_data="menu_back")))
        try:
            bot.send_message(cur_admin(), f"🔥 ĐƠN BUFF #{oid}\n<code>{uid}</code>\n"
                f"🎯 {html.escape(s['name'])}\n📊 {fmt(qty)} | {fmt(price)}đ")
        except: pass

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "smm_myorders")
    @_safe
    def _myo(call):
        rows = order_list_user(dbp(), call.from_user.id, 15)
        if not rows:
            show(call, "<b>🛍 ĐƠN BUFF</b>\n\nChưa có đơn.", back_markup("smm_home")); return
        m = types.InlineKeyboardMarkup(row_width=1)
        for r in rows[:10]:
            m.add(types.InlineKeyboardButton(f"#{r[0]} {status_vi(r[6])[:18]} – {fmt(r[4])}",
                  callback_data=f"smm_ov|{r[0]}"))
        m.add(types.InlineKeyboardButton("🔙", callback_data="smm_home"))
        show(call, f"<b>🛍 ĐƠN BUFF ({len(rows)})</b>", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("smm_ov|"))
    @_safe
    def _ov(call):
        oid = int(call.data.split("|")[1]); bp = dbp(); r = order_get(bp, oid)
        if not r or r["user_id"] != call.from_user.id:
            show(call, "Không thấy.", back_markup("smm_myorders")); return
        if r["api_order"] and r["status"] not in ("completed","refunded","canceled"):
            try:
                resp = api_status(bp, r["api_order"])
                if isinstance(resp, dict) and not resp.get("error") and resp.get("status"):
                    order_update(bp, oid, (resp.get("status") or "").lower(),
                        int(resp.get("start_count") or 0), int(resp.get("remains") or 0))
                    r = order_get(bp, oid)
            except: pass
        show(call, f"<b>🧾 ĐƠN #{oid}</b>\n\n<blockquote>🎯 {html.escape(r['service_name'])}\n"
                   f"🔗 <code>{html.escape(r['link'][:70])}</code>\n📊 {fmt(r['quantity'])}\n"
                   f"💵 {fmt(r['price'])}đ\n📌 <b>{status_vi(r['status'])}</b></blockquote>",
             back_markup("smm_myorders"))

    # ═══════════ ADMIN ═══════════
    def _adm_menu(call, note=""):
        bp = dbp()
        n = svc_count(bp)
        ccount = cfg_get(bp, "smm_cache_count", "0")
        ctime = cfg_get(bp, "smm_cache_time", "—")
        api_url = cfg_get(bp, "smm_api_url", "—") or "—"
        key = cfg_get(bp, "smm_api_key", "")
        kd = (key[:6]+"***") if len(key)>10 else ("(chưa set)" if not key else "***")
        curr = _get_currency(bp); mult = _get_mult(bp)
        txt = (f"<b>🔥 BUFF SMM (ADMIN)</b>\n\n"
               + (f"<blockquote>{note}</blockquote>\n\n" if note else "")
               + f"<blockquote>🌐 API: <code>{html.escape(api_url[:50])}</code>\n"
                 f"🔑 Key: <code>{html.escape(kd)}</code>\n"
                 f"💵 Tỷ giá: <b>{fmt(_get_rate(bp))}đ/USD</b> · 📈 Lãi: <b>{_get_markup(bp)}%</b>\n"
                 f"💱 Tiền tệ: <b>{curr.upper()}</b> · ✖️ Hệ số: <b>{mult:g}</b>\n"
                 f"📦 Đang bán: <b>{n}</b> DV\n"
                 f"📥 Cache: <b>{ccount}</b> DV · {ctime}</blockquote>")
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("📥 Chọn DV để bán", callback_data="adm_pick_menu"),
              types.InlineKeyboardButton("🔄 Tải DS từ API", callback_data="adm_smm_fetch"),
              types.InlineKeyboardButton("📦 DV đang bán", callback_data="adm_smm_list"),
              types.InlineKeyboardButton("💰 Giá & Lãi", callback_data="adm_smm_price"),
              types.InlineKeyboardButton("🔄 TÍNH LẠI TẤT CẢ GIÁ", callback_data="adm_smm_recalc"),
              types.InlineKeyboardButton("⚙️ Cấu hình API", callback_data="adm_smm_cfg"),
              types.InlineKeyboardButton("🧾 Đơn hàng", callback_data="adm_smm_orders"),
              types.InlineKeyboardButton("💵 Số dư API", callback_data="adm_smm_bal"),
              types.InlineKeyboardButton("🔍 Debug API", callback_data="adm_smm_debug"),
              types.InlineKeyboardButton("➕ Thêm 1 DV thủ công", callback_data="adm_smm_add"),
              types.InlineKeyboardButton("🧹 Xóa TẤT CẢ DV", callback_data="adm_smm_wipe"),
              types.InlineKeyboardButton("🗑️ Xóa cache API", callback_data="adm_smm_cachewipe"),
              types.InlineKeyboardButton("🔙 Admin", callback_data=admin_cb()))
        show(call, txt, m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm")
    @_safe
    def _adm(call):
        if call.from_user.id != cur_admin(): return
        _adm_menu(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_fetch")
    @_safe
    def _fetch(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        if not cfg_get(bp, "smm_api_url") or not cfg_get(bp, "smm_api_key"):
            show(call, "⚠️ Chưa cấu hình API.", back_markup("adm_smm_cfg")); return
        resp = api_services(bp)
        if isinstance(resp, dict) and "error" in resp:
            show(call, f"❌ <b>API BÁO LỖI</b>\n\n<code>{html.escape(str(resp['error'])[:300])}</code>",
                 back_markup("adm_smm")); return
        if not isinstance(resp, list):
            show(call, f"❌ API trả về <b>{type(resp).__name__}</b>, không phải LIST.", back_markup("adm_smm")); return
        if not resp:
            show(call, "⚠️ API trả về rỗng.", back_markup("adm_smm")); return
        cache_save(bp, resp)
        _pick_menu(call, f"✅ Đã tải {len(resp)} DV vào cache")

    def _pick_menu(call, note=""):
        bp = dbp()
        services, t = cache_load(bp)
        if not services:
            show(call, "⚠️ Cache trống. Bấm <b>🔄 Tải DS từ API</b> trước.",
                 back_markup("adm_smm")); return
        groups = {}
        for s in services:
            if not isinstance(s, dict): continue
            pl = _norm_cache_platform(s)
            groups[pl] = groups.get(pl, 0) + 1
        m = types.InlineKeyboardMarkup(row_width=1)
        for pl, icon in PLATFORMS:
            if pl in groups:
                m.add(types.InlineKeyboardButton(f"{icon} {pl} ({groups[pl]})",
                      callback_data=f"adm_pick_plat|{pl}"))
        m.add(types.InlineKeyboardButton("🔄 Tải lại từ API", callback_data="adm_smm_fetch"))
        m.add(types.InlineKeyboardButton("🔙 Admin SMM", callback_data="adm_smm"))
        show(call, f"<b>📥 CHỌN DV TỪ API</b>\n\n"
                   + (f"<blockquote>{note}</blockquote>\n\n" if note else "")
                   + f"<blockquote>📊 Cache: <b>{len(services)}</b> DV\n🕐 {t}\n"
                     f"💼 Đang bán: <b>{svc_count(bp)}</b> DV</blockquote>\n\n"
                     "👇 Chọn nền tảng để xem:", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_pick_menu")
    @_safe
    def _pick_menu_entry(call):
        if call.from_user.id != cur_admin(): return
        _pick_menu(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_pick_plat|"))
    @_safe
    def _pick_plat(call):
        if call.from_user.id != cur_admin(): return
        pl = call.data.split("|", 1)[1]
        bp = dbp()
        services, _ = cache_load(bp)
        if not services: show(call, "Cache trống.", back_markup("adm_smm")); return
        subs = {}
        for s in services:
            if not isinstance(s, dict): continue
            if _norm_cache_platform(s) != pl: continue
            sub = detect_subtype(str(s.get("name") or ""))
            subs[sub] = subs.get(sub, 0) + 1
        m = types.InlineKeyboardMarkup(row_width=2)
        for label, icon, _ in SUBTYPES:
            if label in subs:
                m.add(types.InlineKeyboardButton(f"{icon} {label} ({subs[label]})",
                      callback_data=f"adm_pick_sub|{pl}|{label}"))
        m.add(types.InlineKeyboardButton("🔙 Chọn nền tảng", callback_data="adm_pick_menu"))
        show(call, f"<b>📥 {pl}</b>\n\n👇 Chọn loại:", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_pick_sub|"))
    @_safe
    def _pick_sub(call):
        if call.from_user.id != cur_admin(): return
        parts = call.data.split("|")
        pl = parts[1]; sub = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 0
        bp = dbp()
        services, _ = cache_load(bp)
        if not services: show(call, "Cache trống.", back_markup("adm_smm")); return
        matched = []
        for s in services:
            if not isinstance(s, dict): continue
            if _norm_cache_platform(s) != pl: continue
            if detect_subtype(str(s.get("name") or "")) != sub: continue
            matched.append(s)
        matched.sort(key=lambda x: x.get("rate", 0))
        per = 8
        tp = max(1, (len(matched)+per-1)//per)
        page = max(0, min(page, tp-1))
        chunk = matched[page*per:(page+1)*per]
        rate = _get_rate(bp); curr = _get_currency(bp); mult = _get_mult(bp)
        m = types.InlineKeyboardMarkup(row_width=1)
        for s in chunk:
            api_id = str(s.get("service") or s.get("id") or "").strip()
            nm = str(s.get("name") or "")[:30]
            cost_vnd, _ = _parse_api_rate(s.get("rate"), rate, curr, mult)
            icon = "✅" if svc_exists(bp, api_id) else "➕"
            m.add(types.InlineKeyboardButton(f"{icon} {fmt(cost_vnd)}đ · {nm}",
                  callback_data=f"adm_pick_do|{api_id}|{pl}|{sub}|{page}"))
        nav = []
        if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm_pick_sub|{pl}|{sub}|{page-1}"))
        nav.append(types.InlineKeyboardButton(f"{page+1}/{tp}", callback_data="noop"))
        if page < tp-1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm_pick_sub|{pl}|{sub}|{page+1}"))
        if nav: m.row(*nav)
        m.add(types.InlineKeyboardButton("➕ Thêm TẤT CẢ loại này",
              callback_data=f"adm_pick_all|{pl}|{sub}"))
        m.add(types.InlineKeyboardButton("🔙", callback_data=f"adm_pick_plat|{pl}"))
        show(call, f"<b>📥 {pl} · {sub}</b>\n\n"
                   f"<blockquote>📊 {len(matched)} DV · Trang {page+1}/{tp}\n"
                   f"💡 Bấm để thêm DV</blockquote>", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_pick_do|"))
    @_safe
    def _pick_do(call):
        if call.from_user.id != cur_admin(): return
        parts = call.data.split("|")
        api_id = parts[1]; pl = parts[2]; sub = parts[3]
        page = int(parts[4]) if len(parts) > 4 else 0
        bp = dbp()
        services, _ = cache_load(bp)
        found = None
        for s in services:
            if not isinstance(s, dict): continue
            sid = str(s.get("service") or s.get("id") or "").strip()
            if sid == api_id: found = s; break
        if not found:
            bot.send_message(call.message.chat.id, "❌ Không tìm thấy DV trong cache."); return
        if not svc_exists(bp, api_id):
            rate = _get_rate(bp); markup = _get_markup(bp)
            nm, cat, cost, price, mn, mx, _ = _parse_service(found, rate, markup, _get_currency(bp), _get_mult(bp))
            svc_add(bp, pl, nm, api_id, cost, price, mn, mx)
        call.data = f"adm_pick_sub|{pl}|{sub}|{page}"
        _pick_sub(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_pick_all|"))
    @_safe
    def _pick_all(call):
        if call.from_user.id != cur_admin(): return
        parts = call.data.split("|")
        pl = parts[1]; sub = parts[2]
        bp = dbp()
        services, _ = cache_load(bp)
        if not services: show(call, "Cache trống.", back_markup("adm_smm")); return
        rate = _get_rate(bp); markup = _get_markup(bp); curr = _get_currency(bp); mult = _get_mult(bp)
        added = 0; sk = 0
        for s in services:
            if not isinstance(s, dict): continue
            if _norm_cache_platform(s) != pl: continue
            if detect_subtype(str(s.get("name") or "")) != sub: continue
            api_id = str(s.get("service") or s.get("id") or "").strip()
            if not api_id: sk += 1; continue
            if svc_exists(bp, api_id): sk += 1; continue
            try:
                nm, cat, cost, price, mn, mx, _ = _parse_service(s, rate, markup, curr, mult)
                svc_add(bp, pl, nm, api_id, cost, price, mn, mx)
                added += 1
            except Exception as e:
                log.warning("pick_all: %s", e); sk += 1
        show(call, f"✅ Đã thêm <b>{added}</b> DV\n⏭ Bỏ qua: {sk}",
             back_markup(f"adm_pick_sub|{pl}|{sub}"))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_recalc")
    @_safe
    def _recalc(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        services, _ = cache_load(bp)
        if not services:
            show(call, "⚠️ Cache trống. Bấm 🔄 Tải DS từ API trước.", back_markup("adm_smm")); return
        rate = _get_rate(bp); markup = _get_markup(bp); curr = _get_currency(bp); mult = _get_mult(bp)
        cache_map = {str(s.get("service") or s.get("id") or "").strip(): s for s in services if isinstance(s, dict)}
        rows = _q(bp, "SELECT id, api_service FROM smm_services", fetch="all") or []
        updated = 0; skipped = 0; unlocked = 0
        for sid, api_id in rows:
            found = cache_map.get(str(api_id).strip())
            if not found: skipped += 1; continue
            try:
                nm, cat, cost, price, mn, mx, _ = _parse_service(found, rate, markup, curr, mult)
                # Xóa custom_price để tính lại toàn bộ
                svc_update(bp, sid, "custom_price", 0)
                svc_update(bp, sid, "cost", cost)
                svc_update(bp, sid, "price", price)
                updated += 1
                unlocked += 1
            except Exception as e:
                log.warning("recalc %s: %s", sid, e); skipped += 1
        _adm_menu(call, f"✅ Đã tính lại giá cho <b>{updated}</b> DV\n"
                       f"🔓 Đã mở khóa giá cứng: <b>{unlocked}</b>\n"
                       f"⏭ Bỏ qua: <b>{skipped}</b>")

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_wipe")
    @_safe
    def _wipe(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        n = svc_count(bp)
        if n <= 0:
            _adm_menu(call, "ℹ️ DB không có DV nào."); return
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ XOÁ HẾT", callback_data="adm_smm_wipeok"),
               types.InlineKeyboardButton("❌ Hủy", callback_data="adm_smm"))
        show(call, f"⚠️ <b>XOÁ TẤT CẢ {n} DỊCH VỤ?</b>\n\n🚨 <b>KHÔNG THỂ HOÀN TÁC</b>!", kb)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_wipeok")
    @_safe
    def _wipeok(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        n = svc_count(bp)
        _q(bp, "DELETE FROM smm_services")
        _adm_menu(call, f"✅ Đã xoá <b>{n}</b> dịch vụ.")

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_cachewipe")
    @_safe
    def _cachewipe(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        ccount = cfg_get(bp, "smm_cache_count", "0")
        cache_clear(bp)
        _adm_menu(call, f"✅ Đã xoá cache API ({ccount} DV).")

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_cfg")
    @_safe
    def _cfg(call):
        if call.from_user.id != cur_admin(): return
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🌐 Đổi URL", callback_data="adm_smm_set|smm_api_url"),
              types.InlineKeyboardButton("🔑 Đổi Key", callback_data="adm_smm_set|smm_api_key"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm"))
        show(call, "<b>⚙️ CẤU HÌNH API</b>\n\nURL: <code>https://subre247.com/api/v2</code>", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_price")
    @_safe
    def _price_menu(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        curr = _get_currency(bp)
        curr_icon = {"auto":"🔄 Tự động","vnd":"🇻🇳 VNĐ","usd":"🇺🇸 USD","nghin":"💯 Nghìn đồng"}.get(curr, curr)
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton(f"💵 Tỷ giá: {fmt(_get_rate(bp))}đ/USD",
              callback_data="adm_smm_set|smm_usd_rate"),
              types.InlineKeyboardButton(f"📈 Lãi: {_get_markup(bp)}%",
              callback_data="adm_smm_set|smm_markup_pct"),
              types.InlineKeyboardButton(f"💱 Tiền tệ API: {curr_icon}",
              callback_data="adm_smm_curr"),
              types.InlineKeyboardButton(f"✖️ Hệ số nhân: {_get_mult(bp):g}",
              callback_data="adm_smm_set|smm_rate_multiplier"),
              types.InlineKeyboardButton("🔄 Tính lại TẤT CẢ giá", callback_data="adm_smm_recalc"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm"))
        show(call, "<b>💰 CẤU HÌNH GIÁ</b>\n\n"
                   "<b>💡 Với subre247:</b>\n"
                   "• Tiền tệ: <b>🔄 Tự động</b> (khuyên dùng)\n"
                   "• Hệ số nhân: <b>1</b>\n"
                   "• Lãi: tuỳ bạn\n\n"
                   "Bot tự nhận diện: 131.06 → 131,060đ, 13.850 → 13,850đ.", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_curr")
    @_safe
    def _curr_menu(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp(); curr = _get_currency(bp)
        m = types.InlineKeyboardMarkup(row_width=1)
        for code, label in [("auto","🔄 Tự động (khuyên dùng)"),
                            ("vnd","🇻🇳 VNĐ (giá đã là VNĐ)"),
                            ("nghin","💯 Nghìn đồng (VD 131.06 = 131,060đ)"),
                            ("usd","🇺🇸 USD")]:
            mark = "✅ " if curr == code else ""
            m.add(types.InlineKeyboardButton(f"{mark}{label}", callback_data=f"adm_smm_currset|{code}"))
        m.add(types.InlineKeyboardButton("🔙", callback_data="adm_smm_price"))
        show(call, "<b>💱 CHỌN ĐƠN VỊ TIỀN TỆ API</b>\n\n"
                   "Với subre247, chọn <b>🔄 Tự động</b> là chuẩn nhất.", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_currset|"))
    @_safe
    def _currset(call):
        if call.from_user.id != cur_admin(): return
        code = call.data.split("|", 1)[1]
        if code not in ("auto","vnd","usd","nghin"): return
        cfg_set(dbp(), "smm_currency_mode", code)
        bot.answer_callback_query(call.id, f"✅ Đã đặt: {code.upper()}")
        call.data = "adm_smm_price"; _price_menu(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_set|"))
    @_safe
    def _setc(call):
        if call.from_user.id != cur_admin(): return
        k = call.data.split("|", 1)[1]
        if k not in ("smm_api_url", "smm_api_key", "smm_usd_rate", "smm_markup_pct", "smm_rate_multiplier"): return
        user_states[call.from_user.id] = f"SMM_CFG|{k}"
        hints = {"smm_api_url":"https://subre247.com/api/v2","smm_api_key":"API Key",
                 "smm_usd_rate":"26000","smm_markup_pct":"30",
                 "smm_rate_multiplier":"1 (mặc định)"}
        show(call, f"Nhập giá trị mới cho <code>{k}</code>.\n<i>{hints.get(k,'')}</i>\n/cancel hủy.",
             back_markup("adm_smm_price" if k in ("smm_usd_rate","smm_markup_pct","smm_rate_multiplier") else "adm_smm_cfg"))

    @bot.message_handler(func=lambda m: m.from_user and m.from_user.id == cur_admin() and
        (user_states.get(m.from_user.id) or "").startswith("SMM_CFG|") and m.text and not m.text.startswith("/"))
    def _cfg_in(m):
        raw = user_states.get(m.from_user.id, "")
        try: k = raw.split("|", 1)[1]
        except: user_states.pop(m.from_user.id, None); return
        cfg_set(dbp(), k, m.text.strip())
        user_states.pop(m.from_user.id, None)
        back = "adm_smm_price" if k in ("smm_usd_rate","smm_markup_pct","smm_rate_multiplier") else "adm_smm_cfg"
        bot.reply_to(m, f"✅ Đã lưu <code>{k}</code>.\n\n💡 Bấm <b>🔄 Tính lại TẤT CẢ giá</b> để áp dụng.",
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("🔄 Tính lại giá", callback_data="adm_smm_recalc"),
                types.InlineKeyboardButton("🔙 Quay lại", callback_data=back)))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_bal")
    @_safe
    def _bal(call):
        if call.from_user.id != cur_admin(): return
        show(call, f"<b>💰 SỐ DƯ API</b>\n\n<blockquote>{html.escape(str(api_balance(dbp()))[:300])}</blockquote>",
             back_markup("adm_smm"))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_debug")
    @_safe
    def _debug(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        code, body, parsed = api_debug(bp)
        url = cfg_get(bp, "smm_api_url", "(trống)")
        key = cfg_get(bp, "smm_api_key", "")
        kd = (key[:8] + "***") if len(key) > 10 else ("(trống)" if not key else "***")
        if isinstance(parsed, list):
            info = f"LIST {len(parsed)} phần tử"
            if parsed and isinstance(parsed[0], dict):
                sample = parsed[0]
                info += f"\n<b>Rate mẫu:</b> <code>{html.escape(str(sample.get('rate')))}</code>"
                cost, _ = _parse_api_rate(sample.get('rate'), _get_rate(bp), _get_currency(bp), _get_mult(bp))
                info += f"\n<b>→ Bot hiểu là:</b> <code>{fmt(cost)}đ/1k</code>"
        elif isinstance(parsed, dict):
            info = f"DICT {len(parsed)} keys"
        else:
            info = f"Type: {type(parsed).__name__}"
        show(call, f"<b>🔍 DEBUG API</b>\n\n<blockquote>"
                   f"🔗 <code>{html.escape(url)}</code>\n"
                   f"🔑 <code>{html.escape(kd)}</code>\n"
                   f"📡 HTTP: <b>{code}</b>\n📊 {info}</blockquote>\n\n"
                   f"<b>📄 Raw:</b>\n<code>{html.escape(str(body)[:300])}</code>",
             back_markup("adm_smm"))

    def _show_svc(call, page=0):
        bp = dbp(); svcs = svc_list(bp, only_active=False)
        per = 8; tp = max(1, (len(svcs)+per-1)//per); page = max(0, min(page, tp-1))
        chunk = svcs[page*per:(page+1)*per]
        m = types.InlineKeyboardMarkup(row_width=1)
        for s in chunk:
            icon = "✅" if s[8] else "⛔"
            lock = "🔒" if int(s[9] or 0) > 0 else ""
            nm = s[2] if len(s[2]) <= 26 else s[2][:25] + "…"
            m.add(types.InlineKeyboardButton(f"{icon}{lock} #{s[0]} {s[1]} | {nm} – {fmt(s[5])}đ",
                  callback_data=f"adm_smm_sv|{s[0]}"))
        nav = []
        if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm_smm_pg|{page-1}"))
        nav.append(types.InlineKeyboardButton(f"{page+1}/{tp}", callback_data="noop"))
        if page < tp-1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm_smm_pg|{page+1}"))
        if nav: m.row(*nav)
        m.add(types.InlineKeyboardButton("🔄 Tính lại TẤT CẢ giá", callback_data="adm_smm_recalc"),
              types.InlineKeyboardButton("📥 Chọn thêm DV", callback_data="adm_pick_menu"),
              types.InlineKeyboardButton("🔙 Admin SMM", callback_data="adm_smm"))
        show(call, f"<b>📦 DV ĐANG BÁN</b>\n\n{len(svcs)} dịch vụ | Trang {page+1}/{tp}\n"
                   f"<i>🔒 = có giá cứng, sẽ không bị tính lại</i>", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_list")
    @_safe
    def _list(call):
        if call.from_user.id != cur_admin(): return
        _show_svc(call, 0)
    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_pg|"))
    @_safe
    def _pg(call):
        if call.from_user.id != cur_admin(): return
        _show_svc(call, int(call.data.split("|")[1]))

    def _sv_impl(call):
        sid = int(call.data.split("|")[1]); s = svc_get(dbp(), sid)
        if not s: show(call, "Không thấy.", back_markup("adm_smm_list")); return
        profit = s["price"] - s["cost"]
        pct = round(profit*100/s["cost"]) if s["cost"] else 0
        sub = detect_subtype(s["name"])
        is_custom = "🔒 " if int(s.get("custom_price") or 0) > 0 else ""
        txt = (f"<b>📦 DV #{sid}</b>\n\n<blockquote>📱 {html.escape(s['platform'])} · {html.escape(sub)}\n"
               f"📝 {html.escape(s['name'])}\n"
               f"🆔 <code>{html.escape(s['api_service'])}</code>\n"
               f"💵 Nhập: <b>{fmt(s['cost'])}đ</b>/1k\n"
               f"💰 Bán: <b>{fmt(s['price'])}đ</b>/1k {is_custom}\n"
               f"📈 Lãi: <b>{fmt(profit)}đ</b> ({pct}%)\n"
               f"📊 {fmt(s['min'])} – {fmt(s['max'])}\n🔖 {'✅' if s['active'] else '⛔'}</blockquote>")
        m = types.InlineKeyboardMarkup(row_width=2)
        m.add(types.InlineKeyboardButton("✏️ Tên", callback_data=f"adm_smm_ed|{sid}|name"),
              types.InlineKeyboardButton("💰 Sửa giá bán", callback_data=f"adm_smm_ed|{sid}|custom_price"))
        m.add(types.InlineKeyboardButton("📊 Min", callback_data=f"adm_smm_ed|{sid}|min"),
              types.InlineKeyboardButton("📊 Max", callback_data=f"adm_smm_ed|{sid}|max"))
        if int(s.get("custom_price") or 0) > 0:
            m.add(types.InlineKeyboardButton("🔄 Tính lại tự động", callback_data=f"adm_smm_reset|{sid}"))
        m.add(types.InlineKeyboardButton("⛔ Tắt" if s["active"] else "✅ Bật",
              callback_data=f"adm_smm_tg|{sid}"))
        m.add(types.InlineKeyboardButton("🗑️ XOÁ", callback_data=f"adm_smm_dl|{sid}"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm_list"))
        show(call, txt, m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_sv|"))
    @_safe
    def _sv(call):
        if call.from_user.id != cur_admin(): return
        _sv_impl(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_ed|"))
    @_safe
    def _ed(call):
        if call.from_user.id != cur_admin(): return
        _, sid, f = call.data.split("|")
        if f not in ("name", "price", "min", "max", "custom_price"): return
        user_states[call.from_user.id] = f"SMM_ED|{sid}|{f}"
        hint = "\n\n💡 Nhập 0 để quay về tính giá tự động." if f == "custom_price" else ""
        show(call, f"Nhập <code>{f}</code> mới cho #{sid}.{hint}\n/cancel hủy.", back_markup(f"adm_smm_sv|{sid}"))

    @bot.message_handler(func=lambda m: m.from_user and m.from_user.id == cur_admin() and
        (user_states.get(m.from_user.id) or "").startswith("SMM_ED|") and m.text and not m.text.startswith("/"))
    def _ed_in(m):
        raw = user_states.get(m.from_user.id, "")
        try: _, sid_s, f = raw.split("|"); sid = int(sid_s)
        except: user_states.pop(m.from_user.id, None); return
        v = m.text.strip()
        if f in ("price","cost","min","max","custom_price"):
            try: v = int(re.sub(r"[^\d]", "", v))
            except: bot.reply_to(m, "❌ Phải là số"); return
        svc_update(dbp(), sid, f, v)
        user_states.pop(m.from_user.id, None)
        bot.reply_to(m, "✅ Đã sửa.", reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
            types.InlineKeyboardButton("👁 Xem", callback_data=f"adm_smm_sv|{sid}"),
            types.InlineKeyboardButton("🔙 DS", callback_data="adm_smm_list")))

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_reset|"))
    @_safe
    def _reset(call):
        if call.from_user.id != cur_admin(): return
        sid = int(call.data.split("|")[1])
        bp = dbp(); s = svc_get(bp, sid)
        if not s: return
        services, _ = cache_load(bp)
        api_id = s["api_service"]
        found = next((x for x in services if str(x.get("service") or x.get("id") or "").strip() == api_id), None)
        if found:
            rate = _get_rate(bp); markup = _get_markup(bp); curr = _get_currency(bp); mult = _get_mult(bp)
            nm, cat, cost, price, mn, mx, _ = _parse_service(found, rate, markup, curr, mult)
            svc_update(bp, sid, "custom_price", 0)
            svc_update(bp, sid, "cost", cost)
            svc_update(bp, sid, "price", price)
            bot.answer_callback_query(call.id, "✅ Đã tính lại giá tự động")
        else:
            bot.answer_callback_query(call.id, "❌ Không tìm thấy DV trong cache")
        call.data = f"adm_smm_sv|{sid}"; _sv_impl(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_tg|"))
    @_safe
    def _tg(call):
        if call.from_user.id != cur_admin(): return
        sid = int(call.data.split("|")[1]); svc_toggle(dbp(), sid)
        call.data = f"adm_smm_sv|{sid}"; _sv_impl(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_dl|"))
    @_safe
    def _dl(call):
        if call.from_user.id != cur_admin(): return
        sid = int(call.data.split("|")[1])
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ XOÁ", callback_data=f"adm_smm_dlok|{sid}"),
               types.InlineKeyboardButton("❌", callback_data=f"adm_smm_sv|{sid}"))
        show(call, f"⚠️ Xoá DV #{sid}?", kb)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_dlok|"))
    @_safe
    def _dlok(call):
        if call.from_user.id != cur_admin(): return
        svc_del(dbp(), int(call.data.split("|")[1])); _show_svc(call, 0)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_add")
    @_safe
    def _add(call):
        if call.from_user.id != cur_admin(): return
        user_states[call.from_user.id] = "SMM_ADD"
        show(call, "<b>➕ THÊM DV</b>\n\n<code>Nền tảng | Tên | API_ID | giá_nhập | giá_bán | min | max</code>\n\n"
                   "VD: <code>TikTok | Tim VN | 1234 | 5000 | 8000 | 100 | 100000</code>\n/cancel hủy.",
             back_markup("adm_smm"))

    @bot.message_handler(func=lambda m: m.from_user and m.from_user.id == cur_admin() and
        user_states.get(m.from_user.id) == "SMM_ADD" and m.text and not m.text.startswith("/"))
    def _add_in(m):
        f = [x.strip() for x in m.text.split("|")]
        if len(f) < 7: bot.reply_to(m, "❌ Cần 7 phần"); return
        try:
            cost = int(re.sub(r"[^\d]","",f[3])); price = int(re.sub(r"[^\d]","",f[4]))
            mn = int(re.sub(r"[^\d]","",f[5])); mx = int(re.sub(r"[^\d]","",f[6]))
        except: bot.reply_to(m, "❌ Số sai"); return
        sid = svc_add(dbp(), f[0], f[1][:80], f[2], cost, price, mn, mx)
        user_states.pop(m.from_user.id, None)
        bot.reply_to(m, f"✅ Đã thêm #{sid}.", reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
            types.InlineKeyboardButton("👁 Xem", callback_data=f"adm_smm_sv|{sid}"),
            types.InlineKeyboardButton("➕ Nữa", callback_data="adm_smm_add")))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_orders")
    @_safe
    def _ords(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp(); rows = order_list_all(bp, 30)
        if not rows: show(call, "Chưa có đơn.", back_markup("adm_smm")); return
        m = types.InlineKeyboardMarkup(row_width=1)
        for r in rows[:15]:
            m.add(types.InlineKeyboardButton(f"#{r[0]} {status_vi(r[6])[:18]} – {fmt(r[4])}",
                  callback_data=f"adm_smm_ov|{r[0]}"))
        m.add(types.InlineKeyboardButton("🔄 Refresh all", callback_data="adm_smm_ref"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm"))
        show(call, f"<b>🧾 ĐƠN BUFF ({len(rows)})</b>", m)

    def _ov_admin_impl(call):
        oid = int(call.data.split("|")[1]); bp = dbp(); r = order_get(bp, oid)
        if not r: show(call, "Không thấy.", back_markup("adm_smm_orders")); return
        if r["api_order"] and r["status"] not in ("completed","refunded","canceled"):
            resp = api_status(bp, r["api_order"])
            if isinstance(resp, dict) and not resp.get("error") and resp.get("status"):
                order_update(bp, oid, (resp.get("status") or "").lower(),
                    int(resp.get("start_count") or 0), int(resp.get("remains") or 0))
                r = order_get(bp, oid)
        txt = (f"<b>🧾 ĐƠN #{oid}</b>\n\n<blockquote>👤 <code>{r['user_id']}</code>\n"
               f"🎯 {html.escape(r['service_name'])}\n🔗 <code>{html.escape(r['link'][:70])}</code>\n"
               f"📊 {fmt(r['quantity'])} | {fmt(r['price'])}đ\n📌 <b>{status_vi(r['status'])}</b></blockquote>")
        m = types.InlineKeyboardMarkup(row_width=2)
        m.add(types.InlineKeyboardButton("🔄 Refresh", callback_data=f"adm_smm_ov|{oid}"),
              types.InlineKeyboardButton("💸 Hoàn tiền", callback_data=f"adm_smm_rf|{oid}"))
        m.add(types.InlineKeyboardButton("🔙", callback_data="adm_smm_orders"))
        show(call, txt, m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_ov|"))
    @_safe
    def _ov_admin(call):
        if call.from_user.id != cur_admin(): return
        _ov_admin_impl(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_rf|"))
    @_safe
    def _rf(call):
        if call.from_user.id != cur_admin(): return
        oid = int(call.data.split("|")[1]); bp = dbp(); r = order_get(bp, oid)
        if not r: return
        if order_refund(bp, oid):
            try: bot.send_message(r["user_id"], f"💸 Đã hoàn <b>{fmt(r['price'])}đ</b> cho đơn #{oid}.")
            except: pass
        call.data = f"adm_smm_ov|{oid}"; _ov_admin_impl(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_ref")
    @_safe
    def _ref(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp(); rows = order_list_all(bp, 50); n = 0
        for r in rows:
            oid, uid, nm, pl, qty, price, st, ao, cat = r
            if st in ("completed","refunded","canceled") or not ao or ao == "—": continue
            resp = api_status(bp, ao)
            if isinstance(resp, dict) and not resp.get("error") and resp.get("status"):
                order_update(bp, oid, (resp.get("status") or "").lower(),
                    int(resp.get("start_count") or 0), int(resp.get("remains") or 0))
                n += 1
            time.sleep(0.3)
        show(call, f"✅ Đã cập nhật {n} đơn.", back_markup("adm_smm_orders"))


def start_polling_loop(main_db_path):
    def loop():
        time.sleep(180)
        while True:
            try:
                if not os.path.exists(main_db_path): time.sleep(300); continue
                rows = order_list_all(main_db_path, 50)
                for r in rows:
                    oid, uid, nm, pl, qty, price, st, ao, cat = r
                    if st in ("completed","refunded","canceled") or not ao or ao == "—": continue
                    resp = api_status(main_db_path, ao)
                    if isinstance(resp, dict) and not resp.get("error") and resp.get("status"):
                        order_update(main_db_path, oid, (resp.get("status") or "").lower(),
                            int(resp.get("start_count") or 0), int(resp.get("remains") or 0))
                    time.sleep(0.5)
            except Exception as e: log.warning("smm poll: %s", e)
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()