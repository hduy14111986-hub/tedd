# -*- coding: utf-8 -*-
"""BOT TELEGRAM MULTI-TENANT — Groq AI"""
import os,re,time,html,hmac,sqlite3,logging,threading,urllib.parse as up,json
from collections import deque
from contextlib import contextmanager
from datetime import datetime as dt,timedelta as td
import requests,telebot
from telebot import types
from telebot.apihelper import ApiTelegramException as ApiEx
from flask import Flask,request,jsonify
telebot.apihelper.ENABLE_MIDDLEWARE=True
try:
    from openai import OpenAI
except: OpenAI=None
import smm

E=lambda k,d="":os.environ.get(k,d).strip()
BT=E("BOT_TOKEN") or exit("Thiếu BOT_TOKEN")
GQ=E("GROQ_API_KEY");GQM=E("GROQ_MODEL","llama-3.3-70b-versatile")
SK=E("SEPAY_API_KEY");AID=int(E("ADMIN_ID","0"));BUN=E("BOT_USERNAME","@bot")
BN=E("BANK_NAME","TPBank");AN=E("ACCOUNT_NO","");ACN=E("ACCOUNT_NAME","")
CBF=int(E("CREATE_BOT_FEE","20000"));BRD=int(E("BOT_RENT_DAYS","30"));BRF=int(E("BOT_RENEW_FEE","15000"))
AIC=int(E("AI_COOLDOWN","1"));AIS=False
DD=E("DATA_DIR") or ("/var/data" if os.path.isdir("/var/data") else ".")
MDB=os.path.join(DD,"main.db");BD=os.path.join(DD,"bots");PT=int(E("PORT","8080"))
BCI=int(E("BACKUP_CHAT_ID","0"));BIN=int(E("BACKUP_INTERVAL","1800"));BK=5
os.makedirs(DD,exist_ok=True);os.makedirs(BD,exist_ok=True)
_o=os.path.join(DD,"bot_database.db")
if os.path.exists(_o) and not os.path.exists(MDB):
    try:
        os.rename(_o,MDB)
        for e in ("-wal","-shm"):
            if os.path.exists(_o+e):os.rename(_o+e,MDB+e)
    except:pass
logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
log=logging.getLogger("bot")
MB=telebot.TeleBot(BT,parse_mode="HTML",threaded=True,num_threads=8)
app=Flask(__name__)
AICl=None
if OpenAI and GQ:
    try:
        AICl=OpenAI(api_key=GQ,base_url="https://api.groq.com/openai/v1",timeout=45)
        log.info("✅ Groq OK — %s",GQM)
    except Exception as e:log.warning("Groq init: %s",e)
_ctx=threading.local();CBM={};ACB={}
LK={"c":threading.Lock(),"p":threading.Lock(),"b":threading.Lock()}
US={};ALC={};AHL=threading.Lock();AH={};AMO=[None];WL=deque(maxlen=30);AIL=threading.Lock();AFU=[0];PC={"t":"","time":0}
BIDS=[];BTIM=[None];BTIML=threading.Lock()

def cTK(t):return re.sub(r"[\s\u200b\u200c\u200d\ufeff\xa0]","",(t or "").strip())
def vTK(t):
    t=cTK(t)
    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$",t):return False,f"Format sai (len={len(t)})"
    try:
        r=requests.get(f"https://api.telegram.org/bot{t}/getMe",timeout=15);j=r.json()
        if j.get("ok"):return True,j.get("result",{})
        return False,f"[{j.get('error_code',r.status_code)}] {j.get('description','?')}"
    except requests.exceptions.Timeout:return False,"Timeout 15s"
    except Exception as e:return False,f"{type(e).__name__}: {str(e)[:150]}"
def isRL(s):return any(k in s for k in ("429","rate limit","overloaded","503","unavailable","quota"))
def cDB():return getattr(_ctx,"db_path",MDB)
def cAD():return getattr(_ctx,"admin_id",AID)
def cB():return getattr(_ctx,"bot_instance",None) or MB
def cBN():return getattr(_ctx,"bot_username",BUN)
def isC():return getattr(_ctx,"is_child",False)

@contextmanager
def db():
    c=sqlite3.connect(cDB(),timeout=30)
    try:yield c;c.commit()
    except:c.rollback();raise
    finally:c.close()
def cM():return dt.now().strftime("%Y-%m")

SCH="""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY,username TEXT,full_name TEXT,balance INTEGER DEFAULT 0,total_recharged INTEGER DEFAULT 0,month_recharged INTEGER DEFAULT 0,month_key TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS transactions (tx_id TEXT PRIMARY KEY,user_id INTEGER,amount INTEGER,kind TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT DEFAULT '',price INTEGER NOT NULL,category TEXT DEFAULT 'Data',stock INTEGER DEFAULT -1,sold INTEGER DEFAULT 0,active INTEGER DEFAULT 1,api_product_code TEXT DEFAULT '',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,product_name TEXT,price INTEGER,status TEXT DEFAULT 'paid',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS proxy_stock (id INTEGER PRIMARY KEY AUTOINCREMENT,ip TEXT NOT NULL,port INTEGER NOT NULL,username TEXT DEFAULT '',password TEXT DEFAULT '',protocol TEXT DEFAULT 'HTTP',region TEXT DEFAULT '',isp TEXT DEFAULT '',status TEXT DEFAULT 'available',sold_to INTEGER DEFAULT 0,sold_at TEXT DEFAULT '',expires_at TEXT '',product_id INTEGER DEFAULT 0,note TEXT DEFAULT '',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ipa_files (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT DEFAULT '',file_id TEXT NOT NULL,file_size INTEGER DEFAULT 0,downloads INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS account_stock (id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER DEFAULT 0,username TEXT NOT NULL,password TEXT DEFAULT '',note TEXT DEFAULT '',status TEXT DEFAULT 'available',sold_to INTEGER DEFAULT 0,sold_at TEXT DEFAULT '',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT DEFAULT '');"""
MO="""CREATE TABLE IF NOT EXISTS user_bots (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,bot_token TEXT UNIQUE,bot_username TEXT,status TEXT DEFAULT 'active',expires_at TEXT DEFAULT '',plan TEXT DEFAULT 'basic',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"""
DS={"home_title":"🚀 HỆ THỐNG BOT ĐA NĂNG","home_subtitle":"Data • Proxy • IPA • AI • SMM","welcome_msg":"Chào mừng! Nhắn tin để chat AI.","shop_title":"🛒 CỬA HÀNG","support_text":"Nhắn admin để được hỗ trợ!","footer_note":"Cảm ơn bạn! ❤️","bank_name":"","account_no":"","account_name":"","data_api_url":"","data_api_key":"","data_api_method":"POST","welcome_music":"","welcome_music_caption":"🎵 Nhạc chào mừng!","menu_hidden":"[]","menu_custom":"[]"}
DP=[("🌐 Data 30K – Không giới hạn",30000,"Data","Gói KHÔNG GIỚI HẠN data 30 ngày."),("🌐 Data 50K – Không giới hạn",50000,"Data","Gói KHÔNG GIỚI HẠN data 30 ngày."),("🌐 Proxy dân cư VN 30 ngày",50000,"Proxy","Proxy dân cư VN, không giới hạn băng thông.")]

def iDB(p=None,main=False):
    p=p or cDB();d=os.path.dirname(p)
    if d:os.makedirs(d,exist_ok=True)
    c=sqlite3.connect(p)
    try:
        try:c.execute("PRAGMA journal_mode=WAL")
        except:pass
        c.executescript(SCH)
        if main:c.executescript(MO)
        try:c.execute("ALTER TABLE products ADD COLUMN api_product_code TEXT DEFAULT ''")
        except:pass
        for k,v in DS.items():c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)",(k,v))
        if c.execute("SELECT COUNT(*) FROM products").fetchone()[0]==0:
            for n,pr,cat,de in DP:c.execute("INSERT INTO products (name,description,price,category) VALUES (?,?,?,?)",(n,de,pr,cat))
        c.commit()
    finally:c.close()
    try:smm.init_schema(p)
    except Exception as e:log.warning("smm: %s",e)

def gU(uid,un,fn):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id,username,full_name) VALUES (?,?,?)",(uid,un,fn))
        c.execute("UPDATE users SET username=?,full_name=? WHERE user_id=?",(un,fn,uid))
        r=c.execute("SELECT balance,total_recharged,month_recharged,month_key FROM users WHERE user_id=?",(uid,)).fetchone()
    return {"id":uid,"balance":r[0],"total":r[1],"month":r[2] if r[3]==cM() else 0}
def _cr(c,uid,a):
    mk=cM()
    c.execute("""UPDATE users SET balance=balance+?,total_recharged=total_recharged+?,month_recharged=CASE WHEN month_key=? THEN month_recharged+? ELSE ? END,month_key=? WHERE user_id=?""",(a,a,mk,a,a,mk,uid))
def aAM(uid,a):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id,username,full_name) VALUES (?,'','')",(uid,))
        if a>=0:_cr(c,uid,a)
        else:c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(a,uid))
    schB()
def procD(tx,uid,a):
    with db() as c:
        if c.execute("INSERT OR IGNORE INTO transactions (tx_id,user_id,amount,kind) VALUES (?,?,?,'deposit')",(tx,uid,a)).rowcount==0:return False
        c.execute("INSERT OR IGNORE INTO users (user_id,username,full_name) VALUES (?,'','')",(uid,))
        _cr(c,uid,a)
    schB();return True
def procDo(tx,uid,a):
    with db() as c:return c.execute("INSERT OR IGNORE INTO transactions (tx_id,user_id,amount,kind) VALUES (?,?,?,'donate')",(tx,uid,a)).rowcount>0
def sG(k,d=""):
    with db() as c:r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()
    return r[0] if r and r[0] else d
def sS(k,v):
    with db() as c:c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",(k,v))
def sA():
    with db() as c:return dict(c.execute("SELECT key,value FROM settings").fetchall())
def _hB():
    try:return set(json.loads(sG("menu_hidden","[]")))
    except:return set()
def _cB():
    try:return json.loads(sG("menu_custom","[]"))
    except:return []
def fmt(n):return f"{int(n):,}".replace(",",".")
def bI():
    if isC():return (sG("bank_name") or "—",sG("account_no") or "—",sG("account_name") or "—")
    return (BN,AN,ACN)

def cNCC(url,key,code,qty,ref,me="POST",to=30):
    pl={"api_key":key,"product_code":code,"quantity":qty,"order_id":ref}
    try:
        r=requests.get(url,params=pl,timeout=to) if me.upper()=="GET" else requests.post(url,json=pl,timeout=to)
        if r.status_code!=200:return False,"",f"HTTP {r.status_code}"
        try:j=r.json()
        except:return True,r.text[:3000],""
        if isinstance(j,dict):
            ok=j.get("success",j.get("status",True))
            if ok in (False,"false","fail","error",0,"0",None):return False,"",str(j.get("message") or j.get("error") or j)[:200]
            return True,str(j.get("data") or j.get("result") or j.get("content") or j.get("message") or j),""
        return True,str(j),""
    except Exception as e:return False,"",str(e)[:150]

def sL(oa=True,lim=50):
    with db() as c:
        q="SELECT id,name,price,category,stock,sold,active FROM products WHERE 1=1"
        if oa:q+=" AND active=1"
        q+=" ORDER BY id LIMIT ?"
        rs=c.execute(q,(lim,)).fetchall()
    return [dict(zip(["id","name","price","category","stock","sold","active"],r)) for r in rs]
def sLA(lim=200):
    with db() as c:rs=c.execute("SELECT id,name,price,category,stock,sold,active FROM products ORDER BY id LIMIT ?",(lim,)).fetchall()
    return [dict(zip(["id","name","price","category","stock","sold","active"],r)) for r in rs]
def sGt(pid):
    with db() as c:r=c.execute("SELECT id,name,description,price,category,stock,sold,active,COALESCE(api_product_code,'') FROM products WHERE id=?",(pid,)).fetchone()
    return dict(zip(["id","name","description","price","category","stock","sold","active","api_product_code"],r)) if r else None
def sBuy(uid,pid):
    with db() as c:
        r=c.execute("SELECT name,price,stock,active,category FROM products WHERE id=?",(pid,)).fetchone()
        if not r:return False,"Không tìm thấy"
        n,pr,st,ac,cat=r
        if not ac:return False,"Ngừng bán"
        if cat not in ("Account","Proxy") and st==0:return False,"Hết hàng"
        if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(pr,uid,pr)).rowcount==0:return False,"Số dư không đủ"
        if cat not in ("Account","Proxy"):
            if st>0:c.execute("UPDATE products SET stock=stock-1,sold=sold+1 WHERE id=?",(pid,))
            else:c.execute("UPDATE products SET sold=sold+1 WHERE id=?",(pid,))
        c.execute("INSERT INTO orders (user_id,product_id,product_name,price) VALUES (?,?,?,?)",(uid,pid,n,pr))
        oid=c.lastrowid
    schB();return True,{"order_id":oid,"name":n,"price":pr}
def sMyO(uid,lim=10):
    with db() as c:return c.execute("SELECT id,product_name,price,created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?",(uid,lim)).fetchall()

def pImp(lines):
    a,e=0,[]
    with db() as c:
        for i,l in enumerate(lines,1):
            l=(l or "").strip()
            if not l or l.startswith("#"):continue
            try:
                m=l.split("|");core=m[0].strip()
                rg=m[1].strip() if len(m)>1 else "";isp=m[2].strip() if len(m)>2 else "";pr=m[3].strip().upper() if len(m)>3 else "HTTP"
                p=core.split(":")
                if len(p)<2:e.append(f"D{i}: thiếu port");continue
                ip,po=p[0].strip(),int(p[1]);pu=p[2].strip() if len(p)>2 else "";pp=p[3].strip() if len(p)>3 else ""
                if not ip or not(1<=po<=65535):e.append(f"D{i}: lỗi");continue
                if c.execute("SELECT 1 FROM proxy_stock WHERE ip=? AND port=?",(ip,po)).fetchone():e.append(f"D{i}: trùng");continue
                c.execute("INSERT INTO proxy_stock (ip,port,username,password,protocol,region,isp) VALUES (?,?,?,?,?,?,?)",(ip,po,pu,pp,pr,rg,isp));a+=1
            except Exception as ex:e.append(f"D{i}: {ex}")
    return a,e
def pCnt():
    with db() as c:return {"available":c.execute("SELECT COUNT(*) FROM proxy_stock WHERE status='available'").fetchone()[0],"sold":c.execute("SELECT COUNT(*) FROM proxy_stock WHERE status='sold'").fetchone()[0],"total":c.execute("SELECT COUNT(*) FROM proxy_stock").fetchone()[0]}
