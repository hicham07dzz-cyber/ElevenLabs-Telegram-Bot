#!/usr/bin/env python3
"""Local AUTOFOX EDIT web app server for Android/Termux."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from email.parser import BytesParser
from email.policy import default
import json, subprocess, sys, uuid

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
UPLOADS.mkdir(exist_ok=True); OUTPUTS.mkdir(exist_ok=True)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if urlparse(self.path).path != "/api/edit":
            self.send_error(404); return
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_error(400, "ارسل ملف فيديو"); return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 800 * 1024 * 1024:
            self.send_error(413, "حجم الملف غير مقبول (الحد 800MB)"); return
        body = self.rfile.read(length)
        msg = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        video = None
        for part in msg.iter_parts():
            if part.get_param("name", header="content-disposition") == "video":
                video = part; break
        if video is None:
            self.send_error(400, "لم يتم العثور على الفيديو"); return
        rawname = Path(video.get_filename() or "video.mp4").name
        suffix = Path(rawname).suffix.lower()
        if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}:
            self.send_error(415, "صيغة الفيديو غير مدعومة"); return
        token = uuid.uuid4().hex[:10]
        source = UPLOADS / (token + suffix)
        output = OUTPUTS / (token + "_AUTOFOX.mp4")
        source.write_bytes(video.get_payload(decode=True) or b"")
        try:
            cmd = [sys.executable, str(ROOT / "autofox.py"), str(source), "--output", str(output)]
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "فشل التحليل")[-2500:])
            payload = {"ok": True, "message": "اكتمل المونتاج", "video": "/outputs/" + output.name,
                       "report": "/outputs/" + output.with_suffix(".analysis.json").name}
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        except Exception as exc:
            data = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode()
            self.send_response(500); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        finally:
            try: source.unlink()
            except OSError: pass

if __name__ == "__main__":
    print("AUTOFOX EDIT يعمل على http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
