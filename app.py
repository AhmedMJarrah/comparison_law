"""
app.py
------
Streamlit web interface for the Law Comparison Pipeline.

Features:
  - File upload for JSON + TXT sources
  - Law selection from multi-law JSON
  - Full pipeline execution with progress
  - Side-by-side article comparison view
  - Filter by match status
  - Search by article number
  - Download HTML + Excel reports

Run:
    streamlit run app.py
"""

import streamlit as st
import json
import tempfile
import time
from pathlib import Path

# ── Page config (must be first) ────────────────────────────────
st.set_page_config(
    page_title    = "Law Comparison Pipeline",
    page_icon     = "⚖️",
    layout        = "wide",
    initial_sidebar_state = "expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Global ── */
  @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap');

  html, body, [class*="css"] {
    font-family: 'Tajawal', 'Segoe UI', Tahoma, sans-serif;
  }

  /* ── Header ── */
  .main-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%);
    padding: 1.5rem 2rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    color: white;
  }
  .main-header h1 { color: white; margin: 0; font-size: 1.8rem; }
  .main-header p  { color: #aaaacc; margin: 0.3rem 0 0; font-size: 0.9rem; }

  /* ── KPI Cards ── */
  .kpi-row { display: flex; gap: 12px; margin: 1rem 0; flex-wrap: wrap; }
  .kpi-card {
    flex: 1; min-width: 120px;
    background: white;
    border-radius: 10px;
    padding: 14px 16px;
    text-align: center;
    border-top: 4px solid #ddd;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .kpi-card .num { font-size: 1.8rem; font-weight: 800; line-height: 1; }
  .kpi-card .lbl { font-size: 0.75rem; color: #666; margin-top: 4px; }
  .kpi-match   { border-color: #28a745; }  .kpi-match .num   { color: #28a745; }
  .kpi-near    { border-color: #ffc107; }  .kpi-near .num    { color: #e6a800; }
  .kpi-mis     { border-color: #dc3545; }  .kpi-mis .num     { color: #dc3545; }
  .kpi-miss    { border-color: #6c757d; }  .kpi-miss .num    { color: #6c757d; }
  .kpi-extra   { border-color: #17a2b8; }  .kpi-extra .num   { color: #17a2b8; }
  .kpi-cov     { border-color: #0f3460; }  .kpi-cov .num     { color: #0f3460; }

  /* ── Status badges ── */
  .badge {
    display: inline-block; padding: 2px 10px;
    border-radius: 10px; font-size: 0.75rem; font-weight: 600;
  }
  .badge-MATCH      { background:#d4edda; color:#155724; }
  .badge-NEAR_MATCH { background:#fff3cd; color:#856404; }
  .badge-MISMATCH   { background:#f8d7da; color:#721c24; }
  .badge-MISSING    { background:#e2e3e5; color:#383d41; }
  .badge-EXTRA      { background:#d1ecf1; color:#0c5460; }

  /* ── Article cards ── */
  .art-card {
    border: 1px solid #e9ecef;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
    background: white;
    font-size: 0.85rem;
    line-height: 1.7;
    direction: rtl;
    text-align: right;
  }
  .art-card-header {
    display: flex; justify-content: space-between;
    align-items: center; margin-bottom: 8px;
    border-bottom: 1px solid #f0f0f0; padding-bottom: 6px;
  }
  .art-num { font-weight: 700; color: #0f3460; font-size: 1rem; }
  .art-text { color: #333; white-space: pre-wrap; word-break: break-word; }
  .art-missing { background: #f8f9fa; color: #aaa; font-style: italic; }

  .score-bar-wrap { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
  .score-bar { flex:1; height:5px; border-radius:3px; background:#e9ecef; overflow:hidden; }
  .score-fill { height:100%; border-radius:3px; }

  /* ── Divider ── */
  .col-divider {
    border-right: 2px solid #e9ecef;
    min-height: 100px;
  }

  /* ── Sidebar ── */
  .sidebar-section {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 12px;
  }

  /* ── Verdict ── */
  .verdict-badge {
    display: inline-block; padding: 6px 20px;
    border-radius: 20px; font-weight: 700; font-size: 1rem;
  }
  .v-ممتاز      { background:#d4edda; color:#155724; }
  .v-جيد        { background:#cce5ff; color:#004085; }
  .v-مقبول      { background:#fff3cd; color:#856404; }
</style>
""", unsafe_allow_html=True)


# ── Imports (after page config) ────────────────────────────────
import sys
import os
import logging
logging.basicConfig(level=logging.WARNING)

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent))

# Cloud-safe output dirs — use /tmp so Streamlit Cloud can write
import os
os.environ.setdefault("OUTPUT_DIR",    "/tmp/output")
os.environ.setdefault("REPORTS_DIR",   "/tmp/output/reports")
os.environ.setdefault("SUMMARIES_DIR", "/tmp/output/summaries")
os.environ.setdefault("LOGS_DIR",      "/tmp/logs")
os.environ.setdefault("LOG_TO_FILE",   "false")
os.environ.setdefault("LOG_LEVEL",     "WARNING")
Path("/tmp/output/reports").mkdir(parents=True, exist_ok=True)
Path("/tmp/output/summaries").mkdir(parents=True, exist_ok=True)

from src.ingestion  import load_pair, list_laws_in_json
from src.extractor  import extract
from src.comparator import compare, MatchStatus, STATUS_EMOJI, STATUS_LABEL
from src.reporter   import generate_report
from src.normalizer import convert_numerals


# ── Helpers ────────────────────────────────────────────────────

STATUS_COLORS = {
    MatchStatus.MATCH:      "#28a745",
    MatchStatus.NEAR_MATCH: "#ffc107",
    MatchStatus.MISMATCH:   "#dc3545",
    MatchStatus.MISSING:    "#adb5bd",
    MatchStatus.EXTRA:      "#17a2b8",
}

STATUS_AR = {
    MatchStatus.MATCH:      "✅ تطابق",
    MatchStatus.NEAR_MATCH: "⚠️ جزئي",
    MatchStatus.MISMATCH:   "❌ تعارض",
    MatchStatus.MISSING:    "🔍 غائب",
    MatchStatus.EXTRA:      "➕ زائد",
}

def read_file(uploaded) -> str:
    """Read uploaded file with encoding fallback."""
    raw = uploaded.read()
    for enc in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode file — please save as UTF-8")


def list_laws(json_text: str) -> list[dict]:
    """Parse law list from JSON text."""
    data = json.loads(json_text)
    if not isinstance(data, list):
        data = [data]
    laws = []
    for i, law in enumerate(data):
        leg_num = convert_numerals(str(law.get("Leg_Number", "?")))
        year    = convert_numerals(str(law.get("Year", "?")))
        name    = law.get("Leg_Name", "N/A")
        arts    = len(law.get("Articles", []))
        laws.append({"index": i, "label": f"[{i}] Law {leg_num}/{year} — {name} ({arts} مادة)", "name": name})
    return laws


def score_color(score: float) -> str:
    if score >= 95: return "#28a745"
    if score >= 80: return "#ffc107"
    return "#dc3545"


def render_article_card(art, source: str) -> str:
    """Render a single article as HTML card."""
    text = art.json_text if source == "json" else art.txt_text
    status_class = f"badge-{art.status.value}"
    status_label = STATUS_AR.get(art.status, art.status.value)

    if not text:
        return f"""
        <div class="art-card art-missing">
            <div class="art-card-header">
                <span class="art-num">مادة {art.article_number}</span>
                <span class="badge {status_class}">{status_label}</span>
            </div>
            <div class="art-text">— غير متوفر في هذا المصدر —</div>
        </div>"""

    score_html = ""
    if art.similarity_score > 0:
        color = score_color(art.similarity_score)
        score_html = f"""
        <div class="score-bar-wrap">
            <div class="score-bar"><div class="score-fill" style="width:{art.similarity_score}%;background:{color}"></div></div>
            <span style="font-size:0.75rem;color:{color};font-weight:600">{art.similarity_score:.0f}%</span>
        </div>"""

    preview = text[:400] + ("..." if len(text) > 400 else "")

    return f"""
    <div class="art-card">
        <div class="art-card-header">
            <span class="art-num">مادة {art.article_number}</span>
            <span class="badge {status_class}">{status_label}</span>
        </div>
        {score_html}
        <div class="art-text" style="margin-top:8px">{preview}</div>
    </div>"""


# ── Session state ───────────────────────────────────────────────
if "report" not in st.session_state:
    st.session_state.report    = None
if "report_paths" not in st.session_state:
    st.session_state.report_paths = None
if "json_text" not in st.session_state:
    st.session_state.json_text = None
if "txt_text" not in st.session_state:
    st.session_state.txt_text  = None


# ── Header ─────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>⚖️ Law Comparison Pipeline</h1>
    <p>نظام مقارنة النصوص القانونية — Arabic Legal Text Comparison System</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ─────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📁 Upload Files")

    json_file = st.file_uploader("Source 1 — JSON", type=["json"], key="json_upload")
    txt_file  = st.file_uploader("Source 2 — TXT",  type=["txt"],  key="txt_upload")

    law_index = 0
    law_name  = ""

    if json_file:
        try:
            json_text = read_file(json_file)
            st.session_state.json_text = json_text
            laws = list_laws(json_text)
            if len(laws) > 1:
                st.markdown("### 📋 Select Law")
                options = {l["label"]: l["index"] for l in laws}
                selected = st.selectbox("Law to compare:", list(options.keys()))
                law_index = options[selected]
                law_name  = laws[law_index]["name"]
            else:
                law_name = laws[0]["name"] if laws else ""
                st.success(f"✓ 1 law found: {law_name[:40]}")
        except Exception as e:
            st.error(f"JSON error: {e}")

    if txt_file:
        try:
            txt_text = read_file(txt_file)
            st.session_state.txt_text = txt_text
            st.success(f"✓ TXT loaded: {len(txt_text):,} chars")
        except Exception as e:
            st.error(f"TXT error: {e}")

    st.markdown("---")
    st.markdown("### ⚙️ Settings")
    sim_threshold   = st.slider("Match threshold (%)",      70, 100, 95)
    fuzzy_threshold = st.slider("Near-match threshold (%)", 50, 95,  80)

    st.markdown("---")

    run_btn = st.button(
        "🚀 Run Comparison",
        type="primary",
        use_container_width=True,
        disabled=not (json_file and txt_file)
    )


# ── Run pipeline ────────────────────────────────────────────────
if run_btn and json_file and txt_file:
    with st.spinner("Running pipeline..."):
        try:
            # Write temp files
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as jf:
                jf.write(st.session_state.json_text)
                json_tmp = jf.name

            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tf:
                tf.write(st.session_state.txt_text)
                txt_tmp = tf.name

            progress = st.progress(0, text="[1/4] Loading files...")
            pair = load_pair(json_tmp, txt_tmp, law_index=law_index)
            progress.progress(25, text="[2/4] Extracting articles...")

            extracted = extract(st.session_state.txt_text)
            progress.progress(50, text="[3/4] Comparing articles...")

            # Apply threshold overrides
            from src import config as cfg_mod
            cfg_mod.config.SIMILARITY_THRESHOLD  = sim_threshold
            cfg_mod.config.FUZZY_MATCH_THRESHOLD = fuzzy_threshold

            report = compare(pair.source1, extracted, pair.law_id)
            progress.progress(75, text="[4/4] Generating reports...")

            paths = generate_report(report)
            progress.progress(100, text="Done!")
            time.sleep(0.3)
            progress.empty()

            st.session_state.report       = report
            st.session_state.report_paths = paths

            # Cleanup
            os.unlink(json_tmp)
            os.unlink(txt_tmp)

        except Exception as e:
            st.error(f"Pipeline error: {e}")
            import traceback
            st.code(traceback.format_exc())


# ── Results ─────────────────────────────────────────────────────
report = st.session_state.report

if report:
    # ── KPI row ─────────────────────────────────────────────────
    verdict_class = f"v-{report.overall_verdict}"
    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
        <div>
            <b style="font-size:1.1rem">{report.law_name}</b><br>
            <span style="color:#666;font-size:0.85rem">Law {report.law_number}/{report.year}  |  Magazine № {report.metadata.json_magazine}</span>
        </div>
        <span class="verdict-badge {verdict_class}">الحكم: {report.overall_verdict}</span>
    </div>
    <div class="kpi-row">
        <div class="kpi-card kpi-cov"><div class="num">{report.coverage_pct:.1f}%</div><div class="lbl">التغطية</div></div>
        <div class="kpi-card kpi-cov"><div class="num">{report.match_pct:.1f}%</div><div class="lbl">التطابق</div></div>
        <div class="kpi-card kpi-match"><div class="num">{report.count_match}</div><div class="lbl">✅ تطابق</div></div>
        <div class="kpi-card kpi-near"><div class="num">{report.count_near_match}</div><div class="lbl">⚠️ جزئي</div></div>
        <div class="kpi-card kpi-mis"><div class="num">{report.count_mismatch}</div><div class="lbl">❌ تعارض</div></div>
        <div class="kpi-card kpi-miss"><div class="num">{report.count_missing}</div><div class="lbl">🔍 غائب</div></div>
        <div class="kpi-card kpi-extra"><div class="num">{report.count_extra}</div><div class="lbl">➕ زائد</div></div>
    </div>
    """, unsafe_allow_html=True)

    # ── Downloads ────────────────────────────────────────────────
    paths = st.session_state.report_paths
    if paths:
        dl_col1, dl_col2, _ = st.columns([1, 1, 3])
        with dl_col1:
            with open(paths["html"], "rb") as f:
                st.download_button("📄 Download HTML Report", f.read(),
                    file_name=paths["html"].name, mime="text/html", use_container_width=True)
        with dl_col2:
            with open(paths["excel"], "rb") as f:
                st.download_button("📊 Download Excel Summary", f.read(),
                    file_name=paths["excel"].name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True)

    st.markdown("---")

    # ── Filters ──────────────────────────────────────────────────
    st.markdown("### 🔍 Article Comparison")

    filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 1])

    with filter_col1:
        status_options = {
            "الكل": None,
            "✅ تطابق":         MatchStatus.MATCH,
            "⚠️ تطابق جزئي":    MatchStatus.NEAR_MATCH,
            "❌ تعارض":         MatchStatus.MISMATCH,
            "🔍 غائب":          MatchStatus.MISSING,
            "➕ زائد":          MatchStatus.EXTRA,
        }
        selected_status = st.selectbox("تصفية حسب الحالة:", list(status_options.keys()))
        filter_status = status_options[selected_status]

    with filter_col2:
        search_num = st.text_input("بحث برقم المادة:", placeholder="مثال: 42")

    with filter_col3:
        view_mode = st.radio("عرض:", ["جانبي ↔", "قائمة ☰"], horizontal=True)

    # ── Filter articles ──────────────────────────────────────────
    articles = report.articles
    if filter_status:
        articles = [a for a in articles if a.status == filter_status]
    if search_num.strip():
        articles = [a for a in articles if search_num.strip() in a.article_number]

    st.caption(f"عرض {len(articles)} من {len(report.articles)} مادة")

    # ── Pagination ───────────────────────────────────────────────
    PAGE_SIZE = 20
    total_pages = max(1, (len(articles) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.number_input("الصفحة:", min_value=1, max_value=total_pages, value=1, step=1)
    page_articles = articles[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    st.caption(f"صفحة {page} من {total_pages}")
    st.markdown("---")

    # ── Side-by-side view ────────────────────────────────────────
    if view_mode == "جانبي ↔":
        hdr_left, hdr_right = st.columns(2)
        with hdr_left:
            st.markdown("#### 📘 المصدر الأول (JSON)")
        with hdr_right:
            st.markdown("#### 📗 المصدر الثاني (TXT)")

        for art in page_articles:
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown(render_article_card(art, "json"), unsafe_allow_html=True)
            with col_r:
                st.markdown(render_article_card(art, "txt"), unsafe_allow_html=True)

    # ── List view ────────────────────────────────────────────────
    else:
        for art in page_articles:
            with st.expander(
                f"مادة {art.article_number}  |  "
                f"{STATUS_AR.get(art.status, '')}  |  "
                f"{'%.0f%%' % art.similarity_score if art.similarity_score > 0 else '—'}",
                expanded=art.status in (MatchStatus.MISMATCH, MatchStatus.NEAR_MATCH)
            ):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**📘 المصدر الأول (JSON)**")
                    st.text_area("", art.json_text or "— غير متوفر —",
                        height=150, key=f"j_{art.article_number}", disabled=True)
                with c2:
                    st.markdown("**📗 المصدر الثاني (TXT)**")
                    st.text_area("", art.txt_text or "— غير متوفر —",
                        height=150, key=f"t_{art.article_number}", disabled=True)
                if art.diff_hint:
                    st.caption(f"🔍 فارق: {art.diff_hint}")

else:
    # ── Empty state ──────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;padding:3rem;color:#aaa;">
        <div style="font-size:3rem">⚖️</div>
        <h3 style="color:#888">ابدأ المقارنة</h3>
        <p>ارفع ملف JSON وملف TXT من الشريط الجانبي ثم اضغط <b>Run Comparison</b></p>
        <br>
        <div style="display:inline-flex;gap:2rem;font-size:0.85rem;">
            <div>📁 <b>Source 1</b><br>ملف JSON يحتوي على القوانين</div>
            <div>📄 <b>Source 2</b><br>ملف TXT من مصدر OCR</div>
            <div>📊 <b>التقارير</b><br>HTML + Excel تلقائياً</div>
        </div>
    </div>
    """, unsafe_allow_html=True)