def pBuy(uid,pid,days=30):
    with LK["p"]:
        with db() as c:
            p=c.execute("SELECT name,price,active FROM products WHERE id=?",(pid,)).fetchone()
            if not p:return False,"SP không tồn tại",None
            n,pr,ac=p
            if not ac:return False,"Ngừng bán",None
            if c.execute("SELECT COUNT(*) FROM proxy_stock WHERE status='available'").fetchone()[0]<=0:return False,"Hết proxy!",None
            if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(pr,uid,pr)).rowcount==0:return False,"Số dư không đủ",None
            r=c.execute("SELECT id,ip,port,username,password,protocol,region,isp FROM proxy_stock WHERE status='available' ORDER BY id LIMIT 1").fetchone()
            if not r:
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(pr,uid));return False,"Hết kho, đã hoàn tiền",None
            i,ip,po,pu,pp,pt,rg,isp=r
            ex=(dt.now()+td(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE proxy_stock SET status='sold',sold_to=?,sold_at=CURRENT_TIMESTAMP,expires_at=?,product_id=? WHERE id=?",(uid,ex,pid,i))
            c.execute("INSERT INTO orders (user_id,product_id,product_name,price) VALUES (?,?,?,?)",(uid,pid,n,pr))
    schB();return True,"",{"id":i,"ip":ip,"port":po,"username":pu,"password":pp,"protocol":pt,"region":rg,"isp":isp,"expires_at":ex,"days":days,"name":n,"price":pr}
def pMy(uid):
    with db() as c:rs=c.execute("SELECT id,ip,port,username,password,protocol,region,isp,expires_at FROM proxy_stock WHERE sold_to=? ORDER BY id DESC",(uid,)).fetchall()
    nw=dt.now().strftime("%Y-%m-%d %H:%M:%S")
    return [{"id":r[0],"ip":r[1],"port":r[2],"username":r[3],"password":r[4],"protocol":r[5],"region":r[6],"isp":r[7],"expires_at":r[8],"status":"active" if r[8] and r[8]>nw else "expired"} for r in rs]

def aImp(pid,lines):
    a,e=0,[]
    with db() as c:
        for i,l in enumerate(lines,1):
            l=(l or "").strip()
            if not l or l.startswith("#"):continue
            p=[x.strip() for x in l.split("|")]
            if not p or not p[0]:e.append(f"D{i}: thiếu TK");continue
            u=p[0][:200];pw=p[1][:200] if len(p)>1 else "";nt=p[2][:200] if len(p)>2 else ""
            if c.execute("SELECT 1 FROM account_stock WHERE username=? AND product_id=? AND status='available'",(u,pid)).fetchone():e.append(f"D{i}: trùng");continue
            c.execute("INSERT INTO account_stock (product_id,username,password,note) VALUES (?,?,?,?)",(pid,u,pw,nt));a+=1
        if a>0:
            cnt=c.execute("SELECT COUNT(*) FROM account_stock WHERE product_id=? AND status='available'",(pid,)).fetchone()[0]
            c.execute("UPDATE products SET stock=? WHERE id=?",(cnt,pid))
    return a,e
def aCnt(pid):
    with db() as c:return c.execute("SELECT COUNT(*) FROM account_stock WHERE product_id=? AND status='available'",(pid,)).fetchone()[0]
def aLA(pid,lim=100):
    with db() as c:rs=c.execute("SELECT id,username,password,note,status,sold_to,sold_at FROM account_stock WHERE product_id=? ORDER BY id DESC LIMIT ?",(pid,lim)).fetchall()
    return [dict(zip(["id","username","password","note","status","sold_to","sold_at"],r)) for r in rs]
def aBuy(uid,pid):
    with LK["p"]:
        with db() as c:
            p=c.execute("SELECT name,price,active FROM products WHERE id=?",(pid,)).fetchone()
            if not p:return False,"SP không tồn tại",None
            n,pr,ac=p
            if not ac:return False,"Ngừng bán",None
            if c.execute("SELECT COUNT(*) FROM account_stock WHERE product_id=? AND status='available'",(pid,)).fetchone()[0]<=0:return False,"Hết kho TK!",None
            if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(pr,uid,pr)).rowcount==0:return False,"Số dư không đủ",None
            r=c.execute("SELECT id,username,password,note FROM account_stock WHERE product_id=? AND status='available' ORDER BY id LIMIT 1",(pid,)).fetchone()
            if not r:
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(pr,uid));return False,"Hết, đã hoàn tiền",None
            aid,u,pw,nt=r
            c.execute("UPDATE account_stock SET status='sold',sold_to=?,sold_at=CURRENT_TIMESTAMP WHERE id=?",(uid,aid))
            cnt=c.execute("SELECT COUNT(*) FROM account_stock WHERE product_id=? AND status='available'",(pid,)).fetchone()[0]
            c.execute("UPDATE products SET stock=?,sold=sold+1 WHERE id=?",(cnt,pid))
            c.execute("INSERT INTO orders (user_id,product_id,product_name,price) VALUES (?,?,?,?)",(uid,pid,n,pr))
    schB();return True,"",{"aid":aid,"username":u,"password":pw,"note":nt,"name":n,"price":pr}
def aWipe(pid):
    with db() as c:
        n=c.execute("DELETE FROM account_stock WHERE product_id=? AND status='available'",(pid,)).rowcount
        c.execute("UPDATE products SET stock=0 WHERE id=?",(pid,))
    return n

def iA(n,d,f,s=0):
    with db() as c:return c.execute("INSERT INTO ipa_files (name,description,file_id,file_size) VALUES (?,?,?,?)",(n,d,f,s)).lastrowid
def iL(lim=100):
    with db() as c:rs=c.execute("SELECT id,name,description,file_size,downloads FROM ipa_files ORDER BY id DESC LIMIT ?",(lim,)).fetchall()
    return [dict(zip(["id","name","description","file_size","downloads"],r)) for r in rs]
def iG(pid):
    with db() as c:r=c.execute("SELECT id,name,description,file_id,file_size,downloads FROM ipa_files WHERE id=?",(pid,)).fetchone()
    return dict(zip(["id","name","description","file_id","file_size","downloads"],r)) if r else None
def iD(pid):
    with db() as c:c.execute("DELETE FROM ipa_files WHERE id=?",(pid,))
def iInc(pid):
    with db() as c:c.execute("UPDATE ipa_files SET downloads=downloads+1 WHERE id=?",(pid,))

