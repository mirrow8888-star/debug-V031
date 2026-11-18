"""PWA + RWD 版：FastAPI 外殼提供 manifest / Service Worker / 圖示，Gradio 掛載在根路徑。
本機：uvicorn app:app --reload --port 7860
Render：uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
"""
import io
import threading
from functools import lru_cache
from pathlib import Path

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from PIL import Image, ImageDraw

from rag_engine import get_core
from ui import THEME_COLOR, build_demo

BASE = Path(__file__).parent
app = FastAPI(title="RAG 文件問答", docs_url=None, redoc_url=None)

MANIFEST = {
    "name": "RAG 文件問答",
    "short_name": "RAG 問答",
    "description": "上傳 PDF / DOCX，多策略檢索並以 Groq 模型回答",
    "id": "/",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "any",
    "lang": "zh-Hant",
    "background_color": "#ffffff",
    "theme_color": THEME_COLOR,
    "icons": [
        {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

OFFLINE_HTML = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="{THEME_COLOR}">
<title>目前離線</title>
<style>body{{font-family:system-ui,"Noto Sans TC",sans-serif;display:grid;place-items:center;min-height:100dvh;margin:0;padding:24px;text-align:center;color:#1f2937}}
h1{{font-size:22px;margin:0 0 8px}}p{{color:#6b7280;margin:0 0 20px}}
button{{font-size:16px;padding:10px 22px;border:0;border-radius:10px;background:{THEME_COLOR};color:#fff}}</style></head>
<body><main><h1>目前離線</h1><p>文件問答需要網路連線，連上網路後再試一次。</p>
<button onclick="location.reload()">重新連線</button></main></body></html>"""


@lru_cache(maxsize=8)
def make_icon(size: int, maskable: bool) -> bytes:
    """以 Pillow 即時繪製圖示（綠底 + 白色文件），不需另外放圖檔。"""
    green = THEME_COLOR
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable: d.rectangle([0, 0, size, size], fill=green)              # 全幅，由系統裁切
    else: d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=green)
    w, h = size * 0.36, size * 0.46                                         # 內容留在安全區內
    x0, y0 = (size - w) / 2, (size - h) / 2
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=size * 0.04, fill="white")
    for i in range(4):
        y = y0 + h * (0.2 + 0.18 * i)
        d.rounded_rectangle([x0 + w * 0.15, y, x0 + w * (0.85 if i < 3 else 0.55), y + h * 0.07], radius=size * 0.01, fill=green)
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


ICONS = {"icon-192.png": (192, False), "icon-512.png": (512, False),
         "maskable-512.png": (512, True), "apple-touch-icon.png": (180, True)}


@app.get("/healthz")
def healthz(): return PlainTextResponse("ok")


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(MANIFEST, media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/sw.js")
def service_worker():
    return Response((BASE / "static" / "sw.js").read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/offline")
def offline(): return HTMLResponse(OFFLINE_HTML)


@app.get("/icons/{name}")
def icon(name: str):
    if name not in ICONS: return PlainTextResponse("not found", status_code=404)
    return Response(make_icon(*ICONS[name]), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# 必須放在自訂路由之後：Gradio 掛在根路徑 "/"，其餘路由優先比對
app = gr.mount_gradio_app(app, build_demo(), path="/")

# 在背景載入嵌入模型：伺服器先開始監聽（Render 偵測得到埠），首次提問前模型就緒
threading.Thread(target=get_core, daemon=True).start()
