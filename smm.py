# -*- coding: utf-8 -*-
"""Module Buff Mạng Xã Hội — UI nhóm theo loại"""
import os, re, time, html, sqlite3, logging, threading
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

# Loại dịch vụ con — thứ tự hiển thị
SUBTYPES = [
    ("Tim",     "❤️", ["tim", "like", "tym", "heart", "cảm xúc"]),
    ("Follow",  "👥", ["follow", "fl ", " fl", "theo dõi", "sub", "follower"]),
    ("Share",   "🔁", ["share", "chia sẻ", "repost", "lan truyền"]),
    ("View",    "👁", ["view", "lượt xem", "xem ", "watch", "play"]),
    ("Comment", "💬", ["comment", "cmt", "bình luận", "bl "]),
    ("Live",    "📡", ["live", "mắt live", "stream"]),
    ("Khác",    "🌐", []),  # fallback
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
    try: c.executescript(SCHEMA); c.commit()
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
        log.info("SMM services raw: status=%s body=%s", r.status_code, r.text[:800])
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
    q = "SELECT id,platform,name,api_service,cost,price,min,max,active FROM smm_services WHERE 1=1"
    par = []
    if only_active: q += " AND active=1"
    if platform: q += " AND platform=?"; par.append(platform)
    q += " ORDER BY price ASC LIMIT 500"
    return _q(p, q, tuple(par), "all") or []

def svc_get(p, sid):
    r = _q(p, "SELECT id,platform,name,api_service,cost,price,min,max,active FROM smm_services WHERE id=?", (sid,), "one")
    if not r: return None
    return dict(zip(["id","platform","name","api_service","cost","price","min","max","active"], r))

def svc_add(p, pl, nm, api, cost, price, mn, mx):
    sql = "INSERT INTO smm_services (platform,name,api_service,cost,price,min,max) VALUES (?,?,?,?,?,?,?)"
    return _q(p, sql, (pl, nm, str(api), cost, price, mn, mx))

def svc_update(p, sid, f, v):
    if f not in ("platform","name","api_service","cost","price","min","max","active"): return
    _q(p, f"UPDATE smm_services SET {f}=? WHERE id=?", (v, sid))
def svc_del(p, sid): _q(p, "DELETE FROM smm_services WHERE id=?", (sid,))
def svc_toggle(p, sid):
    r = _q(p, "SELECT active FROM smm_services WHERE id=?", (sid,), "one")
    if not r: return None
    new = 0 if r[0] else 1
    _q(p, "UPDATE smm_services SET active=? WHERE id=?", (new, sid))
    return new

def platforms_available(p):
    rows = _q(p, "SELECT DISTINCT platform FROM smm_services WHERE active=1", fetch="all")
    return [r[0] for r in rows] or []

def svc_count(p):
    try:
        r = _q(p, "SELECT COUNT(*) FROM smm_services", fetch="one")
        return r[0] if r else 0
    except Exception as e:
        log.warning("svc_count err: %s", e); return -1

# ===== PHÂN LOẠI DỊCH VỤ THEO LOẠI =====
def detect_subtype(name):
    """Nhận diện loại dịch vụ từ tên. Trả về tên loại (Tim/Follow/...)."""
    low = (name or "").lower()
    # Ưu tiên theo thứ tự SUBTYPES
    for label, _, keys in SUBTYPES:
        if label == "Khác": continue
        for k in keys:
            if k in low: return label
    return "Khác"

def list_subtypes(bp, platform):
    """Trả về [(label, icon, count, min_price), ...] cho nền tảng."""
    rows = svc_list(bp, platform)
    groups = {}
    for s in rows:
        # s = (id, platform, name, api_service, cost, price, min, max, active)
        label = detect_subtype(s[2])
        if label not in groups:
            groups[label] = {"count": 0, "min_price": 10**12}
        groups[label]["count"] += 1
        if s[5] < groups[label]["min_price"]:
            groups[label]["min_price"] = s[5]
    out = []
    for label, icon, _ in SUBTYPES:
        if label in groups:
            out.append((label, icon, groups[label]["count"], groups[label]["min_price"]))
    return out

def svc_in_subtype(bp, platform, subtype):
    """List service trong 1 subtype, sort giá tăng dần."""
    rows = svc_list(bp, platform)
    out = [s for s in rows if detect_subtype(s[2]) == subtype]
    out.sort(key=lambda s: s[5])
    return out


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


def register(bot, h):
    fmt = h["fmt"]; cur_admin = h["cur_admin"]; get_user = h["get_user"]
    show = h["show"]; back_markup = h["back_markup"]; user_states = h["user_states"]
    dbp = h["db_path_fn"]

    def _safe(fn):
        def w(call):
            try: fn(call)
            except Exception as e:
                log.exception("smm handler err: %s", e)
                try: bot.answer_callback_query(call.id, f"❌ Lỗi: {str(e)[:100]}", show_alert=True)
                except: pass
        return w

    # ===== USER =====
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
        subs = list_subtypes(bp, pl)
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
            m.add(types.InlineKeyboardButton(
                f"{fmt(s[5])}đ/1k · {nm}",
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
                   f"<blockquote>📊 {len(svcs)} dịch vụ · Sắp xếp giá rẻ → cao\n"
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
                   f"💵 {fmt(s['price'])}đ/1k</blockquote>\n\n👉 Gửi <b>link</b> vào chat.\n/cancel để hủy.",
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
            bot.answer_callback_query(call.id, "Phiên hết hạn"); return
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
                bot.answer_callback_query(call.id, "Số dư không đủ"); return
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
        oid = order_create(bp, uid, s, link, qty, price, api_o, "processing")
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

    # ===== ADMIN =====
    def _adm_menu(call, note=""):
        bp = dbp()
        n = svc_count(bp)
        api_url = cfg_get(bp, "smm_api_url", "—") or "—"
        key = cfg_get(bp, "smm_api_key", "")
        kd = (key[:6]+"***") if len(key)>10 else ("(chưa set)" if not key else "***")
        rate = _get_rate(bp); markup = _get_markup(bp)
        txt = (f"<b>🔥 BUFF SMM (ADMIN)</b>\n\n"
               + (f"<blockquote>{note}</blockquote>\n\n" if note else "")
               + f"<blockquote>🌐 API: <code>{html.escape(api_url[:55])}</code>\n"
                 f"🔑 Key: <code>{html.escape(kd)}</code>\n"
                 f"💵 Tỷ giá: <b>{fmt(rate)}đ/USD</b>\n"
                 f"📈 Lãi: <b>{markup}%</b>\n"
                 f"📦 Dịch vụ: <b>{n}</b></blockquote>")
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("⚙️ Cấu hình API", callback_data="adm_smm_cfg"),
              types.InlineKeyboardButton("💰 Giá & Lãi", callback_data="adm_smm_price"),
              types.InlineKeyboardButton("🔄 Sync từ API", callback_data="adm_smm_sync"),
              types.InlineKeyboardButton("🔍 Debug API", callback_data="adm_smm_debug"),
              types.InlineKeyboardButton("📦 DS dịch vụ", callback_data="adm_smm_list"),
              types.InlineKeyboardButton("➕ Thêm thủ công", callback_data="adm_smm_add"),
              types.InlineKeyboardButton("🧹 Xóa HẾT dịch vụ", callback_data="adm_smm_wipe"),
              types.InlineKeyboardButton("🧾 Đơn hàng", callback_data="adm_smm_orders"),
              types.InlineKeyboardButton("💵 Số dư API", callback_data="adm_smm_bal"),
              types.InlineKeyboardButton("🔙 Admin", callback_data="adm_panel"))
        show(call, txt, m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm")
    def _adm(call):
        if call.from_user.id != cur_admin(): return
        _adm_menu(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_cfg")
    def _cfg(call):
        if call.from_user.id != cur_admin(): return
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🌐 Đổi URL", callback_data="adm_smm_set|smm_api_url"),
              types.InlineKeyboardButton("🔑 Đổi Key", callback_data="adm_smm_set|smm_api_key"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm"))
        show(call, "<b>⚙️ CẤU HÌNH API</b>\n\nNhập URL dạng: <code>https://ncc.com/api/v2</code>\n"
                   "Key do nhà cung cấp cấp.", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_price")
    def _price_menu(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton(f"💵 Tỷ giá USD→VNĐ: {fmt(_get_rate(bp))}đ",
              callback_data="adm_smm_set|smm_usd_rate"),
              types.InlineKeyboardButton(f"📈 % Lãi: {_get_markup(bp)}%",
              callback_data="adm_smm_set|smm_markup_pct"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm"))
        show(call, "<b>💰 CẤU HÌNH GIÁ & LÃI</b>\n\n"
                   "API SMM trả rate theo <b>USD/1000</b>.\n"
                   "Giá bán = <code>rate × tỷ_giá × (1 + lãi%)</code>\n\n"
                   "VD: rate 0.90 USD, tỷ giá 25.000, lãi 30%\n"
                   "→ giá bán = 0.90 × 25.000 × 1.3 = 29.250đ/1k", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_set|"))
    def _setc(call):
        if call.from_user.id != cur_admin(): return
        k = call.data.split("|", 1)[1]
        user_states[call.from_user.id] = f"SMM_CFG|{k}"
        hint = "VD: 25000" if k == "smm_usd_rate" else ("VD: 30" if k == "smm_markup_pct" else "Nhập giá trị")
        show(call, f"Nhập giá trị mới cho <code>{k}</code>.\n<i>{hint}</i>\n/cancel hủy.",
             back_markup("adm_smm_cfg"))

    @bot.message_handler(func=lambda m: m.from_user and m.from_user.id == cur_admin() and
        (user_states.get(m.from_user.id) or "").startswith("SMM_CFG|") and m.text and not m.text.startswith("/"))
    def _cfg_in(m):
        raw = user_states.get(m.from_user.id, "")
        try: k = raw.split("|", 1)[1]
        except: user_states.pop(m.from_user.id, None); return
        cfg_set(dbp(), k, m.text.strip())
        user_states.pop(m.from_user.id, None)
        back = "adm_smm_price" if k in ("smm_usd_rate","smm_markup_pct") else "adm_smm_cfg"
        bot.reply_to(m, f"✅ Đã lưu <code>{k}</code>.",
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("🔙 Quay lại", callback_data=back)))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_bal")
    def _bal(call):
        if call.from_user.id != cur_admin(): return
        show(call, f"<b>💰 SỐ DƯ API</b>\n\n<blockquote>{html.escape(str(api_balance(dbp()))[:300])}</blockquote>",
             back_markup("adm_smm"))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_wipe")
    def _wipe(call):
        if call.from_user.id != cur_admin(): return
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ XOÁ HẾT", callback_data="adm_smm_wipeok"),
               types.InlineKeyboardButton("❌ Hủy", callback_data="adm_smm"))
        show(call, "⚠️ <b>XOÁ TẤT CẢ DỊCH VỤ?</b>\n\n"
                   "Sau khi xoá, bấm <b>🔄 Sync từ API</b> để nạp lại.", kb)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_wipeok")
    def _wipeok(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        n = svc_count(bp)
        try: _q(bp, "DELETE FROM smm_services")
        except Exception as e: log.warning("wipe err: %s", e)
        _adm_menu(call, f"✅ Đã xoá {n} dịch vụ. Bấm 🔄 Sync từ API.")

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_debug")
    def _debug(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        try: bot.answer_callback_query(call.id, "🔍 Đang test...")
        except: pass
        code, body, parsed = api_debug(bp)
        url = cfg_get(bp, "smm_api_url", "(trống)")
        key = cfg_get(bp, "smm_api_key", "")
        kd = (key[:8] + "***") if len(key) > 10 else ("(trống)" if not key else "***")
        if isinstance(parsed, list):
            info = f"📊 LIST có {len(parsed)} phần tử"
            if parsed: info += f"\n🔍 Item[0] type: {type(parsed[0]).__name__}"
        elif isinstance(parsed, dict):
            info = f"📊 DICT có {len(parsed)} keys: {list(parsed.keys())[:5]}"
        else:
            info = f"📊 Type: {type(parsed).__name__}"
        txt = (f"<b>🔍 DEBUG API</b>\n\n<blockquote>"
               f"🔗 URL: <code>{html.escape(url)}</code>\n"
               f"🔑 Key: <code>{html.escape(kd)}</code>\n"
               f"📡 HTTP: <b>{code}</b></blockquote>\n\n"
               f"<b>📄 Response raw (300 ký tự đầu):</b>\n<code>{html.escape(str(body)[:300])}</code>\n\n"
               f"<b>🔍 Parsed info:</b>\n<code>{html.escape(info)}</code>")
        show(call, txt, back_markup("adm_smm"))

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_sync")
    def _sync(call):
        if call.from_user.id != cur_admin(): return
        bp = dbp()
        if not cfg_get(bp, "smm_api_url") or not cfg_get(bp, "smm_api_key"):
            show(call, "⚠️ Chưa cấu hình API.", back_markup("adm_smm_cfg")); return
        try: bot.answer_callback_query(call.id, "🔄 Đang tải...")
        except: pass
        resp = api_services(bp)
        if isinstance(resp, dict) and "error" in resp:
            show(call, f"❌ <b>API BÁO LỖI</b>\n\n<blockquote>"
                       f"<code>{html.escape(str(resp['error'])[:300])}</code></blockquote>",
                 back_markup("adm_smm")); return
        if not isinstance(resp, list):
            show(call, f"❌ API trả về kiểu <b>{type(resp).__name__}</b>, không phải LIST.\n\n"
                       f"<code>{html.escape(str(resp)[:300])}</code>",
                 back_markup("adm_smm")); return
        if not resp:
            show(call, "⚠️ API trả về danh sách <b>rỗng</b>.\n\n"
                       "Có thể key không có quyền xem services.",
                 back_markup("adm_smm")); return
        rate = _get_rate(bp); markup = _get_markup(bp)
        added = 0; sk = 0; errs = []
        sample_type = type(resp[0]).__name__
        for i, s in enumerate(resp):
            try:
                if not isinstance(s, dict):
                    sk += 1
                    if len(errs) < 5: errs.append(f"[{i}] item không phải dict")
                    continue
                api_id = str(s.get("service") or s.get("id") or "").strip()
                if not api_id:
                    sk += 1
                    if len(errs) < 5: errs.append(f"[{i}] thiếu service id")
                    continue
                dup = _q(bp, "SELECT 1 FROM smm_services WHERE api_service=?", (api_id,), "one")
                if dup: sk += 1; continue
                nm = str(s.get("name") or "Dịch vụ")[:80]
                cat = str(s.get("category") or s.get("type") or "Khác")[:30]
                pl = _normalize_platform(s.get("platform"), nm, cat)
                try: rate_usd = float(s.get("rate") or 0)
                except: rate_usd = 0
                cost = int(round(rate_usd * rate))
                price = int(round(cost * (1 + markup / 100.0)))
                if price <= 0: price = 1000
                try: mn = int(float(str(s.get("min") or 100).strip()))
                except: mn = 100
                try: mx = int(float(str(s.get("max") or 100000).strip()))
                except: mx = 100000
                svc_add(bp, pl, nm, api_id, cost, price, mn, mx)
                added += 1
            except Exception as e:
                log.warning("sync err [%d]: %s | data=%s", i, e, str(s)[:150])
                sk += 1
                if len(errs) < 5: errs.append(f"[{i}] {str(e)[:80]}")
        msg = (f"✅ <b>SYNC XONG</b>\n\n"
               f"➕ Thêm: <b>{added}</b>\n⏭ Bỏ qua: {sk}\n"
               f"📊 Item type: <b>{sample_type}</b>\n\n"
               f"💵 Tỷ giá: {fmt(rate)}đ/USD | 📈 Lãi: {markup}%")
        if errs:
            msg += "\n\n<b>⚠️ 5 lỗi đầu:</b>\n"
            for e in errs: msg += f"<code>{html.escape(e)}</code>\n"
        show(call, msg, back_markup("adm_smm"))

    def _show_svc(call, page=0):
        bp = dbp(); svcs = svc_list(bp, only_active=False)
        per = 8; tp = max(1, (len(svcs)+per-1)//per); page = max(0, min(page, tp-1))
        chunk = svcs[page*per:(page+1)*per]
        m = types.InlineKeyboardMarkup(row_width=1)
        for s in chunk:
            icon = "✅" if s[8] else "⛔"
            nm = s[2] if len(s[2]) <= 26 else s[2][:25] + "…"
            m.add(types.InlineKeyboardButton(f"{icon} #{s[0]} {s[1]} | {nm} – {fmt(s[5])}đ",
                  callback_data=f"adm_smm_sv|{s[0]}"))
        nav = []
        if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm_smm_pg|{page-1}"))
        nav.append(types.InlineKeyboardButton(f"{page+1}/{tp}", callback_data="noop"))
        if page < tp-1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm_smm_pg|{page+1}"))
        if nav: m.row(*nav)
        m.add(types.InlineKeyboardButton("➕ Thêm", callback_data="adm_smm_add"),
              types.InlineKeyboardButton("🔄 Sync", callback_data="adm_smm_sync"))
        m.add(types.InlineKeyboardButton("🔙 Admin SMM", callback_data="adm_smm"))
        show(call, f"<b>📦 DS DỊCH VỤ</b>\n\n{len(svcs)} dịch vụ | Trang {page+1}/{tp}", m)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_list")
    def _list(call):
        if call.from_user.id != cur_admin(): return
        _show_svc(call, 0)
    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_pg|"))
    def _pg(call):
        if call.from_user.id != cur_admin(): return
        _show_svc(call, int(call.data.split("|")[1]))

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_sv|"))
    def _sv(call):
        if call.from_user.id != cur_admin(): return
        sid = int(call.data.split("|")[1]); s = svc_get(dbp(), sid)
        if not s: show(call, "Không thấy.", back_markup("adm_smm_list")); return
        profit = s["price"] - s["cost"]
        pct = round(profit*100/s["cost"]) if s["cost"] else 0
        sub = detect_subtype(s["name"])
        txt = (f"<b>📦 DV #{sid}</b>\n\n<blockquote>📱 {html.escape(s['platform'])} · {html.escape(sub)}\n"
               f"📝 {html.escape(s['name'])}\n"
               f"🆔 <code>{html.escape(s['api_service'])}</code>\n"
               f"💵 Nhập: <b>{fmt(s['cost'])}đ</b>/1k\n"
               f"💰 Bán: <b>{fmt(s['price'])}đ</b>/1k\n"
               f"📈 Lãi: <b>{fmt(profit)}đ</b> ({pct}%)\n"
               f"📊 {fmt(s['min'])} – {fmt(s['max'])}\n🔖 {'✅' if s['active'] else '⛔'}</blockquote>")
        m = types.InlineKeyboardMarkup(row_width=2)
        m.add(types.InlineKeyboardButton("✏️ Tên", callback_data=f"adm_smm_ed|{sid}|name"),
              types.InlineKeyboardButton("💵 Giá", callback_data=f"adm_smm_ed|{sid}|price"))
        m.add(types.InlineKeyboardButton("📊 Min", callback_data=f"adm_smm_ed|{sid}|min"),
              types.InlineKeyboardButton("📊 Max", callback_data=f"adm_smm_ed|{sid}|max"))
        m.add(types.InlineKeyboardButton("⛔ Tắt" if s["active"] else "✅ Bật",
              callback_data=f"adm_smm_tg|{sid}"))
        m.add(types.InlineKeyboardButton("🗑️ XOÁ", callback_data=f"adm_smm_dl|{sid}"),
              types.InlineKeyboardButton("🔙", callback_data="adm_smm_list"))
        show(call, txt, m)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_ed|"))
    def _ed(call):
        if call.from_user.id != cur_admin(): return
        _, sid, f = call.data.split("|")
        user_states[call.from_user.id] = f"SMM_ED|{sid}|{f}"
        show(call, f"Nhập <code>{f}</code> mới cho #{sid}. /cancel hủy.", back_markup(f"adm_smm_sv|{sid}"))

    @bot.message_handler(func=lambda m: m.from_user and m.from_user.id == cur_admin() and
        (user_states.get(m.from_user.id) or "").startswith("SMM_ED|") and m.text and not m.text.startswith("/"))
    def _ed_in(m):
        raw = user_states.get(m.from_user.id, "")
        try: _, sid_s, f = raw.split("|"); sid = int(sid_s)
        except: user_states.pop(m.from_user.id, None); return
        v = m.text.strip()
        if f in ("price","cost","min","max"):
            try: v = int(re.sub(r"[^\d]", "", v))
            except: bot.reply_to(m, "❌ Phải là số"); return
        svc_update(dbp(), sid, f, v)
        user_states.pop(m.from_user.id, None)
        bot.reply_to(m, "✅ Đã sửa.", reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
            types.InlineKeyboardButton("👁 Xem", callback_data=f"adm_smm_sv|{sid}"),
            types.InlineKeyboardButton("🔙 DS", callback_data="adm_smm_list")))

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_tg|"))
    def _tg(call):
        if call.from_user.id != cur_admin(): return
        sid = int(call.data.split("|")[1]); svc_toggle(dbp(), sid)
        call.data = f"adm_smm_sv|{sid}"; _sv(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_dl|"))
    def _dl(call):
        if call.from_user.id != cur_admin(): return
        sid = int(call.data.split("|")[1])
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ XOÁ", callback_data=f"adm_smm_dlok|{sid}"),
               types.InlineKeyboardButton("❌", callback_data=f"adm_smm_sv|{sid}"))
        show(call, f"⚠️ Xoá DV #{sid}?", kb)

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_dlok|"))
    def _dlok(call):
        if call.from_user.id != cur_admin(): return
        svc_del(dbp(), int(call.data.split("|")[1])); _show_svc(call, 0)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_add")
    def _add(call):
        if call.from_user.id != cur_admin(): return
        user_states[call.from_user.id] = "SMM_ADD"
        show(call, "<b>➕ THÊM DV</b>\n\nCú pháp:\n<code>Nền tảng | Tên | API_ID | giá_nhập | giá_bán | min | max</code>\n\n"
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

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_ov|"))
    def _ov_admin(call):
        if call.from_user.id != cur_admin(): return
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

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("adm_smm_rf|"))
    def _rf(call):
        if call.from_user.id != cur_admin(): return
        oid = int(call.data.split("|")[1]); bp = dbp(); r = order_get(bp, oid)
        if not r: return
        order_refund(bp, oid)
        try: bot.send_message(r["user_id"], f"💸 Đã hoàn <b>{fmt(r['price'])}đ</b> cho đơn #{oid}.")
        except: pass
        call.data = f"adm_smm_ov|{oid}"; _ov_admin(call)

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "adm_smm_ref")
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