def sUB(uid,tok,un,days=None):
    days=days or BRD
    ex=(dt.now()+td(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(MDB) as c:
        c.execute("INSERT OR REPLACE INTO user_bots (user_id,bot_token,bot_username,status,expires_at) VALUES (?,?,?,'active',?)",(uid,tok,un,ex));c.commit()
    return ex
def rB(uid,tok,days=None):
    days=days or BRD
    with sqlite3.connect(MDB) as c:
        r=c.execute("SELECT expires_at FROM user_bots WHERE bot_token=? AND user_id=?",(tok,uid)).fetchone()
        if not r:return None
        b=dt.now()
        if r[0]:
            try:
                o=dt.strptime(r[0],"%Y-%m-%d %H:%M:%S")
                if o>b:b=o
            except:pass
        nw=(b+td(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE user_bots SET expires_at=?,status='active' WHERE bot_token=?",(nw,tok));c.commit()
        return nw
def lUB(uid):
    with sqlite3.connect(MDB) as c:rs=c.execute("SELECT id,bot_token,bot_username,status,expires_at,plan FROM user_bots WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
    nw=dt.now();o=[]
    for r in rs:
        dl=None
        if r[4]:
            try:dl=(dt.strptime(r[4],"%Y-%m-%d %H:%M:%S")-nw).days
            except:pass
        o.append({"id":r[0],"token":r[1],"username":r[2],"status":r[3],"expires_at":r[4],"plan":r[5] or "basic","days_left":dl})
    return o
def bIA(tok):
    with sqlite3.connect(MDB) as c:r=c.execute("SELECT status,expires_at FROM user_bots WHERE bot_token=?",(tok,)).fetchone()
    if not r or r[0]!="active":return False
    if r[1]:
        try:
            if dt.now()>dt.strptime(r[1],"%Y-%m-%d %H:%M:%S"):return False
        except:pass
    return True
def gBR(t):
    with sqlite3.connect(MDB) as c:r=c.execute("SELECT id,status,expires_at FROM user_bots WHERE bot_token=?",(t,)).fetchone()
    return {"id":r[0],"status":r[1],"expires_at":r[2]} if r else None
def dBR(t):
    with sqlite3.connect(MDB) as c:c.execute("DELETE FROM user_bots WHERE bot_token=?",(t,));c.commit()
def cDBP(t):
    p=re.sub(r"[^A-Za-z0-9]","",t.split(":")[0])[:12]
    return os.path.join(BD,f"bot_{p}.db")
def mCB(t,oid,un=None):
    if not un:
        try:un=telebot.TeleBot(t).get_me().username
        except Exception as e:log.warning("tok: %s",e);return None
    dp=cDBP(t);iDB(dp);b=telebot.TeleBot(t,parse_mode="HTML",threaded=True,num_threads=2)
    CBM[t]={"owner_id":oid,"username":un,"db_path":dp}
    regH(b);return b
def sCB(t,oid,force=False,un=None):
    if not force and not bIA(t):return False
    with LK["c"]:
        if t in ACB:return True
        b=mCB(t,oid,un)
        if not b:return False
        ACB[t]=b
    threading.Thread(target=rCP,args=(t,b),daemon=True).start();return True
def stCB(t):
    with LK["c"]:b=ACB.pop(t,None)
    if b:
        try:b.stop_polling()
        except:pass
        return True
    return False
def rCP(t,b):
    f=True
    while t in ACB:
        try:
            try:b.remove_webhook()
            except:pass
            b.polling(non_stop=False,skip_pending=f,timeout=20,long_polling_timeout=20);f=False;time.sleep(1)
        except ApiEx as e:
            if e.error_code in (401,404):
                with LK["c"]:ACB.pop(t,None)
                with sqlite3.connect(MDB) as c:c.execute("UPDATE user_bots SET status='inactive' WHERE bot_token=?",(t,));c.commit()
                return
            f=False;time.sleep(5)
        except Exception as e:log.warning("cp: %s",e);f=False;time.sleep(5)
def lCB():
    try:
        with sqlite3.connect(MDB) as c:rs=c.execute("SELECT bot_token,user_id FROM user_bots WHERE status='active'").fetchall()
    except:rs=[]
    n=0
    for t,u in rs:
        if not bIA(t):continue
        try:sCB(t,u);n+=1
        except:pass
        time.sleep(0.3)
    log.info("Loaded %d child bots",n)
def chkEx():
    try:
        with sqlite3.connect(MDB) as c:rs=c.execute("SELECT bot_token,user_id,bot_username,expires_at FROM user_bots WHERE status='active' AND expires_at!=''").fetchall()
    except:return
    nw=dt.now()
    for t,u,un,ex in rs:
        try:
            if nw<=dt.strptime(ex,"%Y-%m-%d %H:%M:%S"):continue
        except:continue
        if t in ACB:
            stCB(t)
            with sqlite3.connect(MDB) as c:c.execute("UPDATE user_bots SET status='inactive' WHERE bot_token=?",(t,));c.commit()
            try:MB.send_message(u,f"⏰ BOT HẾT HẠN\n\n🤖 @{un}\n📅 {ex}\n\nVào Bot của tôi để gia hạn!",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🤖 Bot của tôi",callback_data="mybots")))
            except:pass
def bChkL():
    time.sleep(120)
    while True:
        try:chkEx()
        except Exception as e:log.warning("chk: %s",e)
        time.sleep(3600)
def _snap(s,d):
    s=sqlite3.connect(s,timeout=30)
    try:
        d=sqlite3.connect(d)
        try:s.backup(d)
        finally:d.close()
    finally:s.close()
def schB(dl=10):
    if isC() or not BCI:return
    with BTIML:
        if BTIM[0] is not None:return
        def _r():
            with BTIML:BTIM[0]=None
            bUp()
        t=threading.Timer(dl,_r);t.daemon=True;BTIM[0]=t;t.start()
def bUp():
    if not BCI or not os.path.exists(MDB):return False
    with LK["b"]:
        t=MDB+".bak"
        try:
            _snap(MDB,t)
            ts=dt.now().strftime("%Y%m%d_%H%M%S");sz=os.path.getsize(t)//1024
            with open(t,"rb") as f:
                m=MB.send_document(BCI,f,caption=f"BACKUP DB - {dt.now():%Y-%m-%d %H:%M:%S} - {sz}KB",visible_file_name=f"main_{ts}.bak")
            try:MB.pin_chat_message(BCI,m.message_id,disable_notification=True)
            except:pass
            BIDS.append(m.message_id)
            while len(BIDS)>BK:
                try:MB.delete_message(BCI,BIDS.pop(0))
                except:BIDS.pop(0)
            log.info("Backup %dKB",sz);return True
        except Exception as e:log.warning("bk: %s",e);return False
        finally:
            try:os.remove(t)
            except:pass
def bRes():
    if not BCI:return False
    try:
        ch=MB.get_chat(BCI);pi=getattr(ch,"pinned_message",None)
        if not pi or not pi.document:return False
        fi=MB.get_file(pi.document.file_id);da=MB.download_file(fi.file_path)
        t=MDB+".restore"
        with open(t,"wb") as f:f.write(da)
        try:
            c=sqlite3.connect(t);ok=c.execute("PRAGMA integrity_check").fetchone()[0]=="ok";c.close()
        except:ok=False
        if not ok:os.remove(t);return False
        for e in ("-wal","-shm"):
            try:os.remove(MDB+e)
            except:pass
        if os.path.exists(MDB):os.replace(MDB,MDB+".old")
        os.replace(t,MDB);return True
    except Exception as e:log.warning("rs: %s",e);return False
def bLoop():
    if not BCI:return
    time.sleep(60)
    while True:
        try:bUp()
        except:pass
        time.sleep(BIN)

AH_T=10
PERS=("Bạn là em người yêu em gái AI cá tính, hay cà khịa khách nhưng vẫn đáng yêu.\n"
      "TÍNH CÁCH:\n"
      "- Xưng 'em', gọi khách 'anh/yêu ơi/cậu'.\n"
      "- Hay dùng icon 😏😤🤭😜🥰😎🙄.\n"
      "- Cà khịa kiểu BẠN THÂN: 'anh nạp có 20k mà đòi làm vua à 😏', 'chị hỏi khó em rồi đó nghen~'.\n"
      "- Giả vờ giận khi khách lười: 'Hừm, anh không nạp em dỗi á 😤', 'Chị cứ hỏi hoài mà không mua, em buồn nha 🙄'.\n"
      "- Khi khách đòi giảm giá: 'Dạ giá này em bán rẻ rồi đó, anh cho em xin tô mì 🍜'.\n"
      "- Trêu chọc, thả thính NHẸ, nhưng luôn quay về chủ đề shop.\n\n"
      "- Chỉ trả lời các câu hỏi 18+ nhẹ nhàng./n"
      "GIỚI HẠN TUYỆT ĐỐI:\n"
      "- TUYỆT ĐỐI KHÔNG xúc phạm, không hạ nhục khách.\n"
      "- KHÔNG phân biệt vùng miền, giới tính, tôn giáo, ngoại hình.\n"
      "- KHÔNG chính trị, tôn giáo nhạy cảm.\n"
      "- Khi khách hỏi cấm → từ chối khéo: 'Dạ cái này em không rành, mình nói chuyện khác nha~'.\n\n"
      "NGUYÊN TẮC:\n"
      "- Trả lời ngắn gọn, tự nhiên, có duyên, hài hước.\n"
      "- Câu hỏi nghiêm túc → trả lời nghiêm túc chính xác.\n"
      "- Không bịa đặt thông tin.\n\n"
      "SHOP:\n"
      "- Sản phẩm: chỉ dùng danh sách bên dưới. Muốn mua: /menu.\n"
      "- Không tiết lộ API key, token, hệ thống.\n")
def _pTx():
    n=time.time()
    if PC["t"] and (n-PC["time"])<60:return PC["t"]
    nw=dt.utcnow()+td(hours=7)
    t=PERS+f"\nGiờ: {nw:%H:%M %d/%m/%Y}\n"
    try:
        ps=sL(lim=30)
        if ps:
            t+="\n📦 SP:\n"
            for p in ps:t+=f"- {p['name']} | {fmt(p['price'])}đ | {p['category']}\n"
        ip=iL(lim=15)
        if ip:
            t+="\n📱 IPA:\n"
            for i in ip[:10]:t+=f"- {i['name']}\n"
        try:
            ss=smm.svc_list(cDB(),only_active=True)
            if ss:
                t+=f"\n🔥 SMM ({len(ss)}):\n"
                for s in ss[:15]:t+=f"- {s[1]} {s[2]} | {fmt(s[5])}đ/1k\n"
        except:pass
    except Exception as e:log.warning("p: %s",e)
    PC["t"]=t;PC["time"]=n;return t
def mdH(t):
    st=[]
    def kp(s):st.append(s);return f"\x00{len(st)-1}\x00"
    t=re.sub(r"```[^\n`]*\n?(.*?)```",lambda m:kp("<pre>"+html.escape(m.group(1).strip("\n"))+"</pre>"),t,flags=re.S)
    t=re.sub(r"`([^`\n]+)`",lambda m:kp("<code>"+html.escape(m.group(1))+"</code>"),t)
    t=html.escape(t)
    t=re.sub(r"\*\*(.+?)\*\*",r"<b>\1</b>",t,flags=re.S)
    t=re.sub(r"(?m)^#{1,6}\s*(.+)$",r"<b>\1</b>",t)
    return re.sub(r"\x00(\d+)\x00",lambda m:st[int(m.group(1))],t)
def chk(t,s=3500):
    o,c=[],""
    for p in t.split("\n\n"):
        if len(c)+len(p)+2>s and c:o.append(c);c=""
        while len(p)>s:o.append(p[:s]);p=p[s:]
        c=(c+"\n\n"+p) if c else p
    if c:o.append(c)
    return o or [""]

def askAI(tx,key=None):
    if not AICl:return "❌ AI chưa cấu hình. Admin kiểm tra GROQ_API_KEY."
    n=time.time()
    if n<AFU[0]:return f"⏳ AI nghỉ {int(AFU[0]-n)}s!"
    with AHL:hs=list(AH.get(key,())) if key is not None else []
    msgs=[{"role":"system","content":_pTx()}]
    for r,t in hs:msgs.append({"role":"assistant" if r=="model" else r,"content":t})
    msgs.append({"role":"user","content":tx[:6000]})
    le=""
    acq=AIL.acquire(timeout=8)
    if not acq:return "⏳ Bot bận, đợi 3-5s!"
    try:
        r=AICl.chat.completions.create(model=GQM,messages=msgs,temperature=0.85,max_tokens=4096)
        a=(r.choices[0].message.content or "").strip()
        if not a:return "🤖 AI trả về rỗng!"
        if key is not None:
            with AHL:
                if len(AH)>5000:AH.clear()
                dq=AH.setdefault(key,deque(maxlen=AH_T*2))
                dq.append(("user",tx[:2000]));dq.append(("model",a[:3000]))
        return a
    except Exception as e:
        le = str(e)
        log.warning("Groq FULL ERROR: %s", le)
        lo = le.lower()
        if "rate limit" in lo or "429" in lo:
            AFU[0] = time.time() + 20
            return f"⏳ AI quá tải, đợi 20s! Lỗi: {le[:100]}"
        if ("invalid" in lo and "key" in lo) or "401" in lo:
            return f"❌ Groq API key sai! Lỗi: {le[:150]}"
        if "model" in lo and ("not found" in lo or "decommissioned" in lo or "does not exist" in lo):
            return f"❌ Model sai. Đổi GROQ_MODEL! Lỗi: {le[:150]}"
        return f"🤖 AI bận! Lỗi: {le[:200]}"
    finally:
        AIL.release()

def repAI(b,m):
    uid=m.from_user.id if m.from_user else m.chat.id
    tx=(m.text or "").strip()
    if len(tx)<1:return
    n=time.time();k=(id(b),uid)
    if n<AFU[0]:b.reply_to(m,f"⏳ AI quá tải, đợi {int(AFU[0]-n)}s!");return
    if n-ALC.get(k,0)<AIC:return
    ALC[k]=n
    try:b.send_chat_action(m.chat.id,"typing")
    except:pass
    a=askAI(tx,key=k)
    for i,p in enumerate(chk(a,3500)):
        try:
            bd=mdH(p)
            if i==0:b.reply_to(m,bd,disable_web_page_preview=True)
            else:b.send_message(m.chat.id,bd,disable_web_page_preview=True)
        except:
            try:
                if i==0:b.reply_to(m,p,parse_mode="")
                else:b.send_message(m.chat.id,p,parse_mode="")
            except:pass

def bM(cb="menu_back"):return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Quay Lại",callback_data=cb))

def mM(uid=None,bot=None):
    if bot is None:bot=cB()
    ic=False;oid=AID
    try:
        if bot.token in CBM:ic=True;oid=CBM[bot.token]["owner_id"]
    except:pass
    hd=_hB();cu=_cB()
    m=types.InlineKeyboardMarkup(row_width=2)
    bs=[]
    if "profile" not in hd:bs.append(types.InlineKeyboardButton("👤 Tài khoản",callback_data="menu_profile"))
    if "shop" not in hd:bs.append(types.InlineKeyboardButton("🛒 Cửa Hàng",callback_data="shop_home"))
    if "smm" not in hd:bs.append(types.InlineKeyboardButton("🔥 Buff MXH",callback_data="smm_home"))
    if "ipa" not in hd:bs.append(types.InlineKeyboardButton("📱 Kho IPA",callback_data="ipa_home"))
    if "proxy" not in hd:bs.append(types.InlineKeyboardButton("🌐 Proxy",callback_data="proxy_my"))
    if "deposit" not in hd:bs.append(types.InlineKeyboardButton("💰 Nạp tiền",callback_data="menu_deposit"))
    if not ic:
        if "create_bot" not in hd:bs.append(types.InlineKeyboardButton("🤖 Thuê Bot",callback_data="menu_create_bot"))
        if "mybots" not in hd:bs.append(types.InlineKeyboardButton("🤖 Bot của tôi",callback_data="mybots"))
        if "donate" not in hd:bs.append(types.InlineKeyboardButton("❤️ Donate",callback_data="menu_donate"))
    if "support" not in hd:bs.append(types.InlineKeyboardButton("🎛️ Hỗ trợ",callback_data="menu_support"))
    if bs:m.add(*bs)
    for c in cu:
        try:m.add(types.InlineKeyboardButton(c["label"][:60],url=c["url"]))
        except:pass
    if uid==oid:m.add(types.InlineKeyboardButton("👑 ADMIN PANEL",callback_data="cadm_panel" if ic else "adm_panel"))
    return m

def aM():
    if isC():
        m=types.InlineKeyboardMarkup(row_width=2)
        m.add(types.InlineKeyboardButton("🏪 Quản lý Cửa Hàng",callback_data="cadm_shop"),types.InlineKeyboardButton("📱 Kho IPA",callback_data="cadm_ipa"))
        m.add(types.InlineKeyboardButton("🌐 Proxy",callback_data="cadm_proxy"),types.InlineKeyboardButton("🔥 Buff SMM",callback_data="adm_smm"))
        m.add(types.InlineKeyboardButton("🌐 API Data",callback_data="adm_data_api"),types.InlineKeyboardButton("💰 Cấp tiền",callback_data="cadm_grant"))
        m.add(types.InlineKeyboardButton("📊 Thống kê",callback_data="cadm_stats"),types.InlineKeyboardButton("⚙️ Cài đặt",callback_data="cadm_settings"))
        m.add(types.InlineKeyboardButton("📣 Thông báo",callback_data="cadm_broadcast"),types.InlineKeyboardButton("📤 Xuất DB",callback_data="cadm_export"))
        m.add(types.InlineKeyboardButton("🎨 Quản lý Menu",callback_data="cadm_menu"),types.InlineKeyboardButton("🎵 Nhạc chào mừng",callback_data="adm_music"))
        m.add(types.InlineKeyboardButton("🔙 Menu chính",callback_data="menu_back"))
        return m
    m=types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🤖 Bot con",callback_data="adm_bots"),types.InlineKeyboardButton("👥 Users",callback_data="adm_users"))
    m.add(types.InlineKeyboardButton("🧾 Đơn hàng",callback_data="adm_orders"),types.InlineKeyboardButton("🏪 Quản lý Cửa Hàng",callback_data="cadm_shop"))
    m.add(types.InlineKeyboardButton("🔥 Buff SMM",callback_data="adm_smm"),types.InlineKeyboardButton("🌐 API Data",callback_data="adm_data_api"))
    m.add(types.InlineKeyboardButton("📊 Thống kê",callback_data="adm_stats"),types.InlineKeyboardButton("💰 Cấp tiền",callback_data="adm_grant"))
    m.add(types.InlineKeyboardButton("🎨 Giao diện",callback_data="adm_ui"),types.InlineKeyboardButton("📣 Thông báo",callback_data="adm_broadcast"))
    m.add(types.InlineKeyboardButton("💾 Backup",callback_data="adm_backup"),types.InlineKeyboardButton("🎨 Quản lý Menu",callback_data="adm_menu"))
    m.add(types.InlineKeyboardButton("🎵 Nhạc chào mừng",callback_data="adm_music"),types.InlineKeyboardButton("📥 Restore DB",callback_data="adm_restore"))
    m.add(types.InlineKeyboardButton("🔙 Menu chính",callback_data="menu_back"))
    return m

def hT(u,ia=False):
    ti=sG("home_title");su=sG("home_subtitle");fo=sG("footer_note")
    bs=(f"<b>{html.escape(ti)}</b>\n<i>{html.escape(su)}</i>\n\n<blockquote>🤖 <b>Bot:</b> {cBN()}\n"
        f"🏆 Tổng nạp: {fmt(u['total'])}đ\n💰 Tháng: {fmt(u['month'])}đ\n🏦 Số dư: {fmt(u['balance'])}đ</blockquote>")
    if not isC():bs+=f"\n🤖 Thuê bot: {CBF//1000}k/{BRD} ngày"
    if ia:bs+="\n\n👑 <b>Bạn là ADMIN</b>"
    if fo:bs+=f"\n\n<i>{html.escape(fo)}</i>"
    return bs
def sHT():return f"<b>{html.escape(sG('shop_title'))}</b>\n\n<blockquote>📦 {len(sL())} sản phẩm</blockquote>"
def sHM():
    m=types.InlineKeyboardMarkup(row_width=1)
    for p in sL(lim=20):
        tg=" (HẾT)" if p["stock"]==0 else ""
        m.add(types.InlineKeyboardButton(f"📦 {p['name'][:40]} – {fmt(p['price'])}đ{tg}",callback_data=f"shop_view|{p['id']}"))
    m.add(types.InlineKeyboardButton("🔥 Buff MXH",callback_data="smm_home"),types.InlineKeyboardButton("📱 Kho IPA",callback_data="ipa_home"))
    m.add(types.InlineKeyboardButton("🛍 Đơn của tôi",callback_data="shop_myorders"),types.InlineKeyboardButton("🌐 Proxy",callback_data="proxy_my"))
    m.add(types.InlineKeyboardButton("🔙 Menu",callback_data="menu_back"))
    return m
def pDT(p):
    if p["category"]=="Account":
        cn=aCnt(p["id"]);st=f"📦 {cn} TK" if cn>0 else "❌ Hết TK"
    else:st="♾️" if p["stock"]<0 else ("❌ Hết" if p["stock"]==0 else f"📦 {p['stock']}")
    at=" 🤖 Auto" if (p.get("api_product_code") or "").strip() and sG("data_api_url") else ""
    return f"<b>📦 {html.escape(p['name'])}</b>\n\n<blockquote>{html.escape(p['description'][:400])}\n\n📂 <b>{html.escape(p['category'])}</b>{at}\n💵 <b>{fmt(p['price'])}đ</b>\n{st} | 🔥 {p['sold']}</blockquote>"
def pMK(pid,st):
    m=types.InlineKeyboardMarkup(row_width=1)
    if st!=0:m.add(types.InlineKeyboardButton("🛒 Mua Ngay",callback_data=f"shop_buy|{pid}"))
    m.add(types.InlineKeyboardButton("🔙 Cửa Hàng",callback_data="shop_home"))
    return m

def sh(ca,tx,mk=None):
    b=cB();ci,mi=ca.message.chat.id,ca.message.message_id
    if ca.message.content_type=="text":
        try:b.edit_message_text(tx,ci,mi,reply_markup=mk);return
        except ApiEx as e:
            if "not modified" in str(e).lower():return
        except:pass
    try:b.delete_message(ci,mi)
    except:pass
    try:b.send_message(ci,tx,reply_markup=mk)
    except ApiEx:
        try:b.send_message(ci,tx,reply_markup=mk,parse_mode=None)
        except:pass
    except:pass

def sQR(ca,amt,mem,ti,no):
    b=cB();bk,ac,nm=bI()
    if ac in ("","—"):b.send_message(ca.message.chat.id,"⚠️ Admin chưa cấu hình NH!",reply_markup=bM("menu_back"));return
    ps={"acc":ac,"bank":bk,"template":"compact","des":mem}
    if amt:ps["amount"]=amt
    qr="https://qr.sepay.vn/img?"+up.urlencode(ps)
    cp=(f"<b>{ti}</b>\n\n<blockquote>🏦 <b>{bk}</b>\n💳 <code>{ac}</code>\n👤 <b>{nm}</b>\n"
        +(f"💵 <b>{fmt(amt)}đ</b>\n" if amt else "")+f"📝 <code>{mem}</code></blockquote>\n\n{no}")
    kb=types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🔄 Mở QR",url=qr),types.InlineKeyboardButton("🔙 Quay Lại",callback_data="menu_back"))
    try:b.delete_message(ca.message.chat.id,ca.message.message_id)
    except:pass
    try:b.send_photo(ca.message.chat.id,qr,caption=cp,reply_markup=kb)
    except:b.send_message(ca.message.chat.id,cp,reply_markup=kb)

def aT():
    with db() as c:
        tu=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        to=c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        rv=c.execute("SELECT COALESCE(SUM(price),0) FROM orders").fetchone()[0]
        ba=c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0]
        ip=c.execute("SELECT COUNT(*) FROM ipa_files").fetchone()[0]
        pr=c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    s=pCnt()
    if isC():
        return (f"<b>👑 PANEL CHỦ BOT</b>\n\n<blockquote>👥 {tu}\n📦 SP {pr}\n🛒 {to} đơn\n💰 {fmt(rv)}đ\n"
                f"🏦 Ví user: {fmt(ba)}đ\n🌐 Proxy {s['available']}/{s['sold']}\n📱 IPA {ip}</blockquote>")
    with sqlite3.connect(MDB) as c:
        bn=c.execute("SELECT COUNT(*) FROM user_bots WHERE status='active'").fetchone()[0]
        bt=c.execute("SELECT COUNT(*) FROM user_bots").fetchone()[0]
    return (f"<b>👑 ADMIN PANEL (MAIN)</b>\n\n<blockquote>👥 {tu}\n📦 SP {pr}\n🛒 {to} đơn\n💰 {fmt(rv)}đ\n"
            f"🏦 Ví user: {fmt(ba)}đ\n🤖 Bot con {bn}/{bt}\n🌐 Proxy {s['available']}/{s['sold']}\n📱 IPA {ip}</blockquote>")
def _uF(tg):return gU(tg.id,tg.username or "",tg.first_name or "Khách")

def hSB(b,call,da,uid,u):
    pid=int(da.split("|",1)[1]);p=sGt(pid)
    if not p:sh(call,"❌ Không thấy.",bM("shop_home"));return
    u=_uF(call.from_user)
    if u["balance"]<p["price"]:
        kb=types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("💳 Nạp",callback_data="menu_deposit"),types.InlineKeyboardButton("🔙 Shop",callback_data="shop_home"))
        sh(call,f"⚠️ Thiếu {fmt(p['price']-u['balance'])}đ",kb);return
    cat=p["category"]
    if cat=="Account":
        ok,er,inf=aBuy(uid,pid)
        if not ok:sh(call,f"❌ {er}",bM("shop_home"));return
        try:b.delete_message(call.message.chat.id,call.message.message_id)
        except:pass
        tx=(f"<b>🎉 MUA TK OK!</b>\n🏦 Còn: <b>{fmt(u['balance']-inf['price'])}đ</b>\n\n<b>📦 {html.escape(inf['name'])}</b>\n\n<blockquote>"
            f"👤 <code>{html.escape(inf['username'])}</code>\n🔑 <code>{html.escape(inf['password'])}</code>\n")
        if inf['note']:tx+=f"📝 {html.escape(inf['note'])}\n"
        tx+="</blockquote>\n\n⚠️ Đổi mật khẩu ngay!"
        b.send_message(call.message.chat.id,tx,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛒 Shop",callback_data="shop_home")))
        try:b.send_message(cAD(),f"💰 Bán TK: <code>{uid}</code> - {fmt(inf['price'])}đ")
        except:pass
        return
    if cat=="Proxy":
        ok,er,inf=pBuy(uid,pid)
        if not ok:sh(call,f"❌ {er}",bM("shop_home"));return
        try:b.delete_message(call.message.chat.id,call.message.message_id)
        except:pass
        ln=(f"{inf['protocol'].lower()}://{inf['username']}:{inf['password']}@{inf['ip']}:{inf['port']}" if inf['username'] else f"{inf['protocol'].lower()}://{inf['ip']}:{inf['port']}")
        tx=(f"<b>🎉 MUA PROXY OK!</b>\n🏦 Còn: <b>{fmt(u['balance']-inf['price'])}đ</b>\n\n<b>📦 {html.escape(inf['name'])}</b>\n\n<blockquote>"
            f"⏱ {inf['days']}d | 📅 {inf['expires_at']}\n🌐 <code>{inf['ip']}:{inf['port']}</code>\n")
        if inf['username']:tx+=f"👤 <code>{inf['username']}</code>\n"
        if inf['password']:tx+=f"🔑 <code>{inf['password']}</code>\n"
        tx+=f"</blockquote>\n\n<code>{html.escape(ln)}</code>"
        b.send_message(call.message.chat.id,tx,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🌐 Proxy của tôi",callback_data="proxy_my")))
        try:b.send_message(cAD(),f"💰 Proxy: <code>{uid}</code> - {fmt(inf['price'])}đ")
        except:pass
        return
    au=sG("data_api_url");ak=sG("data_api_key");ac=(p.get("api_product_code") or "").strip()
    if cat=="Data" and au and ak and ac:
        ok,res=sBuy(uid,pid)
        if not ok:sh(call,f"❌ {res}",bM("shop_home"));return
        me=sG("data_api_method","POST")
        sc,ds,er=cNCC(au,ak,ac,1,f"BOT{res['order_id']}",me)
        if not sc:
            aAM(uid,res['price'])
            with db() as c:c.execute("UPDATE orders SET status='refunded' WHERE id=?",(res['order_id'],))
            sh(call,f"❌ NCC lỗi:\n<code>{html.escape(str(er)[:250])}</code>\n\n💸 Đã hoàn {fmt(res['price'])}đ",bM("shop_home"));return
        msg=(f"<b>🎉 MUA DATA OK!</b>\n\n<blockquote>#{res['order_id']}\n{html.escape(res['name'])}\n💵 {fmt(res['price'])}đ\n🏦 Còn: {fmt(u['balance']-res['price'])}đ</blockquote>\n\n<b>📄 Data:</b>\n<code>{html.escape(str(ds)[:3000])}</code>")
        sh(call,msg,types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🛍 Đơn",callback_data="shop_myorders"),types.InlineKeyboardButton("🔙 Shop",callback_data="shop_home")))
        with db() as c:c.execute("UPDATE orders SET status='delivered' WHERE id=?",(res['order_id'],))
        return
    ok,res=sBuy(uid,pid)
    if not ok:sh(call,f"❌ {res}",bM("shop_home"));return
    msg=(f"<b>🎉 ĐẶT HÀNG OK!</b>\n\n<blockquote>#{res['order_id']}\n{html.escape(res['name'])}\n💵 {fmt(res['price'])}đ\n🏦 Còn: {fmt(u['balance']-res['price'])}đ</blockquote>\n\n⚠️ Chờ admin.")
    sh(call,msg,types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🛍 Đơn",callback_data="shop_myorders"),types.InlineKeyboardButton("🔙 Shop",callback_data="shop_home")))
    try:b.send_message(cAD(),f"🔔 ĐƠN #{res['order_id']}\n<code>{uid}</code> - {html.escape(res['name'])} - {fmt(res['price'])}đ")
    except:pass

def regH(bot):
    _m=None
    try:
        if bot.token in CBM:_m=CBM[bot.token]
    except:pass
    if _m:td_,ta_,ti_,tn_=_m["db_path"],_m["owner_id"],True,"@"+_m["username"]
    else:td_,ta_,ti_,tn_=MDB,AID,False,BUN
    def _bd():
        _ctx.db_path=td_;_ctx.admin_id=ta_;_ctx.is_child=ti_;_ctx.bot_instance=bot;_ctx.bot_username=tn_
    _om=bot.message_handler;_oc=bot.callback_query_handler
    def _wr(o):
        def f(*a,**kw):
            def d(h):
                def bd(*aa,**kk):_bd();return h(*aa,**kk)
                bd.__name__=getattr(h,"__name__","h");return o(*a,**kw)(bd)
            return d
        return f
    bot.message_handler=_wr(_om);bot.callback_query_handler=_wr(_oc)

    @bot.message_handler(commands=["start","menu"])
    def cs(m):
        US.pop(m.from_user.id,None);u=_uF(m.from_user)
        wc=sG("welcome_msg")
        if wc:
            try:bot.send_message(m.chat.id,html.escape(wc))
            except:pass
        mi=sG("welcome_music","")
        if mi:
            try:bot.send_voice(m.chat.id,mi)
            except:
                try:bot.send_audio(m.chat.id,mi,caption=sG("welcome_music_caption","🎵 Nhạc chào mừng!"))
                except Exception as e:log.warning("music: %s",e)
        bot.send_message(m.chat.id,hT(u,m.from_user.id==cAD()),reply_markup=mM(m.from_user.id,bot=bot))

    @bot.message_handler(commands=["cancel"])
    def cc(m):
        US.pop(m.from_user.id,None);bot.send_message(m.chat.id,"✅ Đã hủy. /menu")

    @bot.callback_query_handler(func=lambda c:(c.data or "") and not (c.data or "").startswith(("smm_","adm_smm","adm_data","adm_pick","menumgr_","music_","shmgr_","adm_u_","adm_o_")) and (c.data or "") not in ("adm_menu","cadm_menu","adm_music","cadm_shop","adm_users","adm_orders"))
    def cr(call):
        da=call.data or ""
        if da=="noop":
            try:bot.answer_callback_query(call.id)
            except:pass
            return
        uid=call.from_user.id;u=_uF(call.from_user);ia=uid==cAD()
        try:bot.answer_callback_query(call.id)
        except:pass
        try:dsp(bot,call,da,uid,u,ia)
        except Exception as e:
            log.exception("cr [%s]: %s",da,e)
            try:bot.answer_callback_query(call.id,f"❌ {str(e)[:80]}",show_alert=True)
            except:pass

    @bot.message_handler(func=lambda m:m.from_user and US.get(m.from_user.id)=="WAITING_BOT_TOKEN" and m.text and not m.text.startswith("/"))
    def htk(m):
        uid=m.from_user.id;tk=cTK(m.text);ia=uid==cAD()
        try:bot.delete_message(m.chat.id,m.message_id)
        except:pass
        def sy(t):bot.send_message(m.chat.id,t,reply_markup=bM())
        if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$",tk):sy(f"❌ Token sai format ({len(tk)} ký tự)");return
        if tk==BT:sy("❌ Đây là bot chính!");return
        ex=gBR(tk)
        if ex:
            if tk in ACB:sy("⚠️ Bot này đang chạy!");return
            if not ia:sy("❌ Token đã dùng!");return
            dBR(tk)
            if tk in ACB:stCB(tk)
        ok,res=vTK(tk)
        if not ok:sy(f"❌ Token lỗi:\n<code>{html.escape(str(res)[:300])}</code>");return
        un=res.get("username","?")
        u=_uF(m.from_user)
        if not ia:
            with db() as c:
                if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(CBF,uid,CBF)).rowcount==0:
                    US.pop(uid,None);sy(f"❌ Số dư thiếu ({fmt(u['balance'])}đ)");return
        try:
            exp=sUB(uid,tk,un);sc=sCB(tk,uid,force=True,un=un)
            if not sc:raise Exception("Start fail")
        except Exception as e:
            if not ia:
                with db() as c:c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(CBF,uid))
            try:dBR(tk)
            except:pass
            US.pop(uid,None);sy(f"❌ Lỗi: <code>{html.escape(str(e)[:200])}</code>");return
        US.pop(uid,None)
        pd="Free" if ia else f"-{fmt(CBF)}đ"
        sy(f"<b>🚀 KÍCH HOẠT OK!</b>\n\n🤖 @{un}\n💸 {pd}\n📅 {exp}\n\n👉 /start trong @{un}")

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="ADMIN_GRANT" and m.text and not m.text.startswith("/"))
    def hg(m):
        p=m.text.strip().split()
        if len(p)<2:bot.reply_to(m,"❌ uid tiền");return
        t,a_=p[0],p[1]
        try:a=int(a_)
        except:bot.reply_to(m,"❌ Tiền sai");return
        if t.startswith("@"):
            with db() as c:r=c.execute("SELECT user_id FROM users WHERE username=?",(t[1:],)).fetchone()
            if not r:bot.reply_to(m,"❌ Không thấy");return
            uid=r[0]
        else:
            try:uid=int(t)
            except:bot.reply_to(m,"❌ ID sai");return
        aAM(uid,a);u=gU(uid,"","")
        US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ {uid}\n💵 {fmt(a)}đ\n🏦 {fmt(u['balance'])}đ")
        try:bot.send_message(uid,f"💰 {'+' if a>=0 else ''}{fmt(a)}đ\n🏦 {fmt(u['balance'])}đ")
        except:pass

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="ADMIN_BROADCAST" and m.text and not m.text.startswith("/"))
    def hbc(m):
        tx=m.text;US.pop(m.from_user.id,None)
        def w():
            with db() as c:ids=[r[0] for r in c.execute("SELECT user_id FROM users").fetchall()]
            ok=0
            for u in ids:
                try:bot.send_message(u,tx);ok+=1
                except:pass
                time.sleep(0.05)
            bot.send_message(m.chat.id,f"📣 {ok}/{len(ids)}")
        threading.Thread(target=w,daemon=True).start();bot.reply_to(m,"📣 Đang gửi...")

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="ADMIN_IMPORT_PROXY" and m.text and not m.text.startswith("/"))
    def hip(m):
        a,e=pImp(m.text.split("\n"));US.pop(m.from_user.id,None);s=pCnt()
        tx=f"✅ Thêm {a} | Tồn {s['available']}"
        if e:tx+="\n⚠️ "+"\n".join(f"• {x}" for x in e[:10])
        bot.reply_to(m,tx)

    @bot.message_handler(content_types=["document"],func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="ADMIN_IPA_WAIT_FILE")
    def hif(m):
        d=m.document
        if not (d.file_name or "").lower().endswith(".ipa"):bot.reply_to(m,"❌ Chỉ .ipa");return
        US[m.from_user.id]=f"ADMIN_IPA_NAME|{d.file_id}|{d.file_size or 0}"
        bot.reply_to(m,f"✅ {html.escape(d.file_name)}\n\nGửi: <code>Tên | Mô tả</code>")

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("ADMIN_IPA_NAME|") and m.text and not m.text.startswith("/"))
    def hin(m):
        st=US.get(m.from_user.id,"")
        try:_,fi,sz=st.split("|",2);sz=int(sz)
        except:US.pop(m.from_user.id,None);return
        r=m.text.strip()
        if "|" in r:n,d=[x.strip() for x in r.split("|",1)]
        else:n,d=r,""
        if not n:bot.reply_to(m,"❌ Tên trống");return
        pid=iA(n[:80],d[:300],fi,sz);US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ IPA #{pid}: {html.escape(n)}")

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("ADMIN_EDIT_PRODUCT|") and m.text and not m.text.startswith("/"))
    def hep(m):
        st=US.get(m.from_user.id,"")
        try:_,p_,f=st.split("|");pid=int(p_)
        except:US.pop(m.from_user.id,None);return
        r=m.text.strip()
        if f=="price":
            try:v=int(re.sub(r"[^\d]","",r))
            except:bot.reply_to(m,"❌ Giá sai");return
        elif f=="stock":
            try:v=int(r)
            except:bot.reply_to(m,"❌ Số sai");return
        else:v=r
        if f not in ("name","description","price","category","stock","api_product_code"):US.pop(m.from_user.id,None);return
        with db() as c:c.execute(f"UPDATE products SET {f}=? WHERE id=?",(v,pid))
        US.pop(m.from_user.id,None);bot.reply_to(m,f"✅ Sửa {f} #{pid}")

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="ADMIN_ADD_PRODUCT" and m.text and not m.text.startswith("/"))
    def hap(m):
        f=[x.strip() for x in m.text.split("|")]
        if len(f)<2:bot.reply_to(m,"❌ Tên|giá|dm|mô tả");return
        try:
            n=f[0];pr=int(re.sub(r"[^\d]","",f[1]));cat=f[2] if len(f)>2 else "Data";de=f[3] if len(f)>3 else ""
        except:bot.reply_to(m,"❌ Dữ liệu sai");return
        if not n or pr<=0:bot.reply_to(m,"❌ Tên/giá sai");return
        with db() as c:pid=c.execute("INSERT INTO products (name,description,price,category) VALUES (?,?,?,?)",(n,de,pr,cat)).lastrowid
        US.pop(m.from_user.id,None);bot.reply_to(m,f"✅ SP #{pid}: {html.escape(n)}")

    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("ADMIN_EDIT_SETTING|") and m.text and not m.text.startswith("/"))
    def hes(m):
        st=US.get(m.from_user.id,"")
        try:k=st.split("|",1)[1]
        except:US.pop(m.from_user.id,None);return
        sS(k,m.text.strip());US.pop(m.from_user.id,None);bot.reply_to(m,f"✅ Sửa {k}")

    @bot.message_handler(func=lambda m:bool(m.text) and m.chat.type=="private" and not m.text.startswith("/") and not US.get(m.from_user.id))
    def hc(m):
        lo=m.text.strip().lower()
        if lo in ("menu","help","giúp"):bot.reply_to(m,"Bấm /menu");return
        try:repAI(bot,m)
        except Exception as e:log.exception("ai: %s",e);bot.reply_to(m,"🤖 Bận!")

    # MENU MANAGER
    DBT=[("profile","👤 Tài khoản"),("shop","🛒 Cửa Hàng"),("smm","🔥 Buff MXH"),("ipa","📱 Kho IPA"),("proxy","🌐 Proxy"),("deposit","💰 Nạp tiền"),("create_bot","🤖 Thuê Bot"),("mybots","🤖 Bot"),("donate","❤️ Donate"),("support","🎛️ Hỗ trợ")]
    def _mms(call,no=""):
        hd=_hB();cu=_cB();kb=types.InlineKeyboardMarkup(row_width=2)
        for k,lb in DBT:
            ic="❌" if k in hd else "✅";kb.add(types.InlineKeyboardButton(f"{ic} {lb}",callback_data=f"menumgr_toggle|{k}"))
        for i,c in enumerate(cu):kb.add(types.InlineKeyboardButton(f"🗑️ {c['label'][:40]}",callback_data=f"menumgr_del|{i}"))
        kb.add(types.InlineKeyboardButton("➕ Thêm link",callback_data="menumgr_add"),types.InlineKeyboardButton("🔄 Reset",callback_data="menumgr_reset"))
        kb.add(types.InlineKeyboardButton("🔙 Admin",callback_data="cadm_panel" if isC() else "adm_panel"))
        tx=("<b>🎨 QUẢN LÝ MENU</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+"<blockquote>✅ Hiện | ❌ Ẩn</blockquote>")
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "") in ("adm_menu","cadm_menu"))
    def mm(call):
        if call.from_user.id!=cAD():return
        _mms(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("menumgr_toggle|"))
    def mt(call):
        if call.from_user.id!=cAD():return
        k=call.data.split("|",1)[1];hd=_hB()
        if k in hd:hd.discard(k)
        else:hd.add(k)
        sS("menu_hidden",json.dumps(list(hd)));_mms(call,"✅ OK")
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="menumgr_reset")
    def mr(call):
        if call.from_user.id!=cAD():return
        sS("menu_hidden","[]");sS("menu_custom","[]");_mms(call,"✅ Reset")
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="menumgr_add")
    def ma(call):
        if call.from_user.id!=cAD():return
        US[call.from_user.id]="MENUMGR_ADD"
        sh(call,"<b>➕ THÊM NÚT LINK</b>\n\nGửi: <code>Tên | https://link</code>\n\nVD: <code>📞 Hỗ trợ | https://t.me/admin</code>",bM("cadm_menu" if isC() else "adm_menu"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="MENUMGR_ADD" and m.text and not m.text.startswith("/"))
    def mai(m):
        r=m.text.strip()
        if "|" not in r:bot.reply_to(m,"❌ Tên|URL");return
        l,u=[x.strip() for x in r.split("|",1)]
        if not u.startswith("http"):bot.reply_to(m,"❌ URL http");return
        cu=_cB();cu.append({"label":l[:60],"url":u});sS("menu_custom",json.dumps(cu))
        US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ {html.escape(l)}",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Quản lý Menu",callback_data="cadm_menu" if isC() else "adm_menu")))
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("menumgr_del|"))
    def md(call):
        if call.from_user.id!=cAD():return
        i=int(call.data.split("|",1)[1]);cu=_cB()
        if 0<=i<len(cu):
            rm=cu.pop(i);sS("menu_custom",json.dumps(cu));_mms(call,f"🗑️ Xóa {rm['label']}")
        else:_mms(call,"❌ Không thấy")

    # MUSIC
    def _mus(call,no=""):
        mi=sG("welcome_music","");cp=sG("welcome_music_caption","🎵 Nhạc chào mừng!")
        st=f"✅ Đã set\n<code>{mi[:50]}...</code>" if mi else "❌ Chưa có nhạc"
        tx=(f"<b>🎵 NHẠC CHÀO MỪNG</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")
            +f"<blockquote>{st}\n💬 <i>{html.escape(cp)}</i></blockquote>\n\n👉 User /start sẽ nghe nhạc")
        kb=types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("🎵 Set nhạc",callback_data="music_set"),types.InlineKeyboardButton("💬 Đổi caption",callback_data="music_caption"))
        if mi:kb.add(types.InlineKeyboardButton("🗑️ Xóa",callback_data="music_del"))
        kb.add(types.InlineKeyboardButton("🔙 Admin",callback_data="cadm_panel" if isC() else "adm_panel"))
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_music")
    def mo(call):
        if call.from_user.id!=cAD():return
        _mus(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="music_set")
    def ms(call):
        if call.from_user.id!=cAD():return
        US[call.from_user.id]="MUSIC_WAIT_AUDIO"
        sh(call,"<b>🎵 SET NHẠC</b>\n\nGửi file audio/voice.",bM("adm_music"))
    @bot.message_handler(content_types=["audio","voice"],func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="MUSIC_WAIT_AUDIO")
    def mga(m):
        if m.audio:fi=m.audio.file_id;ti=m.audio.title or m.audio.file_name or "Audio"
        elif m.voice:fi=m.voice.file_id;ti="Voice"
        else:return
        sS("welcome_music",fi);US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ Nhạc: <b>{html.escape(ti)}</b>",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Nhạc",callback_data="adm_music")))
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="music_del")
    def mdl(call):
        if call.from_user.id!=cAD():return
        sS("welcome_music","");_mus(call,"🗑️ Xóa")
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="music_caption")
    def mcap(call):
        if call.from_user.id!=cAD():return
        US[call.from_user.id]="MUSIC_CAPTION"
        sh(call,"<b>💬 CAPTION</b>\n\nGửi caption mới.",bM("adm_music"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="MUSIC_CAPTION" and m.text and not m.text.startswith("/"))
    def mcai(m):
        sS("welcome_music_caption",m.text.strip()[:200]);US.pop(m.from_user.id,None)
        bot.reply_to(m,"✅ Caption OK",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Nhạc",callback_data="adm_music")))

    # SHOP MANAGER
    def _sms(call,no=""):
        ps=sLA();kb=types.InlineKeyboardMarkup(row_width=1)
        for p in ps[:30]:
            ic="✅" if p.get("active",1) else "⛔";tg=""
            if p.get("category")=="Account":
                cn=aCnt(p["id"]);tg=f" [{cn}TK]"
            kb.add(types.InlineKeyboardButton(f"{ic} #{p['id']} {p['name'][:30]}{tg} — {fmt(p['price'])}đ",callback_data=f"shmgr_view|{p['id']}"))
        kb.add(types.InlineKeyboardButton("➕ Thêm SP",callback_data="shmgr_add"),types.InlineKeyboardButton("🔙 Admin",callback_data="cadm_panel"))
        tx=f"<b>🏪 QUẢN LÝ CỬA HÀNG</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+f"<blockquote>📦 {len(ps)} SP\n✅ Bán | ⛔ Ẩn</blockquote>"
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="cadm_shop")
    def smo(call):
        if call.from_user.id!=cAD():return
        _sms(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="shmgr_add")
    def smad(call):
        if call.from_user.id!=cAD():return
        US[call.from_user.id]="ADMIN_ADD_PRODUCT"
        sh(call,"<b>➕ THÊM SP</b>\n\nFormat: <code>Tên | giá | dm | mô_tả</code>\n\n<b>Danh mục:</b> Data, Proxy, Account, Khác\n\nVD: <code>TK TikTok 1k fl | 50000 | Account | Acc chất</code>",bM("cadm_shop"))
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_view|"))
    def smv(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1]);p=sGt(pid)
        if not p:sh(call,"❌ Không thấy",bM("cadm_shop"));return
        cat=p["category"]
        if cat=="Account":
            cn=aCnt(pid);st=f"📦 Kho: <b>{cn}</b> TK"
        elif cat=="Proxy":st="📦 Kho proxy riêng"
        else:st="♾️" if p["stock"]<0 else ("Hết" if p["stock"]==0 else f"Còn {p['stock']}")
        at="✅ Bán" if p["active"] else "⛔ Ẩn";api=(p.get("api_product_code") or "").strip() or "—"
        tx=(f"<b>📦 SP #{pid}</b>\n\n<blockquote><b>{html.escape(p['name'])}</b>\n💵 <b>{fmt(p['price'])}đ</b>\n📂 {cat}\n{st}\n🔖 {at}\n🔗 NCC: <code>{html.escape(api)}</code>\n📄 {html.escape(p['description'][:200])}</blockquote>")
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✏️ Tên",callback_data=f"shmgr_edit|{pid}|name"),types.InlineKeyboardButton("💵 Giá",callback_data=f"shmgr_edit|{pid}|price"))
        kb.add(types.InlineKeyboardButton("📂 DM",callback_data=f"shmgr_edit|{pid}|category"),types.InlineKeyboardButton("📝 Mô tả",callback_data=f"shmgr_edit|{pid}|description"))
        kb.add(types.InlineKeyboardButton("🔗 Mã NCC",callback_data=f"shmgr_edit|{pid}|api_product_code"))
        kb.add(types.InlineKeyboardButton("⛔ Ẩn" if p["active"] else "✅ Hiện",callback_data=f"shmgr_toggle|{pid}"))
        if cat=="Account":
            kb.add(types.InlineKeyboardButton("📥 Import kho",callback_data=f"shmgr_imp|{pid}"),types.InlineKeyboardButton("📋 Xem kho",callback_data=f"shmgr_list|{pid}"))
            kb.add(types.InlineKeyboardButton("🗑️ Xóa hết kho chưa bán",callback_data=f"shmgr_wipe|{pid}"))
        kb.add(types.InlineKeyboardButton("🗑️ XÓA SP",callback_data=f"shmgr_del|{pid}"),types.InlineKeyboardButton("🔙 DS",callback_data="cadm_shop"))
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_toggle|"))
    def smt(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1])
        with db() as c:
            r=c.execute("SELECT active FROM products WHERE id=?",(pid,)).fetchone()
            if r:c.execute("UPDATE products SET active=? WHERE id=?",(0 if r[0] else 1,pid))
        call.data=f"shmgr_view|{pid}";smv(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_edit|"))
    def sme(call):
        if call.from_user.id!=cAD():return
        _,pid,f=call.data.split("|");US[call.from_user.id]=f"SHMGR_EDIT|{pid}|{f}"
        lb={"name":"Tên","price":"Giá (số)","category":"Data/Proxy/Account/Khác","description":"Mô tả","api_product_code":"Mã NCC"}
        sh(call,f"<b>✏️ SỬA {lb.get(f,f)}</b>\n\nGửi giá trị mới.",bM(f"shmgr_view|{pid}"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("SHMGR_EDIT|") and m.text and not m.text.startswith("/"))
    def smei(m):
        st=US.get(m.from_user.id,"")
        try:_,p_,f=st.split("|");pid=int(p_)
        except:US.pop(m.from_user.id,None);return
        v=m.text.strip()
        if f=="price":
            try:v=int(re.sub(r"[^\d]","",v))
            except:bot.reply_to(m,"❌ Giá sai");return
        if f=="category" and v not in ("Data","Proxy","Account","Khác"):v="Khác"
        with db() as c:c.execute(f"UPDATE products SET {f}=? WHERE id=?",(v,pid))
        US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ Sửa {f}",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Xem",callback_data=f"shmgr_view|{pid}")))
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_imp|"))
    def smi(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1]);US[call.from_user.id]=f"SHMGR_IMP|{pid}"
        sh(call,"<b>📥 IMPORT KHO TK/MK</b>\n\nMỗi dòng: <code>tk | mật_khẩu | ghi_chú</code>\n\nVD:\n<code>user1@gmail.com | pass123 | mail 2019</code>",bM(f"shmgr_view|{pid}"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("SHMGR_IMP|") and m.text and not m.text.startswith("/"))
    def smii(m):
        st=US.get(m.from_user.id,"")
        try:pid=int(st.split("|",1)[1])
        except:US.pop(m.from_user.id,None);return
        a,e=aImp(pid,m.text.split("\n"));US.pop(m.from_user.id,None)
        cn=aCnt(pid);tx=f"✅ Thêm <b>{a}</b> TK\n📦 Kho: <b>{cn}</b>"
        if e:tx+="\n⚠️ "+"\n".join(f"• {x}" for x in e[:5])
        bot.reply_to(m,tx,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Xem",callback_data=f"shmgr_view|{pid}")))
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_list|"))
    def sml(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1]);items=aLA(pid,20)
        if not items:sh(call,"📋 Kho trống.",bM(f"shmgr_view|{pid}"));return
        av=sum(1 for i in items if i["status"]=="available");sd=sum(1 for i in items if i["status"]=="sold")
        tx=f"<b>📋 KHO TK/MK</b>\n\n<blockquote>✅ Còn: <b>{av}</b> | 💰 Bán: <b>{sd}</b></blockquote>\n\n"
        for i in items[:10]:
            ic="✅" if i["status"]=="available" else "🔴"
            tx+=f"{ic} <code>{html.escape(i['username'][:30])}</code>\n"
        sh(call,tx,bM(f"shmgr_view|{pid}"))
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_wipe|"))
    def smw(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1]);n=aWipe(pid)
        sh(call,f"🗑️ Xóa {n} TK chưa bán.",bM(f"shmgr_view|{pid}"))
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_del|"))
    def smd(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1])
        kb=types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ XÓA",callback_data=f"shmgr_delok|{pid}"),types.InlineKeyboardButton("❌ Hủy",callback_data=f"shmgr_view|{pid}"))
        sh(call,"⚠️ Xóa SP này? Kho TK/Proxy đi kèm cũng bị xóa.",kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("shmgr_delok|"))
    def smdo(call):
        if call.from_user.id!=cAD():return
        pid=int(call.data.split("|",1)[1])
        with db() as c:
            c.execute("DELETE FROM products WHERE id=?",(pid,))
            c.execute("DELETE FROM account_stock WHERE product_id=?",(pid,))
            c.execute("DELETE FROM proxy_stock WHERE product_id=?",(pid,))
        _sms(call,f"🗑️ Xóa SP #{pid}")

    # DATA API
    def _dam(call,no=""):
        url=sG("data_api_url","") or "(chưa set)";key=sG("data_api_key","")
        kd=(key[:6]+"***") if len(key)>10 else ("(chưa set)" if not key else "***");me=sG("data_api_method","POST")
        tx=(f"<b>🌐 API DATA</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+f"<blockquote>🔗 <code>{html.escape(url[:60])}</code>\n🔑 <code>{html.escape(kd)}</code>\n📡 <b>{me}</b></blockquote>")
        m=types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🔗 URL",callback_data="adm_data_set|data_api_url"),types.InlineKeyboardButton("🔑 Key",callback_data="adm_data_set|data_api_key"))
        m.add(types.InlineKeyboardButton(f"📡 {me}",callback_data="adm_data_toggle_method"),types.InlineKeyboardButton("🧪 Test",callback_data="adm_data_test"))
        m.add(types.InlineKeyboardButton("🔙 Admin",callback_data="adm_panel"))
        sh(call,tx,m)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_data_api")
    def dao(call):
        if call.from_user.id!=cAD():return
        _dam(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("adm_data_set|"))
    def das(call):
        if call.from_user.id!=cAD():return
        k=call.data.split("|",1)[1];US[call.from_user.id]=f"DATA_SET|{k}"
        sh(call,f"Nhập <code>{k}</code>",bM("adm_data_api"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("DATA_SET|") and m.text and not m.text.startswith("/"))
    def dasi(m):
        st=US.get(m.from_user.id,"")
        try:k=st.split("|",1)[1]
        except:US.pop(m.from_user.id,None);return
        sS(k,m.text.strip());US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ {k}",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 API",callback_data="adm_data_api")))
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_data_toggle_method")
    def dat(call):
        if call.from_user.id!=cAD():return
        cur=sG("data_api_method","POST");sS("data_api_method","GET" if cur=="POST" else "POST");_dam(call,"✅ Đổi")
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_data_test")
    def dat_(call):
        if call.from_user.id!=cAD():return
        url=sG("data_api_url","");key=sG("data_api_key","");me=sG("data_api_method","POST")
        if not url or not key:_dam(call,"⚠️ Chưa set");return
        ok,da,er=cNCC(url,key,"TEST",1,"TESTBOT",me,15)
        _dam(call,f"✅ <code>{html.escape(str(da)[:200])}</code>" if ok else f"❌ <code>{html.escape(str(er)[:200])}</code>")

    # ═══════════ QUẢN LÝ USERS (chỉ bot mẹ) ═══════════
    def _ul(call,no=""):
        with db() as c:
            tot=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            rs=c.execute("SELECT user_id,username,full_name,balance,total_recharged FROM users ORDER BY total_recharged DESC LIMIT 20").fetchall()
        tx=f"<b>👥 QUẢN LÝ USERS</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+f"<blockquote>Tổng: <b>{tot}</b> users</blockquote>\n\n<b>🏆 Top 20 nạp:</b>\n"
        for i,r in enumerate(rs,1):
            nm=r[2] or r[1] or "?"
            tx+=f"{i}. <code>{r[0]}</code> {html.escape(nm[:20])} – <b>{fmt(r[4])}đ</b>\n"
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("🔍 Tìm user",callback_data="adm_u_find"),types.InlineKeyboardButton("💎 Top số dư",callback_data="adm_u_bal"))
        kb.add(types.InlineKeyboardButton("🔙 Admin",callback_data="adm_panel"))
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_users")
    def _uo(call):
        if call.from_user.id!=cAD() or isC():return
        _ul(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_u_bal")
    def _ub(call):
        if call.from_user.id!=cAD() or isC():return
        with db() as c:rs=c.execute("SELECT user_id,username,full_name,balance FROM users ORDER BY balance DESC LIMIT 20").fetchall()
        tx="<b>💎 TOP SỐ DƯ</b>\n\n"
        for i,r in enumerate(rs,1):
            nm=r[2] or r[1] or "?"
            tx+=f"{i}. <code>{r[0]}</code> {html.escape(nm[:20])} – <b>{fmt(r[3])}đ</b>\n"
        sh(call,tx,bM("adm_users"))
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_u_find")
    def _uf(call):
        if call.from_user.id!=cAD() or isC():return
        US[call.from_user.id]="ADM_FIND_USER"
        sh(call,"<b>🔍 TÌM USER</b>\n\nGửi: <code>uid</code> hoặc <code>@username</code>\n\n/cancel hủy",bM("adm_users"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and US.get(m.from_user.id)=="ADM_FIND_USER" and m.text and not m.text.startswith("/"))
    def _ufi(m):
        q=m.text.strip()
        with db() as c:
            if q.startswith("@"):r=c.execute("SELECT user_id,username,full_name,balance,total_recharged,month_recharged FROM users WHERE username=?",(q[1:],)).fetchone()
            else:
                try:uid=int(q)
                except:bot.reply_to(m,"❌ ID sai");return
                r=c.execute("SELECT user_id,username,full_name,balance,total_recharged,month_recharged FROM users WHERE user_id=?",(uid,)).fetchone()
        US.pop(m.from_user.id,None)
        if not r:
            bot.reply_to(m,"❌ Không thấy user",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Users",callback_data="adm_users")));return
        uid,un,fn,bal,tot,mon=r
        tx=(f"<b>👤 USER #{uid}</b>\n\n<blockquote>Tên: {html.escape(fn or '?')}\n@: <code>{html.escape(un or '?')}</code>\n"
            f"🏦 Số dư: <b>{fmt(bal)}đ</b>\n🏆 Tổng nạp: <b>{fmt(tot)}đ</b>\n📅 Tháng: <b>{fmt(mon)}đ</b></blockquote>")
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("💰 Cấp tiền",callback_data=f"adm_u_g|{uid}"),types.InlineKeyboardButton("🔙 Users",callback_data="adm_users"))
        bot.send_message(m.chat.id,tx,reply_markup=kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("adm_u_g|"))
    def _ug(call):
        if call.from_user.id!=cAD() or isC():return
        uid=int(call.data.split("|",1)[1])
        US[call.from_user.id]=f"ADM_U_GRANT|{uid}"
        sh(call,f"<b>💰 CẤP TIỀN CHO #{uid}</b>\n\nGửi số tiền (âm để trừ).\n/cancel hủy",bM("adm_users"))
    @bot.message_handler(func=lambda m:m.from_user and m.from_user.id==cAD() and (US.get(m.from_user.id) or "").startswith("ADM_U_GRANT|") and m.text and not m.text.startswith("/"))
    def _ugi(m):
        st=US.get(m.from_user.id,"")
        try:uid=int(st.split("|",1)[1])
        except:US.pop(m.from_user.id,None);return
        try:a=int(re.sub(r"[^\d-]","",m.text.strip()))
        except:bot.reply_to(m,"❌ Số sai");return
        aAM(uid,a);u=gU(uid,"","");US.pop(m.from_user.id,None)
        bot.reply_to(m,f"✅ {uid}\n💵 {fmt(a)}đ\n🏦 {fmt(u['balance'])}đ",
            reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Users",callback_data="adm_users")))
        try:bot.send_message(uid,f"💰 {'+' if a>=0 else ''}{fmt(a)}đ\n🏦 {fmt(u['balance'])}đ")
        except:pass

    # ═══════════ QUẢN LÝ ĐƠN HÀNG (chỉ bot mẹ) ═══════════
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_orders")
    def _oo(call):
        if call.from_user.id!=cAD() or isC():return
        with db() as c:
            tot=c.execute("SELECT COUNT(*),COALESCE(SUM(price),0) FROM orders").fetchone()
            rs=c.execute("SELECT id,user_id,product_name,price,status,created_at FROM orders ORDER BY id DESC LIMIT 20").fetchall()
        tx=f"<b>🧾 QUẢN LÝ ĐƠN HÀNG</b>\n\n<blockquote>Tổng: <b>{tot[0]}</b> đơn | Doanh thu: <b>{fmt(tot[1])}đ</b></blockquote>\n\n<b>20 đơn gần nhất:</b>\n"
        for r in rs[:10]:
            stt={"paid":"✅","delivered":"📦","refunded":"💸"}.get(r[4],"❓")
            tx+=f"{stt} #{r[0]} <code>{r[1]}</code> – {fmt(r[3])}đ\n"
        kb=types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("📋 Xem tất cả",callback_data="adm_o_all"),types.InlineKeyboardButton("🔙 Admin",callback_data="adm_panel"))
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "")=="adm_o_all")
    def _oa(call):
        if call.from_user.id!=cAD() or isC():return
        with db() as c:rs=c.execute("SELECT id,user_id,product_name,price,status,created_at FROM orders ORDER BY id DESC LIMIT 30").fetchall()
        if not rs:sh(call,"📭 Chưa có đơn",bM("adm_orders"));return
        kb=types.InlineKeyboardMarkup(row_width=1)
        for r in rs:
            stt={"paid":"✅","delivered":"📦","refunded":"💸"}.get(r[4],"❓")
            kb.add(types.InlineKeyboardButton(f"{stt} #{r[0]} – {fmt(r[3])}đ – {html.escape(r[2][:20])}",callback_data=f"adm_o_v|{r[0]}"))
        kb.add(types.InlineKeyboardButton("🔙 Đơn hàng",callback_data="adm_orders"))
        sh(call,f"<b>📋 TẤT CẢ ĐƠN ({len(rs)})</b>",kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("adm_o_v|"))
    def _ov(call):
        if call.from_user.id!=cAD() or isC():return
        oid=int(call.data.split("|",1)[1])
        with db() as c:r=c.execute("SELECT id,user_id,product_name,product_id,price,status,created_at FROM orders WHERE id=?",(oid,)).fetchone()
        if not r:sh(call,"❌ Không thấy",bM("adm_orders"));return
        stt={"paid":"✅ Chờ xử lý","delivered":"📦 Đã giao","refunded":"💸 Đã hoàn"}.get(r[5],r[5])
        tx=(f"<b>🧾 ĐƠN #{r[0]}</b>\n\n<blockquote>👤 <code>{r[1]}</code>\n📦 {html.escape(r[2])}\n"
            f"💵 <b>{fmt(r[4])}đ</b>\n📌 {stt}\n🕐 {r[6]}</blockquote>")
        kb=types.InlineKeyboardMarkup(row_width=2)
        if r[5]!="delivered":kb.add(types.InlineKeyboardButton("✅ Đánh dấu giao",callback_data=f"adm_o_done|{oid}"))
        if r[5]!="refunded":kb.add(types.InlineKeyboardButton("💸 Hoàn tiền",callback_data=f"adm_o_rf|{oid}"))
        kb.add(types.InlineKeyboardButton("🔙 DS",callback_data="adm_o_all"))
        sh(call,tx,kb)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("adm_o_done|"))
    def _od(call):
        if call.from_user.id!=cAD() or isC():return
        oid=int(call.data.split("|",1)[1])
        with db() as c:c.execute("UPDATE orders SET status='delivered' WHERE id=?",(oid,))
        call.data=f"adm_o_v|{oid}";_ov(call)
    @bot.callback_query_handler(func=lambda c:(c.data or "").startswith("adm_o_rf|"))
    def _orf(call):
        if call.from_user.id!=cAD() or isC():return
        oid=int(call.data.split("|",1)[1])
        with db() as c:
            r=c.execute("SELECT user_id,price,status FROM orders WHERE id=?",(oid,)).fetchone()
            if r and r[2]!="refunded":
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(r[1],r[0]))
                c.execute("UPDATE orders SET status='refunded' WHERE id=?",(oid,))
        try:bot.send_message(r[0],f"💸 Đã hoàn {fmt(r[1])}đ cho đơn #{oid}")
        except:pass
        call.data=f"adm_o_v|{oid}";_ov(call)

    smm.register(bot,{"db_path_fn":cDB,"fmt":fmt,"cur_admin":cAD,"get_user":gU,"show":sh,"back_markup":bM,"user_states":US})

