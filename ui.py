"""Gradio 介面：RWD 樣式、PWA <head>、每位使用者獨立的 session 狀態、Word / CSV 匯出。"""
import csv, os, re, tempfile
from datetime import datetime

import gradio as gr
from docx import Document
from docx.shared import Pt, RGBColor

from rag_engine import ENV_KEY, MODELS, RAG, STRATEGIES

THEME_COLOR = "#10b981"

CSS_BASE = """
.gradio-container{max-width:1200px!important;margin:auto}
#hdr{padding:18px 4px 6px}#hdr h1{font-size:26px;margin:0;font-weight:700}
#hdr p{color:#6b7280;margin:4px 0 0;font-size:14px}
.side{border-radius:14px!important}
#send{min-width:90px}
footer{display:none!important}
"""

# RWD：手機單欄、觸控友善、iOS 輸入不自動縮放、支援瀏覽器安全區（瀏海 / 底部手勢列）
CSS_RWD = """
.gradio-container{
  padding-left:max(12px,env(safe-area-inset-left))!important;
  padding-right:max(12px,env(safe-area-inset-right))!important;
  padding-bottom:calc(12px + env(safe-area-inset-bottom,0px))!important}
input,textarea,select{font-size:16px!important}
button,.gr-button{min-height:40px}
#chat{height:62vh!important}
#inputrow{flex-wrap:nowrap!important;align-items:stretch}
#inputrow>*{min-width:0!important}
#send{min-width:72px!important}
@media (max-width:1023px){#layout>.column{min-width:100%!important;flex-basis:100%!important}}
@media (max-width:640px){
  #hdr{padding:calc(10px + env(safe-area-inset-top,0px)) 2px 4px}
  #hdr h1{font-size:20px}#hdr p{font-size:12px}
  #chat{height:55dvh!important}
  .actions{flex-wrap:wrap!important}.actions>*{min-width:45%!important;flex:1 1 45%!important}
}
@media (display-mode:standalone){html,body{overscroll-behavior-y:contain}}
"""

PWA_HEAD = f"""
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="{THEME_COLOR}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="RAG 問答">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192.png">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<script>
if ("serviceWorker" in navigator) {{
  window.addEventListener("load", () =>
    navigator.serviceWorker.register("/sw.js", {{scope: "/"}}).catch(() => {{}}));
}}
</script>
"""

_GREY = RGBColor(0x6B, 0x72, 0x80)


# ── 匯出：Word / CSV ──
def _out_path(ext):
    return os.path.join(tempfile.gettempdir(), f"RAG問答紀錄_{datetime.now():%Y%m%d_%H%M%S}.{ext}")


