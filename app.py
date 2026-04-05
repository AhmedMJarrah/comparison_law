"""
app.py
------
Streamlit web interface for the Law Comparison Pipeline.
Supports batch mode: one JSON + multiple TXT files.
Auto-pairs each TXT to its matching law in the JSON by
extracting law number + year from the Arabic filename.

Run:
    streamlit run app.py
"""

import streamlit as st
import json
import re
import tempfile
import time
import os
from pathlib import Path

st.set_page_config(
    page_title    = "Law Comparison Pipeline",
    page_icon     = "⚖️",
    layout        = "wide",
    initial_sidebar_state = "expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap');
  html, body, [class*="css"] { font-family: 'Tajawal', 'Segoe UI', Tahoma, sans-serif; }

  .main-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%);
    padding: 1.5rem 2rem; border-radius: 12px;
    margin-bottom: 1.5rem; color: white;
  }
  .main-header h1 { color: white; margin: 0; font-size: 1.8rem; }
  .main-header p  { color: #aaaacc; margin: 0.3rem 0 0; font-size: 0.9rem; }

  .kpi-row { display: flex; gap: 12px; margin: 1rem 0; flex-wrap: wrap; }
  .kpi-card {
    flex: 1; min-width: 110px; background: white;
    border-radius: 10px; padding: 14px 16px; text-align: center;
    border-top: 4px solid #ddd; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .kpi-card .num { font-size: 1.7rem; font-weight: 800; line-height: 1; }
  .kpi-card .lbl { font-size: 0.72rem; color: #666; margin-top: 4px; }
  .kpi-match  { border-color:#28a745; } .kpi-match .num  { color:#28a745; }
  .kpi-near   { border-color:#ffc107; } .kpi-near .num   { color:#e6a800; }
  .kpi-mis    { border-color:#dc3545; } .kpi-mis .num    { color:#dc3545; }
  .kpi-miss   { border-color:#6c757d; } .kpi-miss .num   { color:#6c757d; }
  .kpi-extra  { border-color:#17a2b8; } .kpi-extra .num  { color:#17a2b8; }
  .kpi-cov    { border-color:#0f3460; } .kpi-cov .num    { color:#0f3460; }

  .law-row {
    background: white; border-radius: 10px; padding: 14px 18px;
    margin-bottom: 10px; border-right: 5px solid #ddd;
    box-shadow: 0 1px 6px rgba(0,0,0,0.05); cursor: pointer;
    display: flex; justify-content: space-between; align-items: center;
  }
  .law-row:hover { box-shadow: 0 3px 12px rgba(0,0,0,0.1); }
  .law-row.border-green  { border-color: #28a745; }
  .law-row.border-yellow { border-color: #ffc107; }
  .law-row.border-red    { border-color: #dc3545; }
  .law-row.border-gray   { border-color: #adb5bd; }

  .badge {
    display: inline-block; padding: 2px 10px;
    border-radius: 10px; font-size: 0.75rem; font-weight: 600;
  }
  .badge-MATCH      { background:#d4edda; color:#155724; }
  .badge-NEAR_MATCH { background:#fff3cd; color:#856404; }
  .badge-MISMATCH   { background:#f8d7da; color:#721c24; }
  .badge-MISSING    { background:#e2e3e5; color:#383d41; }
  .badge-EXTRA      { background:#d1ecf1; color:#0c5460; }

  .art-card {
    border: 1px solid #e9ecef; border-radius: 8px; padding: 12px 14px;
    margin-bottom: 8px; background: white; font-size: 0.85rem;
    line-height: 1.7; direction: rtl; text-align: right;
  }
  .art-card-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 8px; border-bottom: 1px solid #f0f0f0; padding-bottom: 6px;
  }
  .art-num  { font-weight: 700; color: #0f3460; font-size: 1rem; }
  .art-text { color: #333; white-space: pre-wrap; word-break: break-word; }
  .score-bar-wrap { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
  .score-bar { flex:1; height:5px; border-radius:3px; background:#e9ecef; overflow:hidden; }
  .score-fill { height:100%; border-radius:3px; }

  .verdict-badge {
    display: inline-block; padding: 6px 20px;
    border-radius: 20px; font-weight: 700; font-size: 0.95rem;
  }
  .v-ممتاز  { background:#d4edda; color:#155724; }
  .v-جيد    { background:#cce5ff; color:#004085; }
  .v-مقبول  { background:#fff3cd; color:#856404; }
  .v-يحتاج-مراجعة { background:#f8d7da; color:#721c24; }

  .pair-chip {
    display: inline-block; padding: 3px 10px; border-radius: 8px;
    font-size: 0.75rem; font-weight: 500; margin: 2px;
  }
  .chip-ok     { background:#d4edda; color:#155724; }
  .chip-warn   { background:#fff3cd; color:#856404; }
  .chip-err    { background:#f8d7da; color:#721c24; }
  .chip-skip   { background:#e2e3e5; color:#383d41; }
</style>
""", unsafe_allow_html=True)

# ── Cloud-safe paths ────────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OUTPUT_DIR",    "/tmp/output")
os.environ.setdefault("REPORTS_DIR",   "/tmp/output/reports")
os.environ.setdefault("SUMMARIES_DIR", "/tmp/output/summaries")
os.environ.setdefault("LOGS_DIR",      "/tmp/logs")
os.environ.setdefault("LOG_TO_FILE",   "false")
os.environ.setdefault("LOG_LEVEL",     "WARNING")
Path("/tmp/output/reports").mkdir(parents=True, exist_ok=True)
Path("/tmp/output/summaries").mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(level=logging.WARNING)

from src.ingestion  import load_pair
from src.extractor  import extract
from src.comparator import compare, MatchStatus, STATUS_EMOJI, STATUS_LABEL
from src.reporter   import generate_report
from src.normalizer import convert_numerals


# ── Helpers ─────────────────────────────────────────────────────

STATUS_AR = {
    MatchStatus.MATCH:      "✅ تطابق",
    MatchStatus.NEAR_MATCH: "⚠️ جزئي",
    MatchStatus.MISMATCH:   "❌ تعارض",
    MatchStatus.MISSING:    "🔍 غائب",
    MatchStatus.EXTRA:      "➕ زائد",
}

def read_bytes(uploaded) -> str:
    raw = uploaded.read()
    for enc in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode file — please save as UTF-8")


def parse_law_index_from_filename(filename: str, laws: list[dict]) -> int | None:
    """
    Extract law number + year from Arabic TXT filename and find
    its matching index in the JSON law list.

    Handles all known filename patterns:
      قانون_رقم_{N}_لسنة_{Y}         plain law
      قانون_معدل_رقم_{N}_لسنة_{Y}    amended law
      قانون_مؤقت_رقم_{N}_لسنة_{Y}    temporary law
      قانون_مؤقت_معدل_رقم_{N}_لسنة_{Y} temporary amended law
    """
    # Convert Arabic-Indic numerals just in case
    fname = convert_numerals(filename)

    # Strategy 1: extract رقم + لسنة together (most reliable)
    # Handles: رقم_31_لسنة_2017 regardless of what comes before رقم
    m = re.search(r'رقم[_\s]+(\d+)[_\s]+لسنة[_\s]+(\d+)', fname)
    if m:
        num_from_file  = m.group(1)
        year_from_file = m.group(2)

        # Try exact match first (number + year)
        for law in laws:
            if (str(law.get("leg_number", "")) == num_from_file and
                    str(law.get("year", "")) == year_from_file):
                return law["index"]

        # Try year only as fallback (if law number differs slightly)
        for law in laws:
            if str(law.get("year", "")) == year_from_file:
                return law["index"]

    # Strategy 2: extract just لسنة (last resort)
    m2 = re.search(r'لسنة[_\s]+(\d+)', fname)
    if m2:
        year_from_file = m2.group(1)
        for law in laws:
            if str(law.get("year", "")) == year_from_file:
                return law["index"]

    return None


def list_laws(json_text: str) -> list[dict]:
    data = json.loads(json_text)
    if not isinstance(data, list):
        data = [data]
    laws = []
    for i, law in enumerate(data):
        leg_number = convert_numerals(str(law.get("Leg_Number", "?")))
        year       = convert_numerals(str(law.get("Year", "?")))
        name       = law.get("Leg_Name", "N/A")
        arts       = len(law.get("Articles", []))
        laws.append({
            "index":      i,
            "leg_number": leg_number,
            "year":       year,
            "name":       name,
            "articles":   arts,
            "label":      f"[{i}] Law {leg_number}/{year} — {name} ({arts} مادة)",
        })
    return laws


def score_color(score: float) -> str:
    if score >= 95: return "#28a745"
    if score >= 80: return "#ffc107"
    return "#dc3545"


def row_border_class(match_pct: float) -> str:
    if match_pct >= 95:  return "border-green"
    if match_pct >= 80:  return "border-yellow"
    if match_pct >= 0.1: return "border-red"
    return "border-gray"


def render_article_card(art, source: str) -> str:
    text         = art.json_text if source == "json" else art.txt_text
    status_class = f"badge-{art.status.value}"
    status_label = STATUS_AR.get(art.status, art.status.value)
    if not text:
        return f"""<div class="art-card" style="background:#f8f9fa;">
            <div class="art-card-header">
                <span class="art-num">مادة {art.article_number}</span>
                <span class="badge {status_class}">{status_label}</span>
            </div>
            <div class="art-text" style="color:#aaa;font-style:italic;">— غير متوفر في هذا المصدر —</div>
        </div>"""
    score_html = ""
    if art.similarity_score > 0:
        color = score_color(art.similarity_score)
        score_html = f"""<div class="score-bar-wrap">
            <div class="score-bar"><div class="score-fill" style="width:{art.similarity_score}%;background:{color}"></div></div>
            <span style="font-size:0.75rem;color:{color};font-weight:600">{art.similarity_score:.0f}%</span>
        </div>"""
    preview = text[:400] + ("..." if len(text) > 400 else "")
    return f"""<div class="art-card">
        <div class="art-card-header">
            <span class="art-num">مادة {art.article_number}</span>
            <span class="badge {status_class}">{status_label}</span>
        </div>
        {score_html}
        <div class="art-text" style="margin-top:8px">{preview}</div>
    </div>"""


# ── Session state ────────────────────────────────────────────────
for key in ["batch_results", "json_text", "laws", "pairing_summary"]:
    if key not in st.session_state:
        st.session_state[key] = None


# ── Header ───────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>⚖️ Law Comparison Pipeline</h1>
    <p>نظام مقارنة النصوص القانونية — Batch mode: one JSON + multiple TXT files</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📁 Upload Files")

    json_file = st.file_uploader(
        "Source 1 — JSON (contains all laws)",
        type=["json"], key="json_upload"
    )

    txt_files = st.file_uploader(
        "Source 2 — TXT files (one per law, multiple allowed)",
        type=["txt"], accept_multiple_files=True, key="txt_upload"
    )

    # ── Parse JSON and preview pairing ──────────────────────────
    pairing = []   # list of {txt_name, law_index, law_name, status}

    if json_file and txt_files:
        try:
            json_text = read_bytes(json_file)
            st.session_state.json_text = json_text
            laws = list_laws(json_text)
            st.session_state.laws = laws
            st.success(f"✓ JSON: {len(laws)} laws found")

            st.markdown("---")
            st.markdown("### 🔗 Auto-pairing preview")

            used_indices = set()
            for tf in txt_files:
                idx = parse_law_index_from_filename(tf.name, laws)
                if idx is None:
                    pairing.append({
                        "txt_name":  tf.name,
                        "law_index": None,
                        "law_name":  "❌ No match found",
                        "status":    "error"
                    })
                elif idx in used_indices:
                    pairing.append({
                        "txt_name":  tf.name,
                        "law_index": idx,
                        "law_name":  laws[idx]["name"],
                        "status":    "duplicate"
                    })
                else:
                    used_indices.add(idx)
                    pairing.append({
                        "txt_name":  tf.name,
                        "law_index": idx,
                        "law_name":  laws[idx]["name"],
                        "status":    "ok"
                    })

            st.session_state.pairing_summary = pairing

            # Show pairing chips
            for p in pairing:
                chip_class = {
                    "ok":        "chip-ok",
                    "error":     "chip-err",
                    "duplicate": "chip-warn",
                }.get(p["status"], "chip-skip")
                icon = {"ok": "✓", "error": "✗", "duplicate": "⚠"}.get(p["status"], "?")
                short_name = p["law_name"][:35] + "..." if len(p["law_name"]) > 35 else p["law_name"]
                st.markdown(
                    f'<span class="pair-chip {chip_class}">{icon} {short_name}</span>',
                    unsafe_allow_html=True
                )

            ok_count  = sum(1 for p in pairing if p["status"] == "ok")
            err_count = sum(1 for p in pairing if p["status"] == "error")
            st.markdown(f"**{ok_count}** paired ✅  |  **{err_count}** unmatched ❌")

        except Exception as e:
            st.error(f"Error: {e}")

    elif json_file:
        try:
            json_text = read_bytes(json_file)
            st.session_state.json_text = json_text
            laws = list_laws(json_text)
            st.session_state.laws = laws
            st.success(f"✓ JSON: {len(laws)} laws found")
            st.info("Now upload TXT files ↑")
        except Exception as e:
            st.error(f"JSON error: {e}")

    st.markdown("---")
    st.markdown("### ⚙️ Settings")
    sim_threshold   = st.slider("Match threshold (%)",      70, 100, 95)
    fuzzy_threshold = st.slider("Near-match threshold (%)", 50, 95,  80)
    st.markdown("---")

    ready  = (json_file and txt_files and
              st.session_state.pairing_summary and
              any(p["status"] == "ok" for p in
                  (st.session_state.pairing_summary or [])))

    run_btn = st.button(
        "🚀 Run Batch Comparison",
        type="primary",
        use_container_width=True,
        disabled=not ready
    )


# ── Run batch pipeline ───────────────────────────────────────────
if run_btn and ready:

    pairing     = st.session_state.pairing_summary
    json_text   = st.session_state.json_text
    laws        = st.session_state.laws
    valid_pairs = [p for p in pairing if p["status"] == "ok"]

    # Write JSON to temp file once
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as jf:
        jf.write(json_text)
        json_tmp = jf.name

    # Reset results
    st.session_state.batch_results = []

    progress_bar = st.progress(0, text="Starting batch comparison...")
    status_area  = st.empty()
    batch_results = []

    # Build a lookup: txt filename → uploaded file object
    txt_lookup = {tf.name: tf for tf in txt_files}

    for i, pair_info in enumerate(valid_pairs):
        pct  = int((i / len(valid_pairs)) * 100)
        law_name_short = pair_info["law_name"][:40]
        progress_bar.progress(pct, text=f"[{i+1}/{len(valid_pairs)}] {law_name_short}...")
        status_area.info(f"⚙️ Comparing: {law_name_short}")

        try:
            txt_file_obj = txt_lookup[pair_info["txt_name"]]
            txt_text     = read_bytes(txt_file_obj)

            # Write TXT to temp file
            with tempfile.NamedTemporaryFile(
                suffix=".txt", delete=False, mode="w", encoding="utf-8"
            ) as tf:
                tf.write(txt_text)
                txt_tmp = tf.name

            # Apply thresholds
            from src import config as cfg_mod
            cfg_mod.config.SIMILARITY_THRESHOLD  = sim_threshold
            cfg_mod.config.FUZZY_MATCH_THRESHOLD = fuzzy_threshold

            # Run pipeline
            pair     = load_pair(json_tmp, txt_tmp, law_index=pair_info["law_index"])
            extracted = extract(txt_text)
            report   = compare(pair.source1, extracted, pair.law_id)
            paths    = generate_report(report)

            batch_results.append({
                "report":    report,
                "paths":     paths,
                "txt_name":  pair_info["txt_name"],
                "status":    "success",
            })
            os.unlink(txt_tmp)

        except Exception as e:
            batch_results.append({
                "report":   None,
                "paths":    None,
                "txt_name": pair_info["txt_name"],
                "law_name": pair_info["law_name"],
                "status":   "failed",
                "error":    str(e),
            })

    os.unlink(json_tmp)

    # Sort by match_pct ascending (worst first)
    batch_results.sort(key=lambda x: (
        x["report"].match_pct if x["report"] else 0
    ))

    progress_bar.progress(100, text="Done!")
    time.sleep(0.5)
    progress_bar.empty()
    status_area.empty()
    st.session_state.batch_results = batch_results
    st.success(f"✅ Batch complete — {len([r for r in batch_results if r['status']=='success'])} laws compared!")


# ── Display results ──────────────────────────────────────────────
batch_results = st.session_state.batch_results

if batch_results:

    successful = [r for r in batch_results if r["status"] == "success"]
    failed     = [r for r in batch_results if r["status"] == "failed"]

    # ── Master KPIs ─────────────────────────────────────────────
    total_json    = sum(r["report"].total_json       for r in successful)
    total_match   = sum(r["report"].count_match      for r in successful)
    total_near    = sum(r["report"].count_near_match for r in successful)
    total_mis     = sum(r["report"].count_mismatch   for r in successful)
    total_missing = sum(r["report"].count_missing    for r in successful)
    total_extra   = sum(r["report"].count_extra      for r in successful)
    avg_coverage  = (sum(r["report"].coverage_pct    for r in successful) / len(successful)) if successful else 0
    avg_match     = (sum(r["report"].match_pct       for r in successful) / len(successful)) if successful else 0

    st.markdown(f"""
    <div class="kpi-row">
        <div class="kpi-card kpi-cov"><div class="num">{len(successful)}</div><div class="lbl">Laws compared</div></div>
        <div class="kpi-card kpi-cov"><div class="num">{avg_coverage:.1f}%</div><div class="lbl">Avg coverage</div></div>
        <div class="kpi-card kpi-cov"><div class="num">{avg_match:.1f}%</div><div class="lbl">Avg match rate</div></div>
        <div class="kpi-card kpi-match"><div class="num">{total_match}</div><div class="lbl">✅ Match</div></div>
        <div class="kpi-card kpi-near"><div class="num">{total_near}</div><div class="lbl">⚠️ Near match</div></div>
        <div class="kpi-card kpi-mis"><div class="num">{total_mis}</div><div class="lbl">❌ Mismatch</div></div>
        <div class="kpi-card kpi-miss"><div class="num">{total_missing}</div><div class="lbl">🔍 Missing</div></div>
        <div class="kpi-card kpi-extra"><div class="num">{total_extra}</div><div class="lbl">➕ Extra</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.caption("⬇️ Sorted by match rate — laws needing most attention appear first")
    st.markdown("---")

    # ── Failed runs ──────────────────────────────────────────────
    if failed:
        with st.expander(f"⚠️ {len(failed)} law(s) failed — click to see errors"):
            for r in failed:
                st.error(f"**{r.get('law_name', r['txt_name'])}** — {r['error']}")

    # ── Law rows (sorted worst first) ───────────────────────────
    st.markdown("### 📋 Results by Law")

    for idx, result in enumerate(successful):
        report = result["report"]
        bc     = row_border_class(report.match_pct)
        vc     = f"v-{report.overall_verdict.replace(' ', '-')}"

        with st.expander(
            f"{'❌' if report.match_pct < 80 else '⚠️' if report.match_pct < 95 else '✅'}  "
            f"{report.law_name[:55]}  |  "
            f"Match: {report.match_pct:.1f}%  |  "
            f"Coverage: {report.coverage_pct:.1f}%",
            expanded=(idx == 0)   # expand worst law by default
        ):
            # Law header
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
                <div>
                    <b>{report.law_name}</b><br>
                    <span style="color:#666;font-size:0.82rem;">
                        Law {report.law_number}/{report.year}  |
                        Magazine № {report.metadata.json_magazine}
                        {'✅' if report.metadata.match else '❌'}
                    </span>
                </div>
                <span class="verdict-badge {vc}">الحكم: {report.overall_verdict}</span>
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

            # Downloads
            paths = result["paths"]
            if paths:
                dl1, dl2, _ = st.columns([1, 1, 2])
                with dl1:
                    with open(paths["html"], "rb") as f:
                        st.download_button(
                            "📄 HTML Report", f.read(),
                            file_name=paths["html"].name,
                            mime="text/html",
                            use_container_width=True,
                            key=f"html_{idx}"
                        )
                with dl2:
                    with open(paths["excel"], "rb") as f:
                        st.download_button(
                            "📊 Excel", f.read(),
                            file_name=paths["excel"].name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key=f"excel_{idx}"
                        )

            st.markdown("---")

            # ── Article viewer ───────────────────────────────────
            st.markdown("#### 🔍 Article Comparison")

            fc1, fc2, fc3 = st.columns([2, 2, 1])
            with fc1:
                status_opts = {
                    "الكل": None,
                    "✅ تطابق":       MatchStatus.MATCH,
                    "⚠️ جزئي":        MatchStatus.NEAR_MATCH,
                    "❌ تعارض":       MatchStatus.MISMATCH,
                    "🔍 غائب":        MatchStatus.MISSING,
                    "➕ زائد":        MatchStatus.EXTRA,
                }
                sel_status = st.selectbox(
                    "تصفية:", list(status_opts.keys()),
                    key=f"filter_{idx}"
                )
                filter_status = status_opts[sel_status]

            with fc2:
                search = st.text_input(
                    "بحث برقم المادة:", placeholder="مثال: 42",
                    key=f"search_{idx}"
                )

            with fc3:
                view = st.radio(
                    "عرض:", ["↔ جانبي", "☰ قائمة"],
                    key=f"view_{idx}", horizontal=True
                )

            # Filter
            arts = report.articles
            if filter_status:
                arts = [a for a in arts if a.status == filter_status]
            if search.strip():
                arts = [a for a in arts if search.strip() in a.article_number]

            # Paginate
            PAGE = 15
            total_pages = max(1, (len(arts) + PAGE - 1) // PAGE)
            page = st.number_input(
                f"صفحة (من {total_pages}):", min_value=1,
                max_value=total_pages, value=1, key=f"page_{idx}"
            )
            page_arts = arts[(page-1)*PAGE : page*PAGE]
            st.caption(f"عرض {len(arts)} مادة")

            # Render
            if view == "↔ جانبي":
                h1c, h2c = st.columns(2)
                with h1c: st.markdown("**📘 المصدر الأول (JSON)**")
                with h2c: st.markdown("**📗 المصدر الثاني (TXT)**")
                for art in page_arts:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(render_article_card(art, "json"), unsafe_allow_html=True)
                    with c2:
                        st.markdown(render_article_card(art, "txt"),  unsafe_allow_html=True)
            else:
                for art in page_arts:
                    with st.expander(
                        f"مادة {art.article_number}  |  "
                        f"{STATUS_AR.get(art.status,'')}  |  "
                        f"{'%.0f%%' % art.similarity_score if art.similarity_score > 0 else '—'}",
                        expanded=art.status in (MatchStatus.MISMATCH, MatchStatus.NEAR_MATCH)
                    ):
                        a1, a2 = st.columns(2)
                        with a1:
                            st.markdown("**📘 JSON**")
                            st.text_area("", art.json_text or "— غير متوفر —",
                                height=140, key=f"j_{idx}_{art.article_number}", disabled=True)
                        with a2:
                            st.markdown("**📗 TXT**")
                            st.text_area("", art.txt_text or "— غير متوفر —",
                                height=140, key=f"t_{idx}_{art.article_number}", disabled=True)
                        if art.diff_hint:
                            st.caption(f"🔍 {art.diff_hint}")

else:
    # ── Empty state ──────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;padding:3rem;color:#aaa;">
        <div style="font-size:3rem">⚖️</div>
        <h3 style="color:#888">ابدأ المقارنة</h3>
        <p>ارفع ملف JSON وملفات TXT من الشريط الجانبي ثم اضغط <b>Run Batch Comparison</b></p>
        <br>
        <div style="display:inline-flex;gap:2rem;font-size:0.85rem;flex-wrap:wrap;">
            <div>📁 <b>JSON</b><br>ملف واحد يحتوي على كل القوانين</div>
            <div>📄 <b>TXT files</b><br>ملف لكل قانون (متعدد)</div>
            <div>🔗 <b>Auto-pair</b><br>ربط تلقائي عبر اسم الملف</div>
            <div>📊 <b>Sorted</b><br>الأسوأ أولاً للمراجعة</div>
        </div>
    </div>
    """, unsafe_allow_html=True)