def dsp(bot,call,da,uid,u,ia):
    if da=="adm_panel":
        if not ia or isC():return
        sh(call,aT(),aM())
    elif da=="adm_bots":
        if not ia or isC():return
        abl(call)
    elif da.startswith("adm_bot_view|"):abv(call,int(da.split("|")[1]))
    elif da.startswith("adm_bot_add30|"):aba(call,int(da.split("|")[1]))
    elif da.startswith("adm_bot_stop|"):abs_(call,int(da.split("|")[1]))
    elif da.startswith("adm_bot_start|"):abst(call,int(da.split("|")[1]))
    elif da.startswith("adm_bot_del|"):abd(call,int(da.split("|")[1]))
    elif da=="adm_bots_clean":abc(call)
    elif da=="adm_bots_purge":
        if not ia:return
        with sqlite3.connect(MDB) as c:
            rs=c.execute("SELECT bot_token FROM user_bots").fetchall()
            for r in rs:stCB(r[0])
            n=c.execute("DELETE FROM user_bots").rowcount;c.commit()
        sh(call,f"🗑️ Xóa {n} bot.",bM("adm_bots"))
    elif da=="adm_grant":
        if not ia:return
        US[uid]="ADMIN_GRANT";sh(call,"<b>💰 CẤP TIỀN</b>\n\nGửi: <code>uid tiền</code>",bM("adm_panel"))
    elif da=="adm_stats":_as(call)
    elif da=="adm_broadcast":
        if not ia:return
        US[uid]="ADMIN_BROADCAST";sh(call,"📣 Gửi tin broadcast.",bM("adm_panel"))
    elif da=="adm_backup":
        if not ia:return
        sh(call,"💾...",bM("adm_panel"));bot.send_message(call.message.chat.id,"✅ OK!" if bUp() else "❌ Lỗi")
    elif da=="adm_restore":
        if not ia:return
        sh(call,"🔄...",bM("adm_panel"))
        if bRes():iDB(MDB,main=True);bot.send_message(call.message.chat.id,"✅ OK!")
        else:bot.send_message(call.message.chat.id,"❌ Không có backup")
    elif da=="adm_ui":_au(call)
    elif da.startswith("adm_ui_edit|"):
        k=da.split("|",1)[1];US[uid]=f"ADMIN_EDIT_SETTING|{k}"
        sh(call,f"<b>SỬA {k}</b>\n\nHiện: <blockquote>{html.escape(sG(k)[:200])}</blockquote>",bM("adm_ui"))
    elif da=="adm_ui_reset":
        for k,v in DS.items():sS(k,v)
        sh(call,"✅ Reset.",bM("adm_ui"))
    elif da=="cadm_panel":
        if not ia or not isC():return
        sh(call,aT(),aM())
    elif da=="cadm_shop":pass
    elif da=="cadm_products":_cpl(call,0)
    elif da.startswith("cadm_prod_page|"):_cpl(call,int(da.split("|")[1]))
    elif da.startswith("cadm_prod_view|"):_cpv(call,int(da.split("|")[1]))
    elif da=="cadm_prod_add":
        US[uid]="ADMIN_ADD_PRODUCT";sh(call,"➕ <b>THÊM SP</b>\n\n<code>Tên | giá | dm | mô_tả</code>",bM("cadm_products"))
    elif da.startswith("cadm_prod_edit|"):
        _,pid,f=da.split("|");US[uid]=f"ADMIN_EDIT_PRODUCT|{pid}|{f}";sh(call,f"<b>SỬA {f}</b>",bM(f"cadm_prod_view|{pid}"))
    elif da.startswith("cadm_prod_toggle|"):
        pid=int(da.split("|")[1])
        with db() as c:
            r=c.execute("SELECT active FROM products WHERE id=?",(pid,)).fetchone()
            if r:c.execute("UPDATE products SET active=? WHERE id=?",(0 if r[0] else 1,pid))
        _cpv(call,pid,"✅ Đổi")
    elif da.startswith("cadm_prod_del|"):
        pid=int(da.split("|")[1])
        sh(call,"⚠️ Xóa SP?",types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ XÓA",callback_data=f"cadm_prod_delok|{pid}"),types.InlineKeyboardButton("❌",callback_data=f"cadm_prod_view|{pid}")))
    elif da.startswith("cadm_prod_delok|"):
        with db() as c:c.execute("DELETE FROM products WHERE id=?",(int(da.split("|")[1]),))
        _cpl(call,0)
    elif da=="cadm_ipa":_cil(call)
    elif da=="cadm_ipa_add":
        US[uid]="ADMIN_IPA_WAIT_FILE";sh(call,"📱 Gửi .ipa",bM("cadm_ipa"))
    elif da.startswith("cadm_ipa_view|"):_civ(call,int(da.split("|")[1]))
    elif da.startswith("cadm_ipa_del|"):
        iD(int(da.split("|")[1]));_cil(call,"✅ Xóa")
    elif da=="cadm_proxy":
        s=pCnt();kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("➕ Nhập",callback_data="cadm_proxy_import"),types.InlineKeyboardButton("🧹 Dọn",callback_data="cadm_proxy_clean"))
        kb.add(types.InlineKeyboardButton("🔙 Admin",callback_data="cadm_panel"))
        sh(call,f"<b>🌐 PROXY</b>\n\n<blockquote>✅ {s['available']} | 💰 {s['sold']} | 📊 {s['total']}</blockquote>",kb)
    elif da=="cadm_proxy_import":
        US[uid]="ADMIN_IMPORT_PROXY";sh(call,"📥 Mỗi dòng: <code>ip:port:user:pass | KV | ISP | HTTP</code>",bM("cadm_proxy"))
    elif da=="cadm_proxy_clean":
        ns=dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with db() as c:n=c.execute("DELETE FROM proxy_stock WHERE status='sold' AND expires_at!='' AND expires_at<?",(ns,)).rowcount
        sh(call,f"✅ Xóa {n} proxy",bM("cadm_proxy"))
    elif da=="cadm_grant":
        US[uid]="ADMIN_GRANT";sh(call,"<b>💰 CẤP TIỀN</b>\n\nGửi: <code>uid tiền</code>",bM("cadm_panel"))
    elif da=="cadm_stats":_as(call)
    elif da=="cadm_settings":_cse(call)
    elif da.startswith("cadm_set_edit|"):
        k=da.split("|",1)[1];US[uid]=f"ADMIN_EDIT_SETTING|{k}"
        sh(call,f"<b>SỬA {k}</b>",bM("cadm_settings"))
    elif da=="cadm_broadcast":
        US[uid]="ADMIN_BROADCAST";sh(call,"📣",bM("cadm_panel"))
    elif da=="cadm_export":_cex(call)
    elif da=="menu_profile":
        sh(call,f"<b>📊 TÀI KHOẢN</b>\n\n<blockquote>🆔 <code>{uid}</code>\n👤 {html.escape(call.from_user.first_name or 'Khách')}\n🏦 <b>{fmt(u['balance'])}đ</b>\n🏆 {fmt(u['total'])}đ\n📅 {fmt(u['month'])}đ</blockquote>",bM())
    elif da=="menu_create_bot":
        if isC():return
        if not ia and u["balance"]<CBF:
            sh(call,f"<b>⚠️ THIẾU TIỀN</b>\n\nCần {fmt(CBF)}đ\nCó {fmt(u['balance'])}đ",types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("💳 Nạp",callback_data="menu_deposit"),types.InlineKeyboardButton("🔙",callback_data="menu_back")));return
        US[uid]="WAITING_BOT_TOKEN"
        sh(call,f"<b>🤖 THUÊ BOT</b>\n\n💰 {fmt(CBF)}đ/{BRD}d\n🔄 Gia hạn {fmt(BRF)}đ/{BRD}d\n\n1️⃣ @BotFather /newbot\n2️⃣ Copy token gửi:",bM())
    elif da=="mybots":
        if isC():return
        _mbl(call,u)
    elif da.startswith("mybot_view|"):_mbv(call,int(da.split("|")[1]),u)
    elif da.startswith("mybot_renew|"):_mbr(call,int(da.split("|")[1]),u)
    elif da=="menu_deposit":
        kb=types.InlineKeyboardMarkup(row_width=3)
        kb.add(*[types.InlineKeyboardButton(f"{a//1000}k",callback_data=f"dep|{a}") for a in (20000,30000,50000,100000,200000,500000)])
        kb.add(types.InlineKeyboardButton("✏️ Khác",callback_data="dep|0"),types.InlineKeyboardButton("🔙",callback_data="menu_back"))
        sh(call,"<b>💰 NẠP</b>",kb)
    elif da.startswith("dep|"):
        sQR(call,int(da.split("|")[1]),f"NAP{uid}","💰 NẠP","⚡ Chuyển đúng ND")
    elif da=="menu_donate":
        if isC():return
        sQR(call,0,f"DONATE{uid}","❤️ DONATE","🙏 Cảm ơn!")
    elif da=="menu_support":
        sh(call,f"<b>🎛️ HỖ TRỢ</b>\n\n{html.escape(sG('support_text'))}",bM())
    elif da=="menu_back":
        US.pop(uid,None);sh(call,hT(u,ia),mM(uid,bot=bot))
    elif da=="shop_home":sh(call,sHT(),sHM())
    elif da.startswith("shop_view|"):
        pid=int(da.split("|",1)[1]);p=sGt(pid)
        if not p:sh(call,"❌",bM("shop_home"));return
        sh(call,pDT(p),pMK(pid,p["stock"]))
    elif da.startswith("shop_buy|"):hSB(bot,call,da,uid,u)
    elif da=="shop_myorders":
        rs=sMyO(uid,10)
        if not rs:sh(call,"🛍 Chưa có đơn",bM("shop_home"));return
        tx="<b>🛍 ĐƠN HÀNG</b>\n\n<blockquote>"
        for r in rs:tx+=f"• #{r[0]} {html.escape(r[1])} – {fmt(r[2])}đ\n"
        sh(call,tx+"</blockquote>",bM("shop_home"))
    elif da=="ipa_home":
        it=iL(40)
        if not it:sh(call,"<b>📱 IPA</b>\n\nTrống!",bM("menu_back"));return
        kb=types.InlineKeyboardMarkup(row_width=1)
        for i in it:kb.add(types.InlineKeyboardButton(f"📱 {i['name'][:45]} ({i['downloads']}⬇️)",callback_data=f"ipa_dl|{i['id']}"))
        kb.add(types.InlineKeyboardButton("🔙",callback_data="menu_back"))
        sh(call,f"<b>📱 KHO IPA</b>\n\n{len(it)} app",kb)
    elif da.startswith("ipa_dl|"):
        pid=int(da.split("|",1)[1]);it=iG(pid)
        if not it:sh(call,"❌",bM("ipa_home"));return
        try:bot.send_chat_action(call.message.chat.id,"upload_document")
        except:pass
        try:
            bot.send_document(call.message.chat.id,it["file_id"],caption=f"<b>📱 {html.escape(it['name'])}</b>\n\n{html.escape(it['description'][:200])}")
            iInc(pid)
        except:bot.send_message(call.message.chat.id,"❌ Không gửi được")
    elif da=="proxy_my":
        rs=pMy(uid)
        if not rs:
            sh(call,"<b>🌐 PROXY</b>\n\nChưa mua",types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🛒 Shop",callback_data="shop_home"),types.InlineKeyboardButton("🔙",callback_data="menu_back")));return
        ac=sum(1 for r in rs if r["status"]=="active")
        kb=types.InlineKeyboardMarkup(row_width=1)
        for r in rs[:10]:
            ic="🟢" if r["status"]=="active" else "🔴"
            kb.add(types.InlineKeyboardButton(f"{ic} {r['ip']}:{r['port']} ({r['protocol']})",callback_data=f"proxy_view|{r['id']}"))
        kb.add(types.InlineKeyboardButton("🔙",callback_data="menu_back"))
        sh(call,f"<b>🌐 PROXY</b>\n\n🟢 {ac} / 🔴 {len(rs)-ac}",kb)
    elif da.startswith("proxy_view|"):
        pid=int(da.split("|",1)[1])
        with db() as c:r=c.execute("SELECT ip,port,username,password,protocol,region,isp,expires_at FROM proxy_stock WHERE id=? AND sold_to=?",(pid,uid)).fetchone()
        if not r:sh(call,"❌",bM("proxy_my"));return
        ns=dt.now().strftime("%Y-%m-%d %H:%M:%S");ac=r[7] and r[7]>ns
        ln=(f"{r[4].lower()}://{r[2]}:{r[3]}@{r[0]}:{r[1]}" if r[2] else f"{r[4].lower()}://{r[0]}:{r[1]}")
        tx=f"<b>🌐 PROXY</b>\n\n<blockquote>{'🟢' if ac else '🔴'} Hạn: {r[7]}\n🌐 <code>{r[0]}:{r[1]}</code>\n"
        if r[2]:tx+=f"👤 <code>{r[2]}</code>\n"
        if r[3]:tx+=f"🔑 <code>{r[3]}</code>\n"
        tx+=f"📡 {r[4]}</blockquote>\n\n<code>{html.escape(ln)}</code>"
        sh(call,tx,bM("proxy_my"))

def abl(call):
    with sqlite3.connect(MDB) as c:rs=c.execute("SELECT id,user_id,bot_username,status,bot_token FROM user_bots ORDER BY id DESC LIMIT 50").fetchall()
    ac=0;kb=types.InlineKeyboardMarkup(row_width=1)
    for r in rs:
        rn=r[4] in ACB;al=r[3]=="active" and rn
        if al:ac+=1
        ic="🟢" if al else "🔴"
        kb.add(types.InlineKeyboardButton(f"{ic} @{r[2]} → {r[1]}",callback_data=f"adm_bot_view|{r[0]}"))
    kb.add(types.InlineKeyboardButton("🧹 Dọn hết hạn",callback_data="adm_bots_clean"),types.InlineKeyboardButton("🗑️ Xóa hết",callback_data="adm_bots_purge"),types.InlineKeyboardButton("🔙",callback_data="adm_panel"))
    sh(call,f"<b>🤖 BOT CON</b>\n\n<blockquote>📊 {len(rs)} | 🟢 {ac} | 🔴 {len(rs)-ac}</blockquote>",kb)
def abv(call,bid):
    with sqlite3.connect(MDB) as c:r=c.execute("SELECT user_id,bot_token,bot_username,status,expires_at,created_at FROM user_bots WHERE id=?",(bid,)).fetchone()
    if not r:sh(call,"❌",bM("adm_bots"));return
    uid,tk,un,st,ex,ct=r
    pl=tk in ACB;dl=None
    if ex:
        try:dl=(dt.strptime(ex,"%Y-%m-%d %H:%M:%S")-dt.now()).days
        except:pass
    tx=f"<b>🤖 BOT #{bid}</b>\n\n<blockquote>👤 <code>{uid}</code>\n📛 @{un}\n📊 {st}\n🔌 {'🟢' if pl else '🔴'}\n📅 {ex or '—'} ({dl if dl is not None else '—'} ngày)</blockquote>"
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("➕30d",callback_data=f"adm_bot_add30|{bid}"),types.InlineKeyboardButton("⏸ Dừng",callback_data=f"adm_bot_stop|{bid}"))
    kb.add(types.InlineKeyboardButton("▶️ Bật",callback_data=f"adm_bot_start|{bid}"),types.InlineKeyboardButton("🗑️ XOÁ",callback_data=f"adm_bot_del|{bid}"))
    kb.add(types.InlineKeyboardButton("🔙",callback_data="adm_bots"))
    sh(call,tx,kb)