def export_csv(records):
    if not records: gr.Warning("目前沒有問答紀錄可匯出"); return None
    path = _out_path("csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig：Excel 開啟中文不亂碼
        w = csv.DictWriter(f, fieldnames=list(records[0])); w.writeheader(); w.writerows(records)
    return path


def _md_runs(par, text):  # 將 **粗體** 轉成 Word 粗體
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part: par.add_run(part).bold = bool(i % 2)


def export_docx(records, with_src=True):
    if not records: gr.Warning("目前沒有問答紀錄可匯出"); return None
    doc = Document()
    st = doc.styles["Normal"]; st.font.name, st.font.size = "Microsoft JhengHei", Pt(11)
    st.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft JhengHei")
    doc.add_heading("RAG 文件問答紀錄", 0)
    meta = doc.add_paragraph(f"文件：{records[-1]['文件']}　·　匯出時間：{datetime.now():%Y-%m-%d %H:%M}　·　共 {len(records)} 題")
    meta.runs[0].font.color.rgb = _GREY
    for n, r in enumerate(records, 1):
        doc.add_heading(f"Q{n}．{r['問題']}", level=1)
        info = doc.add_paragraph(f"{r['時間']}　·　{r['策略']}　·　{r['模型']}")
        info.runs[0].font.size, info.runs[0].font.color.rgb = Pt(9), _GREY
        for line in r["回答"].splitlines():
            line = line.rstrip()
            if not line.strip(): continue
            if m := re.match(r"^\s*#{1,6}\s+(.*)", line): doc.add_heading(m.group(1).replace("**", ""), level=2); continue
            if m := re.match(r"^(\s*)[-*•]\s+(.*)", line):
                par = doc.add_paragraph(style="List Bullet 2" if len(m.group(1)) >= 2 else "List Bullet"); _md_runs(par, m.group(2))
            elif m := re.match(r"^\s*\d+[.)]\s+(.*)", line):
                par = doc.add_paragraph(style="List Number"); _md_runs(par, m.group(1))
            else: _md_runs(doc.add_paragraph(), line)
        if with_src and r["參考片段"]:
            h = doc.add_paragraph(); run = h.add_run("參考片段"); run.bold, run.font.size = True, Pt(9)
            for blk in r["參考片段"].split("\n\n"):
                p = doc.add_paragraph(blk.strip()); p.paragraph_format.left_indent = Pt(12)
                for run in p.runs: run.font.size, run.font.color.rgb = Pt(8.5), RGBColor(0x55, 0x5B, 0x66)
    path = _out_path("docx"); doc.save(path)
    return path


# ── 事件處理（rag 為每位使用者專屬的 session 狀態）──
def _rag(s):
    return s if s is not None else RAG()


def _key_status(s, n_models=0):
    if s.client is None: return "⚠ 尚未設定 Key"
    who = "伺服器預設 Key" if s.using_env_key else "你的 Key"
    return f"✓ 使用{who} · {n_models} 個模型" if n_models else f"✗ {who}無效或無法取得模型"


def on_key(key, cur, s):
    s = _rag(s); s.set_key(key)
    ms = s.list_models()
    upd = gr.update(choices=ms, value=cur if cur in ms else (MODELS[0] if MODELS[0] in ms else ms[0])) if ms else gr.update()
    return _key_status(s, len(ms)), upd, s


def on_upload(f, s):
    s = _rag(s)
    return ("⚠ 請選擇檔案" if f is None else s.load(f if isinstance(f, str) else f.name)), s


def on_ask(q, history, records, strategy, k, model, s):
    s = _rag(s); q = (q or "").strip()
    if not q: return "", history, gr.update(), records, s
    ans, src = s.answer(q, strategy, k, model)
    records = records + [{"時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "文件": s.name, "問題": q,
                          "回答": re.sub(r"\n*<sub>.*?</sub>", "", ans, flags=re.S).strip(),
                          "策略": STRATEGIES[strategy][0], "模型": s.model,
                          "參考片段": src.split("─" * 40, 1)[-1].strip()}]
    return "", history + [{"role": "user", "content": q}, {"role": "assistant", "content": ans}], src, records, s


def build_demo():
    boot = RAG()                      # 僅用來取得初始模型清單
    init_models = boot.list_models() or MODELS
    css = CSS_BASE + CSS_RWD
    theme = gr.themes.Soft(primary_hue="emerald", neutral_hue="slate", radius_size="lg",
                           font=[gr.themes.GoogleFont("Noto Sans TC"), "sans-serif"])

    with gr.Blocks(title="RAG 文件問答", css=css, theme=theme, head=PWA_HEAD) as demo:
        gr.HTML("<div id='hdr'><h1>📚 RAG 文件問答</h1><p>上傳 PDF / DOCX，選擇檢索策略，直接提問 · Groq × fastembed</p></div>")
        with gr.Row(equal_height=False, elem_id="layout"):
            with gr.Column(scale=1, min_width=300, elem_classes="side"):
                with gr.Accordion("🔑 Groq API Key", open=not ENV_KEY):
                    key = gr.Textbox(type="password", show_label=False, placeholder="gsk_…（Enter 套用；留空使用伺服器預設）")
                    key_status = gr.Markdown("✓ 使用伺服器預設 Key" if ENV_KEY else "⚠ 尚未設定 Key")
                model = gr.Dropdown(init_models, value=MODELS[0] if MODELS[0] in init_models else init_models[0],
                                    allow_custom_value=True, label="模型")
                file = gr.File(label="上傳文件", file_types=[".pdf", ".docx"], type="filepath", height=120)
                status = gr.Textbox(show_label=False, interactive=False, lines=2, placeholder="尚未載入文件")
                strategy = gr.Radio([(v[0], k) for k, v in STRATEGIES.items()], value="hybrid", label="檢索策略")
                desc = gr.Markdown(f"<small>{STRATEGIES['hybrid'][1]}</small>")
                topk = gr.Slider(1, 10, 4, step=1, label="片段數量 Top-K")
            with gr.Column(scale=2, min_width=300):
                chat = gr.Chatbot(type="messages", height=520, show_label=False, elem_id="chat",
                                  placeholder="**上傳文件後開始提問**<br>例如：這份文件的重點是什麼？")
                with gr.Row(elem_id="inputrow"):
                    q = gr.Textbox(show_label=False, placeholder="輸入問題，Enter 送出", scale=6, container=False)
                    send = gr.Button("送出", variant="primary", scale=1, elem_id="send")
                with gr.Row():
                    gr.Examples([["這份文件的重點是什麼？"], ["文件提到哪些規定或限制？"], ["有哪些風險或注意事項？"]], q, label=None)
                    clear = gr.Button("🗑 清除對話", size="sm", variant="secondary")
                with gr.Accordion("🔎 檢索到的片段", open=False):
                    src = gr.Textbox(show_label=False, lines=12, interactive=False)
                with gr.Row(elem_classes="actions"):
                    with_src = gr.Checkbox(True, label="Word 包含參考片段", scale=2)
                    btn_docx = gr.Button("📄 匯出 Word", size="sm", scale=1)
                    btn_csv = gr.Button("📊 匯出 CSV", size="sm", scale=1)
                out_file = gr.File(label="下載檔案", visible=False)

        records = gr.State([])
        rag_state = gr.State(None, delete_callback=lambda r: r.close() if r else None)   # session 結束時釋放向量

        key.submit(on_key, [key, model, rag_state], [key_status, model, rag_state])
        key.blur(on_key, [key, model, rag_state], [key_status, model, rag_state])
        file.upload(on_upload, [file, rag_state], [status, rag_state])
        strategy.change(lambda s: f"<small>{STRATEGIES[s][1]}</small>", strategy, desc)
        for ev in (q.submit, send.click):
            ev(on_ask, [q, chat, records, strategy, topk, model, rag_state], [q, chat, src, records, rag_state])
        clear.click(lambda: ([], "", [], gr.update(value=None, visible=False)), None, [chat, src, records, out_file])
        show = lambda p: gr.update(value=p, visible=bool(p))
        btn_docx.click(lambda r, w: show(export_docx(r, w)), [records, with_src], out_file)
        btn_csv.click(lambda r: show(export_csv(r)), records, out_file)

    return demo.queue(default_concurrency_limit=4)
