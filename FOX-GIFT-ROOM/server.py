#!/usr/bin/env python3
"""FOX GIFT ROOM: independent room-credit server; standard library only."""
import os, json, re, sqlite3, secrets, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DB=Path.home()/".foxgift_room.sqlite3"
ADMIN_KEY=os.environ.get("FOXGIFT_ADMIN_KEY","")
HOST=os.environ.get("FOXGIFT_HOST","127.0.0.1")
PORT=int(os.environ.get("FOXGIFT_PORT","8765"))

def connect():
    c=sqlite3.connect(DB,timeout=10)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS codes(
          code TEXT PRIMARY KEY, multiplier INTEGER NOT NULL DEFAULT 1,
          credits INTEGER NOT NULL, max_uses INTEGER NOT NULL,
          expires_at INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wallets(uid TEXT PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS claims(
          id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL,uid TEXT NOT NULL,
          token_id TEXT NOT NULL,credits INTEGER NOT NULL,created_at INTEGER NOT NULL,
          UNIQUE(code,uid),FOREIGN KEY(code) REFERENCES codes(code)
        );
        """)
        cols={r["name"] for r in c.execute("PRAGMA table_info(codes)")}
        if "multiplier" not in cols:
            c.execute("ALTER TABLE codes ADD COLUMN multiplier INTEGER NOT NULL DEFAULT 1")
        claim_cols={r["name"] for r in c.execute("PRAGMA table_info(claims)")}
        if "token_id" not in claim_cols:
            c.execute("ALTER TABLE claims ADD COLUMN token_id TEXT")
            c.execute("UPDATE claims SET token_id='00000' WHERE token_id IS NULL")

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,fmt,*args):
        print("[FOX-GIFT]",fmt%args)
    def send_json(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(raw)));self.send_header("Cache-Control","no-store")
        self.end_headers();self.wfile.write(raw)
    def read_json(self):
        try:
            n=int(self.headers.get("Content-Length","0"))
            if n<1 or n>10000: raise ValueError()
            return json.loads(self.rfile.read(n))
        except Exception: raise ValueError("بيانات الطلب غير صالحة.")
    def admin_ok(self):
        return bool(ADMIN_KEY) and secrets.compare_digest(self.headers.get("X-Admin-Key",""),ADMIN_KEY)
    def do_GET(self):
        if self.path=="/api/admin/list":
            if not self.admin_ok(): return self.send_json(401,{"error":"مفتاح الإدارة غير صحيح."})
            with connect() as c:
                rows=c.execute("""SELECT codes.*,(SELECT COUNT(*) FROM claims WHERE claims.code=codes.code) AS used FROM codes ORDER BY created_at DESC""").fetchall()
                total=c.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            now=int(time.time())
            return self.send_json(200,{"claims":total,"codes":[
              {"code":r["code"],"multiplier":r["multiplier"],"credits":r["credits"],
               "max_uses":r["max_uses"],"expires_at":r["expires_at"],"active":bool(r["active"]),
               "expired":now>r["expires_at"],"used":r["used"]} for r in rows]})
        return super().do_GET()
    def do_POST(self):
        try:
            data=self.read_json()
            if self.path=="/api/claim":
                uid=str(data.get("uid","")).strip()
                code=str(data.get("code","")).strip().upper()
                if not re.fullmatch(r"\d{5,24}",uid) or not re.fullmatch(r"[A-Z0-9_-]{4,32}",code):
                    return self.send_json(400,{"error":"UID أو كود الهدية غير صالح."})
                now=int(time.time())
                with connect() as c:
                    c.execute("BEGIN IMMEDIATE")
                    gift=c.execute("SELECT * FROM codes WHERE code=?",(code,)).fetchone()
                    if not gift or not gift["active"]: return self.send_json(404,{"error":"الكود غير موجود أو متوقف."})
                    if now>gift["expires_at"]: return self.send_json(410,{"error":"انتهت صلاحية الكود."})
                    used=c.execute("SELECT COUNT(*) FROM claims WHERE code=?",(code,)).fetchone()[0]
                    if used>=gift["max_uses"]: return self.send_json(409,{"error":"اكتمل عدد استعمالات هذا الكود."})
                    if c.execute("SELECT 1 FROM claims WHERE code=? AND uid=?",(code,uid)).fetchone():
                        return self.send_json(409,{"error":"هذا UID استعمل الكود من قبل."})
                    first_five=int(uid[:5])
                    token_id=str(first_five*gift["multiplier"]+4921)[:5].zfill(5)
                    c.execute("INSERT INTO wallets(uid,balance) VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET balance=balance+excluded.balance",(uid,gift["credits"]))
                    c.execute("INSERT INTO claims(code,uid,token_id,credits,created_at) VALUES(?,?,?,?,?)",(code,uid,token_id,gift["credits"],now))
                    balance=c.execute("SELECT balance FROM wallets WHERE uid=?",(uid,)).fetchone()[0]
                return self.send_json(200,{"token_id":token_id,"credits":gift["credits"],"balance":balance})
            if not self.admin_ok(): return self.send_json(401,{"error":"مفتاح الإدارة غير صحيح."})
            if self.path=="/api/admin/create":
                code=str(data.get("code","")).strip().upper()
                multiplier=int(data.get("multiplier",0));credits=int(data.get("credits",0))
                uses=int(data.get("max_uses",0));days=int(data.get("days",0))
                if not re.fullmatch(r"[A-Z0-9_-]{4,32}",code) or not (1<=multiplier<=999999 and 1<=credits<=1000000 and 1<=uses<=100000 and 1<=days<=365):
                    return self.send_json(400,{"error":"تحقق من الكود والمعامل والقيم المدخلة."})
                with connect() as c:
                    c.execute("INSERT INTO codes(code,multiplier,credits,max_uses,expires_at,active,created_at) VALUES(?,?,?,?,?,1,?)",
                              (code,multiplier,credits,uses,int(time.time())+days*86400,int(time.time())))
                return self.send_json(201,{"ok":True})
            if self.path=="/api/admin/toggle":
                code=str(data.get("code","")).upper()
                with connect() as c:
                    row=c.execute("SELECT active FROM codes WHERE code=?",(code,)).fetchone()
                    if not row: return self.send_json(404,{"error":"الكود غير موجود."})
                    c.execute("UPDATE codes SET active=? WHERE code=?",(0 if row["active"] else 1,code))
                return self.send_json(200,{"ok":True})
            if self.path=="/api/admin/delete":
                code=str(data.get("code","")).upper()
                with connect() as c:
                    c.execute("DELETE FROM claims WHERE code=?",(code,))
                    cur=c.execute("DELETE FROM codes WHERE code=?",(code,))
                    if not cur.rowcount: return self.send_json(404,{"error":"الكود غير موجود."})
                return self.send_json(200,{"ok":True})
            return self.send_json(404,{"error":"المسار غير موجود."})
        except sqlite3.IntegrityError: return self.send_json(409,{"error":"الكود موجود مسبقاً أو العملية مكررة."})
        except (ValueError,TypeError,json.JSONDecodeError): return self.send_json(400,{"error":"تحقق من البيانات المدخلة."})
        except Exception: return self.send_json(500,{"error":"حدث خطأ داخلي."})

if __name__=="__main__":
    init_db()
    if not ADMIN_KEY: raise SystemExit("ضع FOXGIFT_ADMIN_KEY في متغير البيئة قبل التشغيل.")
    print(f"FOX GIFT ROOM running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