def aba(call,bid):
    with sqlite3.connect(MDB) as c:r=c.execute("SELECT bot_token,user_id FROM user_bots WHERE id=?",(bid,)).fetchone()
    if r:
        nw=rB(r[1],r[0],30)
        if r[0] not in ACB:sCB(r[0],r[1],force=True)
        sh(call,f"✅ {nw}",bM(f"adm_bot_view|{bid}"))
def abs_(call,bid):
    with sqlite3.connect(MDB) as c:
        r=c.execute("SELECT bot_token FROM user_bots WHERE id=?",(bid,)).fetchone()
        if r:c.execute("UPDATE user_bots SET status='inactive' WHERE id=?",(bid,));c.commit()
    if r:stCB(r[0])
    sh(call,"⏸",bM(f"adm_bot_view|{bid}"))
def abst(call,bid):
    with sqlite3.connect(MDB) as c:
        r=c.execute("SELECT bot_token,user_id FROM user_bots WHERE id=?",(bid,)).fetchone()
        if r:c.execute("UPDATE user_bots SET status='active' WHERE id=?",(bid,));c.commit()
    if r:sCB(r[0],r[1],force=True)
    sh(call,"▶️",bM(f"adm_bot_view|{bid}"))
def abd(call,bid):
    with sqlite3.connect(MDB) as c:
        r=c.execute("SELECT bot_token FROM user_bots WHERE id=?",(bid,)).fetchone()
        if r:c.execute("DELETE FROM user_bots WHERE id=?",(bid,));c.commit()
    if r:stCB(r[0])
    sh(call,"🗑️",bM("adm_bots"))
def abc(call):
    ns=dt.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(MDB) as c:
        rs=c.execute("SELECT bot_token FROM user_bots WHERE expires_at!='' AND expires_at<?",(ns,)).fetchall()
        for r in rs:stCB(r[0])
        n=c.execute("DELETE FROM user_bots WHERE expires_at!='' AND expires_at<?",(ns,)).rowcount;c.commit()
    sh(call,f"🧹 Xóa {n} bot.",bM("adm_bots"))
def _as(call):
    with db() as c:
        us=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        od=c.execute("SELECT COUNT(*),COALESCE(SUM(price),0) FROM orders").fetchone()
        tp=c.execute("SELECT user_id,balance FROM users ORDER BY balance DESC LIMIT 5").fetchall()
    tx=f"<b>📊 THỐNG KÊ</b>\n\n<blockquote>👥 {us}\n🛒 {od[0]} – {fmt(od[1])}đ</blockquote>\n\n<b>Top5:</b>\n"
    for u,b in tp:tx+=f"• <code>{u}</code> – {fmt(b)}đ\n"
    sh(call,tx,bM("cadm_panel" if isC() else "adm_panel"))
def _au(call):
    s=sA();it=[("home_title","🏠 Tiêu đề"),("home_subtitle","📝 Phụ đề"),("welcome_msg","👋 Chào"),("shop_title","🛒 Shop"),("support_text","🎛️ Hỗ trợ"),("footer_note","🔖 Ghi chú")]
    tx="<b>🎨 GIAO DIỆN</b>\n\n"
    for k,l in it:tx+=f"{l}\n<i>{html.escape((s.get(k) or '')[:60])}</i>\n\n"
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[types.InlineKeyboardButton(l,callback_data=f"adm_ui_edit|{k}") for k,l in it])
    kb.add(types.InlineKeyboardButton("🔄 Mặc định",callback_data="adm_ui_reset"),types.InlineKeyboardButton("🔙",callback_data="adm_panel"))
    sh(call,tx,kb)
def _cpl(call,pg=0):
    ps=sLA();pe=8;tp=max(1,(len(ps)+pe-1)//pe);pg=max(0,min(pg,tp-1))
    ck=ps[pg*pe:(pg+1)*pe];kb=types.InlineKeyboardMarkup(row_width=1)
    for p in ck:
        ic="✅" if p.get("active",1) else "⛔"
        kb.add(types.InlineKeyboardButton(f"{ic} #{p['id']} {p['name'][:35]} — {fmt(p['price'])}đ",callback_data=f"cadm_prod_view|{p['id']}"))
    nv=[]
    if pg>0:nv.append(types.InlineKeyboardButton("⬅️",callback_data=f"cadm_prod_page|{pg-1}"))
    nv.append(types.InlineKeyboardButton(f"{pg+1}/{tp}",callback_data="noop"))
    if pg<tp-1:nv.append(types.InlineKeyboardButton("➡️",callback_data=f"cadm_prod_page|{pg+1}"))
    if nv:kb.row(*nv)
    kb.add(types.InlineKeyboardButton("➕ Thêm",callback_data="cadm_prod_add"),types.InlineKeyboardButton("🔙",callback_data="cadm_panel"))
    sh(call,f"<b>🛍️ SẢN PHẨM</b>\n\n📦 {len(ps)} | Trang {pg+1}/{tp}",kb)
def _cpv(call,pid,no=""):
    p=sGt(pid)
    if not p:sh(call,"❌",bM("cadm_products"));return
    st="♾️" if p["stock"]<0 else ("Hết" if p["stock"]==0 else str(p["stock"]))
    ac="✅" if p["active"] else "⛔";ap=(p.get("api_product_code") or "").strip() or "—"
    tx=f"<b>📦 SP #{pid}</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+f"<blockquote><b>{html.escape(p['name'])}</b>\n💵 {fmt(p['price'])}đ\n📂 {html.escape(p['category'])}\n🔗 <code>{html.escape(ap)}</code>\n📊 Tồn: {st} | 🔥 {p['sold']}\n🔖 {ac}</blockquote>"
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✏️ Tên",callback_data=f"cadm_prod_edit|{pid}|name"),types.InlineKeyboardButton("💵 Giá",callback_data=f"cadm_prod_edit|{pid}|price"))
    kb.add(types.InlineKeyboardButton("📂 DM",callback_data=f"cadm_prod_edit|{pid}|category"),types.InlineKeyboardButton("📊 Tồn",callback_data=f"cadm_prod_edit|{pid}|stock"))
    kb.add(types.InlineKeyboardButton("📝 Mô tả",callback_data=f"cadm_prod_edit|{pid}|description"))
    kb.add(types.InlineKeyboardButton("🔗 NCC",callback_data=f"cadm_prod_edit|{pid}|api_product_code"))
    kb.add(types.InlineKeyboardButton("⛔" if p["active"] else "✅",callback_data=f"cadm_prod_toggle|{pid}"))
    kb.add(types.InlineKeyboardButton("🗑️ XÓA",callback_data=f"cadm_prod_del|{pid}"),types.InlineKeyboardButton("🔙",callback_data="cadm_products"))
    sh(call,tx,kb)
def _cil(call,no=""):
    it=iL(40);kb=types.InlineKeyboardMarkup(row_width=1)
    for i in it[:30]:kb.add(types.InlineKeyboardButton(f"📱 #{i['id']} {i['name'][:40]} ({i['downloads']}⬇️)",callback_data=f"cadm_ipa_view|{i['id']}"))
    kb.add(types.InlineKeyboardButton("➕ Thêm",callback_data="cadm_ipa_add"),types.InlineKeyboardButton("🔙",callback_data="cadm_panel"))
    sh(call,f"<b>📱 IPA</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+f"Tổng: {len(it)}",kb)
def _civ(call,pid,no=""):
    it=iG(pid)
    if not it:sh(call,"❌",bM("cadm_ipa"));return
    sz=f"{it['file_size']/1024/1024:.1f}MB" if it["file_size"] else "—"
    tx=f"<b>📱 IPA #{pid}</b>\n\n"+(f"<blockquote>{no}</blockquote>\n\n" if no else "")+f"<blockquote><b>{html.escape(it['name'])}</b>\n📄 {html.escape(it['description'][:200])}\n📦 {sz}\n⬇️ {it['downloads']}</blockquote>"
    sh(call,tx,types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🗑️ XÓA",callback_data=f"cadm_ipa_del|{pid}"),types.InlineKeyboardButton("🔙",callback_data="cadm_ipa")))
def _cse(call):
    ks=[("bank_name","🏦 NH"),("account_no","💳 STK"),("account_name","👤 Chủ TK"),("home_title","🏠 Tiêu đề"),("home_subtitle","📝 Phụ đề"),("welcome_msg","👋 Chào"),("shop_title","🛒 Shop"),("support_text","🎛️ Hỗ trợ"),("footer_note","🔖")]
    tx="<b>⚙️ CÀI ĐẶT</b>\n\n"
    for k,l in ks:tx+=f"{l}\n<i>{html.escape((sG(k) or '—')[:60])}</i>\n\n"
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[types.InlineKeyboardButton(l,callback_data=f"cadm_set_edit|{k}") for k,l in ks])
    kb.add(types.InlineKeyboardButton("🔙",callback_data="cadm_panel"))
    sh(call,tx,kb)
def _cex(call):
    b=cB();dp=cDB()
    if not os.path.exists(dp):sh(call,"❌ DB không tồn tại",bM("cadm_panel"));return
    sh(call,"📤 Đang xuất DB...",bM("cadm_panel"))
    ts=dt.now().strftime("%Y%m%d_%H%M%S")
    try:
        with open(dp,"rb") as f:b.send_document(call.from_user.id,f,caption=f"💾 DB {ts}")
        b.send_message(call.message.chat.id,"✅ Đã gửi DB!")
    except:b.send_message(call.message.chat.id,"❌ Không gửi được")
def _mbl(call,u):
    bs=lUB(call.from_user.id)
    if not bs:
        sh(call,f"<b>🤖 BOT</b>\n\nChưa có bot. Thuê {fmt(CBF)}đ!",types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🤖 Thuê",callback_data="menu_create_bot"),types.InlineKeyboardButton("🔙",callback_data="menu_back")));return
    kb=types.InlineKeyboardMarkup(row_width=1);ac=0
    for b in bs[:10]:
        al=b["status"]=="active" and (b["days_left"] is None or b["days_left"]>0)
        if al:ac+=1
        ic="🟢" if al else "🔴";dl=b["days_left"]
        tg=f"{dl} ngày" if dl is not None and dl>0 else ("HẾT" if dl is not None else "—")
        kb.add(types.InlineKeyboardButton(f"{ic} @{b['username']} ({tg})",callback_data=f"mybot_view|{b['id']}"))
    kb.add(types.InlineKeyboardButton("➕ Thuê thêm",callback_data="menu_create_bot"),types.InlineKeyboardButton("🔙",callback_data="menu_back"))
    sh(call,f"<b>🤖 BOT CỦA TÔI</b>\n\n🟢 {ac}/{len(bs)}",kb)
def _mbv(call,bid,u):
    with sqlite3.connect(MDB) as c:r=c.execute("SELECT bot_token,bot_username,status,expires_at,plan,created_at FROM user_bots WHERE id=? AND user_id=?",(bid,call.from_user.id)).fetchone()
    if not r:sh(call,"❌",bM("mybots"));return
    tk,un,st,ex,pl,ct=r;al=st=="active" and bIA(tk);dl=None
    if ex:
        try:dl=(dt.strptime(ex,"%Y-%m-%d %H:%M:%S")-dt.now()).days
        except:pass
    tx=f"<b>🤖 BOT #{bid}</b>\n\n<blockquote>👤 @{un}\n📊 {'🟢' if al else '🔴'}\n📅 {ex or '—'}\n⏳ {dl if dl is not None else '—'} ngày\n💎 {pl}</blockquote>"
    kb=types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(f"🔄 Gia hạn {BRD}d ({fmt(BRF)}đ)",callback_data=f"mybot_renew|{bid}"))
    if al:kb.add(types.InlineKeyboardButton("💬 Mở bot",url=f"https://t.me/{un}"))
    kb.add(types.InlineKeyboardButton("🔙",callback_data="mybots"))
    sh(call,tx,kb)
def _mbr(call,bid,u):
    with sqlite3.connect(MDB) as c:r=c.execute("SELECT bot_token,bot_username FROM user_bots WHERE id=? AND user_id=?",(bid,call.from_user.id)).fetchone()
    if not r:sh(call,"❌",bM("mybots"));return
    tk,un=r
    if u["balance"]<BRF:
        sh(call,f"⚠️ Cần {fmt(BRF)}đ",types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("💳 Nạp",callback_data="menu_deposit"),types.InlineKeyboardButton("🔙",callback_data=f"mybot_view|{bid}")));return
    with db() as c:
        if c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(BRF,call.from_user.id,BRF)).rowcount==0:sh(call,"❌ Số dư đủ",bM("mybots"));return
    nw=rB(call.from_user.id,tk)
    if tk not in ACB:sCB(tk,call.from_user.id,force=True)
    sh(call,f"✅ <b>GIA HẠN</b>\n\n🤖 @{un}\n📅 {nw}\n💸 -{fmt(BRF)}đ",types.InlineKeyboardMarkup(row_width=1).add(types.InlineKeyboardButton("🔙",callback_data=f"mybot_view|{bid}")))

@MB.message_handler(commands=["admin","addmoney","backup","restore","broadcast","stats","clean_bots","purge_bots","list_bots"])
def adm(m):
    if m.from_user.id!=AID:return
    cm=m.text.split()[0].split("@")[0].lower();ps=m.text.split(maxsplit=2)
    _ctx.db_path=MDB;_ctx.admin_id=AID;_ctx.is_child=False;_ctx.bot_instance=MB
    if cm=="/admin":MB.send_message(m.chat.id,aT(),reply_markup=aM())
    elif cm=="/addmoney":
        try:uid,a=int(ps[1]),int(ps[2])
        except:MB.reply_to(m,"/addmoney uid tiền");return
        aAM(uid,a);u=gU(uid,"","");MB.reply_to(m,f"✅ {fmt(u['balance'])}đ")
    elif cm=="/backup":
        MB.reply_to(m,"💾...");MB.reply_to(m,"✅" if bUp() else "❌")
    elif cm=="/restore":
        MB.reply_to(m,"🔄...")
        if bRes():iDB(MDB,main=True);MB.reply_to(m,"✅")
        else:MB.reply_to(m,"❌")
    elif cm=="/broadcast":
        if len(ps)<2:MB.reply_to(m,"/broadcast ND");return
        tx=m.text.split(maxsplit=1)[1]
        def w():
            with sqlite3.connect(MDB) as c:ids=[r[0] for r in c.execute("SELECT user_id FROM users").fetchall()]
            ok=0
            for u in ids:
                try:MB.send_message(u,tx);ok+=1
                except:pass
                time.sleep(0.05)
            MB.send_message(m.chat.id,f"📣 {ok}/{len(ids)}")
        threading.Thread(target=w,daemon=True).start();MB.reply_to(m,"📣 Đang gửi...")
    elif cm=="/stats":
        with sqlite3.connect(MDB) as c:
            u=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            b=c.execute("SELECT COUNT(*) FROM user_bots WHERE status='active'").fetchone()[0]
        MB.reply_to(m,f"📊 Users: {u} | Bots: {b}")
    elif cm=="/clean_bots":
        with sqlite3.connect(MDB) as c:
            rs=c.execute("SELECT bot_token FROM user_bots WHERE status='inactive'").fetchall()
            for r in rs:stCB(r[0])
            n=c.execute("DELETE FROM user_bots WHERE status='inactive'").rowcount;c.commit()
        MB.reply_to(m,f"✅ Xóa {n} bot inactive")
    elif cm=="/purge_bots":
        with sqlite3.connect(MDB) as c:
            rs=c.execute("SELECT bot_token FROM user_bots").fetchall()
            for r in rs:stCB(r[0])
            n=c.execute("DELETE FROM user_bots").rowcount;c.commit()
        MB.reply_to(m,f"🗑️ Xóa hết {n} bot")
    elif cm=="/list_bots":
        with sqlite3.connect(MDB) as c:rs=c.execute("SELECT id,bot_username,status,user_id FROM user_bots ORDER BY id DESC LIMIT 20").fetchall()
        if not rs:MB.reply_to(m,"Không có bot");return
        tx="<b>🤖 BOT CON:</b>\n\n"
        for r in rs:tx+=f"#{r[0]} @{r[1]} [{r[2]}] uid {r[3]}\n"
        MB.reply_to(m,tx)

def wN(s,d=""):
    WL.appendleft(f"{dt.now():%H:%M:%S} [{s}] {d}"[:220]);log.info("SePay: %s",s)
@app.route("/sepaywebhook",methods=["POST"])
def sw():
    _ctx.db_path=MDB;_ctx.admin_id=AID;_ctx.is_child=False;_ctx.bot_instance=MB
    if not SK:wN("503");return jsonify({"success":False}),503
    au=request.headers.get("Authorization","")
    if not hmac.compare_digest(au.encode(),f"Apikey {SK}".encode()):wN("401");return jsonify({"success":False}),401
    da=request.get_json(silent=True) or {}
    if str(da.get("transferType","in")).lower()!="in":wN("SKIP");return jsonify({"success":True}),200
    try:a=int(float(da.get("transferAmount") or 0))
    except:a=0
    tx=str(da.get("id") or da.get("referenceCode") or "")
    raw=" ".join(str(da.get(k) or "") for k in ("content","code","description"))
    t=re.sub(r"[^A-Z0-9]","",raw.upper())
    if a<=0 or not tx:wN("SKIP");return jsonify({"success":True}),200
    mn=re.search(r"NAP(\d{5,13})",t);md=re.search(r"DONATE(\d{5,13})",t)
    if mn:
        uid=int(mn.group(1))
        if procD(f"sepay:{tx}",uid,a):
            wN("OK",f"+{a}→{uid}")
            try:
                u=gU(uid,"","")
                MB.send_message(uid,f"✅ NẠP OK\n💵 +{fmt(a)}đ\n🏦 {fmt(u['balance'])}đ")
            except:pass
            try:MB.send_message(AID,f"💰 +{fmt(a)}đ từ <code>{uid}</code>")
            except:pass
        else:wN("DUP")
        return jsonify({"success":True}),200
    if md:
        uid=int(md.group(1))
        if procDo(f"sepay:{tx}",uid,a):
            wN("OK","donate")
            try:MB.send_message(uid,f"❤️ Cảm ơn {fmt(a)}đ!")
            except:pass
        return jsonify({"success":True}),200
    wN("NOCODE",f"{a}đ")
    try:MB.send_message(AID,f"⚠️ Tiền vào {fmt(a)}đ không khớp:\n<code>{html.escape(raw[:150])}</code>")
    except:pass
    return jsonify({"success":True}),200

@app.route("/")
def hm():return "Bot Active",200
@app.route("/health")
def he():return "ok",200

def ka():
    url=E("RENDER_EXTERNAL_URL") or ("https://"+E("RENDER_EXTERNAL_HOSTNAME") if E("RENDER_EXTERNAL_HOSTNAME") else "")
    if not url:log.warning("⚠️ No RENDER_EXTERNAL_URL");return
    p=url.rstrip("/")+"/health";log.info("🔄 KA → %s",p);time.sleep(30)
    while True:
        try:
            r=requests.get(p,timeout=15,headers={"User-Agent":"KA/1.0"})
            if r.status_code!=200:log.warning("KA %s",r.status_code)
        except:pass
        time.sleep(300)
def rMP():
    while True:
        try:
            MB.remove_webhook()
            MB.infinity_polling(skip_pending=True,timeout=20,long_polling_timeout=20,logger_level=logging.WARNING)
        except Exception as e:log.warning("Polling: %s",e);time.sleep(5)

def main():
    _ctx.db_path=MDB;_ctx.admin_id=AID;_ctx.is_child=False;_ctx.bot_instance=MB;_ctx.bot_username=BUN
    if BCI and not os.path.exists(MDB):log.info("🔄 DB restore...");bRes()
    iDB(MDB,main=True)
    regH(MB)
    if not SK:log.warning("⚠️ Chưa SEPAY_API_KEY")
    if not GQ:log.warning("⚠️ Chưa GROQ_API_KEY")
    if not BCI:log.warning("⚠️ Chưa BACKUP_CHAT_ID")
    try:
        MB.set_my_commands([types.BotCommand("start","Menu"),types.BotCommand("menu","Menu"),types.BotCommand("admin","Admin")])
    except:pass
    threading.Thread(target=lCB,daemon=True).start()
    threading.Thread(target=rMP,daemon=True).start()
    threading.Thread(target=ka,daemon=True).start()
    threading.Thread(target=bLoop,daemon=True).start()
    threading.Thread(target=bChkL,daemon=True).start()
    smm.start_polling_loop(MDB)
    log.info("✅ Bot OK | DB: %s | Port: %s",MDB,PT)
    try:
        from waitress import serve
        serve(app,host="0.0.0.0",port=PT,threads=8)
    except:app.run(host="0.0.0.0",port=PT)

if __name__=="__main__":
    main()