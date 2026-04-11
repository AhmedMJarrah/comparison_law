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

from src.ingestion  import load_pair, load_json_pair
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

        # Format B fallback: law has leg_number="?" — match by year only
        for law in laws:
            if str(law.get("year", "")) == year_from_file:
                return law["index"]

        # Format B fallback 2: law has leg_number="?" and year="?"
        # Match by index position if only one law in the file
        if len(laws) == 1:
            return laws[0]["index"]

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
        if "Leg_Number" in law or "Articles" in law:
            leg_number = convert_numerals(str(law.get("Leg_Number", "?")))
            year       = convert_numerals(str(law.get("Year", "?")))
            name       = law.get("Leg_Name", "N/A")
            arts       = len(law.get("Articles", []))
        else:
            # Format B: extract from text content
            arts     = len(law)
            combined = convert_numerals(
                " ".join(str(v) for v in list(law.values())[:5])
            )
            # Search for: رقم (N) لسنة YYYY
            import re as _re_b
            mb = _re_b.search(r"\d+[)\]] \u0644\u0633\u0646\u0629 (\d{4})", combined)
            mc = _re_b.search(r"(\d{1,4})/(\d{4})", combined)
            if mc:
                leg_number = mc.group(1)
                year       = mc.group(2)
            else:
                leg_number = "?"
                year       = "?"
            name = f"Format-B Law {leg_number}/{year}"
        laws.append({
            "index":      i,
            "leg_number": leg_number,
            "year":       year,
            "name":       name,
            "articles":   arts,
            "label":      f"[{i}] Law {leg_number}/{year} — {name} ({arts} articles)",
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
for key in ["batch_results", "json_text", "laws", "pairing_summary", "mode",
            "edits_s1", "edits_s2", "editor_law_idx", "editor_art_idx",
            "editor_filter", "raw_json1_map", "raw_json2_map"]:
    if key not in st.session_state:
        st.session_state[key] = None

# Editor edits are dicts: {law_id: {article_number: edited_text}}
if st.session_state.edits_s1 is None:
    st.session_state.edits_s1 = {}
if st.session_state.edits_s2 is None:
    st.session_state.edits_s2 = {}
# Staging area: holds unsaved text per article before user clicks Save Article
# Format: {law_id: {art_num: {"s1": text, "s2": text}}}
if "staging" not in st.session_state or st.session_state.staging is None:
    st.session_state.staging = {}
if st.session_state.raw_json1_map is None:
    st.session_state.raw_json1_map = {}   # law_id → original json1 text
if st.session_state.raw_json2_map is None:
    st.session_state.raw_json2_map = {}   # law_id → original json2 text


# ── Header ───────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>⚖️ Law Comparison Pipeline</h1>
    <p>نظام مقارنة النصوص القانونية — JSON vs TXT  |  JSON vs JSON</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────
with st.sidebar:

    # ── Mode selector ────────────────────────────────────────────
    st.markdown("### ⚖️ Comparison Mode")
    mode = st.radio(
        "Select source 2 type:",
        ["📄 JSON vs TXT", "📋 JSON vs JSON"],
        index=1,
        key="mode_selector",
        horizontal=False,
    )
    st.session_state.mode = mode
    is_json_mode = (mode == "📋 JSON vs JSON")

    st.markdown("---")
    st.markdown("### 📁 Upload Files")

    # ── Source 1: always a JSON (Format A) ──────────────────────
    json_file = st.file_uploader(
        "Source 1 — JSON (Format A, contains all laws)",
        type=["json"], key="json_upload"
    )

    # ── Source 2: TXT or JSON depending on mode ──────────────────
    if is_json_mode:
        json2_files = st.file_uploader(
            "Source 2 — JSON files (Format B, one per law)",
            type=["json"], accept_multiple_files=True, key="json2_upload"
        )
        txt_files = []
    else:
        txt_files = st.file_uploader(
            "Source 2 — TXT files (one per law, multiple allowed)",
            type=["txt"], accept_multiple_files=True, key="txt_upload"
        )
        json2_files = []

    # ── Parse Source 1 and preview pairing ──────────────────────
    pairing = []
    source2_files = json2_files if is_json_mode else txt_files
    source2_ext   = ".json"     if is_json_mode else ".txt"

    if json_file and source2_files:
        try:
            json_text = read_bytes(json_file)
            st.session_state.json_text = json_text
            laws = list_laws(json_text)
            st.session_state.laws = laws
            st.success(f"✓ JSON: {len(laws)} laws found")

            st.markdown("---")
            st.markdown("### 🔗 Auto-pairing preview")

            used_indices = set()
            for sf in source2_files:
                idx = parse_law_index_from_filename(sf.name, laws)
                if idx is None:
                    pairing.append({
                        "file_name":  sf.name,
                        "law_index":  None,
                        "law_name":   "❌ No match found",
                        "status":     "error",
                        "is_json":    is_json_mode,
                    })
                elif idx in used_indices:
                    pairing.append({
                        "file_name":  sf.name,
                        "law_index":  idx,
                        "law_name":   laws[idx]["name"],
                        "status":     "duplicate",
                        "is_json":    is_json_mode,
                    })
                else:
                    used_indices.add(idx)
                    pairing.append({
                        "file_name":  sf.name,
                        "law_index":  idx,
                        "law_name":   laws[idx]["name"],
                        "status":     "ok",
                        "is_json":    is_json_mode,
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
                mode_icon  = "📋" if is_json_mode else "📄"
                st.markdown(
                    f'<span class="pair-chip {chip_class}">{icon} {mode_icon} {short_name}</span>',
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
            hint = "Now upload JSON files (Format B) ↑" if is_json_mode else "Now upload TXT files ↑"
            st.info(hint)
        except Exception as e:
            st.error(f"JSON error: {e}")

    st.markdown("---")
    st.markdown("### ⚙️ Settings")
    sim_threshold   = st.slider("Match threshold (%)",      70, 100, 95)
    fuzzy_threshold = st.slider("Near-match threshold (%)", 50, 95,  80)
    st.markdown("---")

    ready = (json_file and source2_files and
             st.session_state.pairing_summary and
             any(p["status"] == "ok" for p in
                 (st.session_state.pairing_summary or [])))

    btn_label = "🚀 Run JSON vs JSON" if is_json_mode else "🚀 Run Batch Comparison"
    run_btn = st.button(
        btn_label,
        type="primary",
        use_container_width=True,
        disabled=not ready
    )
# ── Run batch pipeline ───────────────────────────────────────────
if run_btn and ready:

    pairing      = st.session_state.pairing_summary
    json_text    = st.session_state.json_text
    laws         = st.session_state.laws
    valid_pairs  = [p for p in pairing if p["status"] == "ok"]
    is_json_mode = st.session_state.get("mode") == "📋 JSON vs JSON"

    # Write Source 1 JSON to temp file once
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as jf:
        jf.write(json_text)
        json_tmp = jf.name

    st.session_state.batch_results = []
    progress_bar  = st.progress(0, text="Starting comparison...")
    status_area   = st.empty()
    batch_results = []

    # Build lookup: filename → uploaded file object
    if is_json_mode:
        file_lookup = {sf.name: sf for sf in json2_files}
    else:
        file_lookup = {sf.name: sf for sf in txt_files}

    for i, pair_info in enumerate(valid_pairs):
        pct = int((i / len(valid_pairs)) * 100)
        law_name_short = pair_info["law_name"][:40]
        progress_bar.progress(pct, text=f"[{i+1}/{len(valid_pairs)}] {law_name_short}...")
        status_area.info(f"⚙️ Comparing: {law_name_short}")

        try:
            src2_file_obj = file_lookup[pair_info["file_name"]]
            src2_text     = read_bytes(src2_file_obj)

            # Apply thresholds
            from src import config as cfg_mod
            cfg_mod.config.SIMILARITY_THRESHOLD  = sim_threshold
            cfg_mod.config.FUZZY_MATCH_THRESHOLD = fuzzy_threshold

            if is_json_mode:
                # ── JSON vs JSON mode ────────────────────────────
                # Write Source 2 JSON to temp file
                with tempfile.NamedTemporaryFile(
                    suffix=".json", delete=False, mode="w", encoding="utf-8"
                ) as j2f:
                    j2f.write(src2_text)
                    json2_tmp = j2f.name

                pair_obj = load_json_pair(
                    json_tmp, json2_tmp,
                    law1_index=pair_info["law_index"]
                )
                extracted = pair_obj._extracted
                os.unlink(json2_tmp)

            else:
                # ── JSON vs TXT mode (existing workflow) ─────────
                with tempfile.NamedTemporaryFile(
                    suffix=".txt", delete=False, mode="w", encoding="utf-8"
                ) as tf:
                    tf.write(src2_text)
                    txt_tmp = tf.name

                pair_obj  = load_pair(json_tmp, txt_tmp, law_index=pair_info["law_index"])
                extracted = extract(src2_text)
                os.unlink(txt_tmp)

            report = compare(pair_obj.source1, extracted, pair_obj.law_id)
            paths  = generate_report(report)

            batch_results.append({
                "report":    report,
                "paths":     paths,
                "file_name": pair_info["file_name"],
                "is_json":   is_json_mode,
                "status":    "success",
            })

        except Exception as e:
            batch_results.append({
                "report":    None,
                "paths":     None,
                "file_name": pair_info["file_name"],
                "law_name":  pair_info["law_name"],
                "is_json":   is_json_mode,
                "status":    "failed",
                "error":     str(e),
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

    # Store raw JSON texts for editor (needed to rebuild JSON on save)
    # key = law_id, value = original raw JSON text
    raw_j1 = {}
    raw_j2 = {}
    for r in batch_results:
        if r["status"] == "success":
            lid = r["report"].law_id
            raw_j1[lid] = json_text   # Source 1 always same JSON
    st.session_state.raw_json1_map = raw_j1
    st.session_state.raw_json2_map = raw_j2

    ok_count = len([r for r in batch_results if r["status"] == "success"])
    mode_label = "JSON vs JSON" if is_json_mode else "JSON vs TXT"
    st.success(f"✅ {mode_label} complete — {ok_count} laws compared!")
# ── Display results ──────────────────────────────────────────────
batch_results = st.session_state.batch_results

if batch_results:
    tab_results, tab_editor = st.tabs(["📊 Results", "✏️ Article Editor"])
else:
    tab_results = None
    tab_editor  = None

if batch_results and tab_results:
  with tab_results:
   if True:

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

        mode_used = st.session_state.get("mode", "📄 JSON vs TXT")
        mode_badge = "📋 JSON vs JSON" if "JSON vs JSON" in mode_used else "📄 JSON vs TXT"
        st.caption(f"Mode: {mode_badge} — ⬇️ sorted by match rate (worst first)")
        st.markdown("---")

        # ── Failed runs ──────────────────────────────────────────────
        if failed:
            with st.expander(f"⚠️ {len(failed)} law(s) failed — click to see errors"):
                for r in failed:
                    st.error(f"**{r.get('law_name', r.get('file_name','?'))}** — {r['error']}")

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


# ── Article Editor tab ────────────────────────────────────────
if batch_results and tab_editor:
  with tab_editor:

    STATUS_LABELS_EDITOR = {
        "MATCH":      "✅ Match",
        "NEAR_MATCH": "⚠️ Near Match",
        "MISMATCH":   "❌ Mismatch",
        "MISSING":    "🔍 Missing",
        "EXTRA":      "➕ Extra",
    }

    successful_results = [r for r in batch_results if r["status"] == "success"]

    if not successful_results:
        st.info("No successful comparisons to edit.")
    else:
        # ── Initialize edits for all laws ────────────────────────
        for res in successful_results:
            lid = res["report"].law_id
            if lid not in st.session_state.edits_s1:
                st.session_state.edits_s1[lid] = {}
            if lid not in st.session_state.edits_s2:
                st.session_state.edits_s2[lid] = {}

        # ── Filter control ───────────────────────────────────────
        fcol1, fcol2, fcol3 = st.columns([3, 2, 2])
        with fcol1:
            filter_opts = {
                "All articles":       None,
                "❌ Mismatch only":   "MISMATCH",
                "⚠️ Near Match only": "NEAR_MATCH",
                "🔍 Missing only":    "MISSING",
                "➕ Extra only":      "EXTRA",
                "✅ Match only":      "MATCH",
            }
            selected_filter = st.selectbox(
                "Filter:", list(filter_opts.keys()),
                key="editor_filter_select"
            )
            filter_status = filter_opts[selected_filter]

        # ── Build flat navigation list across ALL laws ────────────
        # Each entry: (law_id, law_name, law_num, law_year, article)
        flat_list = []
        for res in successful_results:
            rpt = res["report"]
            for art in rpt.articles:
                if filter_status is None or art.status.value == filter_status:
                    flat_list.append((
                        rpt.law_id,
                        rpt.law_name,
                        rpt.law_number,
                        rpt.year,
                        art,
                    ))

        total = len(flat_list)

        with fcol2:
            st.metric("Total articles in view", total)

        # Total unsaved edits across all laws
        all_edits_count = sum(
            len(st.session_state.edits_s1.get(r["report"].law_id, {})) +
            len(st.session_state.edits_s2.get(r["report"].law_id, {}))
            for r in successful_results
        )
        with fcol3:
            if all_edits_count > 0:
                st.markdown(
                    f'<div style="padding:8px 12px;background:var(--color-background-warning);'
                    f'border-radius:var(--border-radius-md);font-size:12px;'
                    f'color:var(--color-text-warning);text-align:center;margin-top:6px">'
                    f'🟡 {all_edits_count} unsaved edits</div>',
                    unsafe_allow_html=True
                )

        if not flat_list:
            st.info(f"No articles match the selected filter.")
        else:
            # ── Navigation bar ────────────────────────────────────
            st.markdown("---")
            nav1, nav2, nav3, nav4, nav5 = st.columns([1, 1, 3, 2, 1])

            # Clamp index
            if "ed_idx" not in st.session_state or st.session_state.ed_idx is None:
                st.session_state.ed_idx = 0
            ed_idx = max(0, min(int(st.session_state.ed_idx), total - 1))

            with nav1:
                if st.button("⏮ First", key="ed_first", use_container_width=True):
                    st.session_state.ed_idx = 0
                    st.rerun()

            with nav2:
                if st.button("← Prev", key="ed_prev", use_container_width=True):
                    st.session_state.ed_idx = max(0, ed_idx - 1)
                    st.rerun()

            with nav3:
                st.markdown(
                    f'<div style="text-align:center;padding:6px;font-size:13px;">'
                    f'Article <strong>{ed_idx + 1}</strong> of <strong>{total}</strong>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            with nav4:
                jump = st.text_input(
                    "Jump to:", key="ed_jump",
                    placeholder="article number",
                    label_visibility="collapsed"
                )
                if jump.strip():
                    # Find first match in flat list
                    for fi, (_, _, _, _, fa) in enumerate(flat_list):
                        if fa.article_number == jump.strip():
                            st.session_state.ed_idx = fi
                            st.rerun()
                            break

            with nav5:
                if st.button("Next →", key="ed_next", use_container_width=True):
                    st.session_state.ed_idx = min(total - 1, ed_idx + 1)
                    st.rerun()

            # ── Current article ───────────────────────────────────
            law_id, law_name, law_num, law_year, art = flat_list[ed_idx]
            art_num      = art.article_number
            edits_s1     = st.session_state.edits_s1[law_id]
            edits_s2     = st.session_state.edits_s2[law_id]
            s1_edited    = art_num in edits_s1
            s2_edited    = art_num in edits_s2
            edit_dot     = " 🟡" if (s1_edited or s2_edited) else ""

            badge_colors = {
                "MATCH":      ("#d4edda", "#155724"),
                "NEAR_MATCH": ("#fff3cd", "#856404"),
                "MISMATCH":   ("#f8d7da", "#721c24"),
                "MISSING":    ("#e2e3e5", "#383d41"),
                "EXTRA":      ("#d1ecf1", "#0c5460"),
            }
            bg_c, txt_c = badge_colors.get(art.status.value, ("#e2e3e5", "#383d41"))
            status_label = STATUS_LABELS_EDITOR.get(art.status.value, art.status.value)
            score_txt    = f"Score: {art.similarity_score:.0f}%" if art.similarity_score > 0 else ""

            # Law + article header
            st.markdown(
                f'<div style="background:var(--color-background-secondary);'
                f'border-radius:var(--border-radius-md);padding:10px 14px;'
                f'margin-bottom:12px;border:0.5px solid var(--color-border-tertiary)">'
                f'<div style="font-size:11px;color:var(--color-text-secondary);margin-bottom:4px">'
                f'📚 {law_name or "Law"} — {law_num}/{law_year}</div>'
                f'<div style="display:flex;align-items:center;gap:10px;">'
                f'<span style="font-size:1.05rem;font-weight:500">المادة {art_num}{edit_dot}</span>'
                f'<span style="background:{bg_c};color:{txt_c};padding:2px 10px;'
                f'border-radius:10px;font-size:12px;font-weight:500">{status_label}</span>'
                + (f'<span style="font-size:12px;color:var(--color-text-secondary)">{score_txt}</span>'
                   if score_txt else "")
                + f'</div></div>',
                unsafe_allow_html=True
            )

            # ── View mode toggle ──────────────────────────────────
            view_mode = st.radio(
                "View mode:",
                ["👁 Diff View", "✏️ Edit View"],
                index=0,
                horizontal=True,
                key=f"view_mode_{law_id}_{art_num}"
            )

            s1_original = art.json_text or ""
            s2_original = art.txt_text  or ""
            s1_current  = edits_s1.get(art_num, s1_original)
            s2_current  = edits_s2.get(art_num, s2_original)

            if view_mode == "👁 Diff View":
                # ── Character-level diff ──────────────────────────
                import difflib, html as _html

                def build_diff_html(text_a: str, text_b: str):
                    """
                    Returns (html_a, html_b) with character-level highlights.
                    text_a extra chars → red background in html_a
                    text_b extra chars → green background in html_b
                    """
                    matcher = difflib.SequenceMatcher(
                        None, text_a, text_b, autojunk=False
                    )
                    html_a = ""
                    html_b = ""
                    for op, i1, i2, j1, j2 in matcher.get_opcodes():
                        ca = _html.escape(text_a[i1:i2])
                        cb = _html.escape(text_b[j1:j2])
                        if op == "equal":
                            html_a += ca
                            html_b += cb
                        elif op == "delete":
                            # In S1 but not S2 → red in S1
                            html_a += (
                                f'<mark style="background:#f8d7da;color:#721c24;'
                                f'border-radius:2px;padding:0 1px">{ca}</mark>'
                            )
                        elif op == "insert":
                            # In S2 but not S1 → green in S2
                            html_b += (
                                f'<mark style="background:#d4edda;color:#155724;'
                                f'border-radius:2px;padding:0 1px">{cb}</mark>'
                            )
                        elif op == "replace":
                            # Different on both sides
                            html_a += (
                                f'<mark style="background:#f8d7da;color:#721c24;'
                                f'border-radius:2px;padding:0 1px">{ca}</mark>'
                            )
                            html_b += (
                                f'<mark style="background:#d4edda;color:#155724;'
                                f'border-radius:2px;padding:0 1px">{cb}</mark>'
                            )
                    return html_a, html_b

                html_s1, html_s2 = build_diff_html(s1_current, s2_current)

                # Legend
                st.markdown(
                    '<div style="display:flex;gap:16px;margin-bottom:8px;font-size:12px">' +
                    '<span><mark style="background:#f8d7da;color:#721c24;padding:1px 6px;border-radius:3px">■</mark> في قسطاس فقط</span>' +
                    '<span><mark style="background:#d4edda;color:#155724;padding:1px 6px;border-radius:3px">■</mark> في الجريدة الرسمية فقط</span>' +
                    '</div>',
                    unsafe_allow_html=True
                )

                col_d1, col_d2 = st.columns(2)

                diff_style = (
                    "background:var(--color-background-secondary);"
                    "border:0.5px solid var(--color-border-tertiary);"
                    "border-radius:var(--border-radius-md);"
                    "padding:12px 14px;"
                    "font-size:13px;"
                    "line-height:1.9;"
                    "direction:rtl;"
                    "text-align:right;"
                    "min-height:300px;"
                    "white-space:pre-wrap;"
                    "word-break:break-word;"
                )

                with col_d1:
                    st.markdown("**📘 قسطاس**")
                    st.markdown(
                        f'<div style="{diff_style}">{html_s1}</div>',
                        unsafe_allow_html=True
                    )

                with col_d2:
                    st.markdown("**📗 الجريدة الرسمية**")
                    st.markdown(
                        f'<div style="{diff_style}">{html_s2}</div>',
                        unsafe_allow_html=True
                    )

            else:
                # ── Edit View (auto-save) ──────────────────────────
                # Every keystroke is saved automatically to session_state.
                # No manual "Save Article" needed — just edit freely.
                # The "Save File" button at the bottom downloads the result.
                col_s1, col_s2 = st.columns(2)

                with col_s1:
                    st.markdown("**📘 قسطاس**")
                    s1_new = st.text_area(
                        label="s1",
                        value=s1_current,
                        height=300,
                        key=f"ta_s1_{law_id}_{art_num}",
                        label_visibility="collapsed"
                    )
                    # Auto-save: commit to edits on every change
                    if s1_new != s1_original:
                        st.session_state.edits_s1[law_id][art_num] = s1_new
                    elif art_num in st.session_state.edits_s1[law_id]:
                        del st.session_state.edits_s1[law_id][art_num]

                with col_s2:
                    st.markdown("**📗 الجريدة الرسمية**")
                    s2_new = st.text_area(
                        label="s2",
                        value=s2_current,
                        height=300,
                        key=f"ta_s2_{law_id}_{art_num}",
                        label_visibility="collapsed"
                    )
                    # Auto-save: commit to edits on every change
                    if s2_new != s2_original:
                        st.session_state.edits_s2[law_id][art_num] = s2_new
                    elif art_num in st.session_state.edits_s2[law_id]:
                        del st.session_state.edits_s2[law_id][art_num]

                # ── Change notification bar ────────────────────────
                s1_modified = s1_new != s1_original
                s2_modified = s2_new != s2_original

                if s1_modified or s2_modified:
                    changed_sides = []
                    if s1_modified: changed_sides.append("قسطاس")
                    if s2_modified: changed_sides.append("الجريدة الرسمية")
                    st.markdown(
                        f'<div style="background:var(--color-background-warning);'
                        f'border-radius:var(--border-radius-md);padding:8px 14px;'
                        f'font-size:13px;color:var(--color-text-warning);margin-top:6px">'
                        f'🟡 تم تعديل المادة {art_num} في: {" و ".join(changed_sides)} — '
                        f'سيتم تضمين التعديل تلقائياً عند حفظ الملف</div>',
                        unsafe_allow_html=True
                    )
                elif s1_edited or s2_edited:
                    st.markdown(
                        f'<div style="background:var(--color-background-success);'
                        f'border-radius:var(--border-radius-md);padding:8px 14px;'
                        f'font-size:13px;color:var(--color-text-success);margin-top:6px">'
                        f'✅ المادة {art_num} معدّلة ومحفوظة — اضغط حفظ الملف للتنزيل</div>',
                        unsafe_allow_html=True
                    )

            # ── Save File bar (bottom) ────────────────────────────
            st.markdown("---")

            def build_edited_json(original_json_text, edits, is_source1=True):
                import json as _j
                data = _j.loads(original_json_text)
                check = data[0] if isinstance(data, list) else data
                keys  = list(check.keys()) if isinstance(check, dict) else []
                is_fmt_b = len(keys) > 0 and all(
                    str(k).strip().isdigit() for k in keys[:10]
                )
                if is_fmt_b:
                    for num, txt in edits.items():
                        if num in data:
                            data[num] = txt
                    return _j.dumps(data, ensure_ascii=False, indent=4)
                else:
                    law_data = data if not isinstance(data, list) else data[0]
                    for a in law_data.get("Articles", []):
                        num = str(a.get("article_number", ""))
                        if num in edits:
                            a["text"] = edits[num]
                    if isinstance(data, list):
                        data[0] = law_data
                    return _j.dumps(data, ensure_ascii=False, indent=4)

            s1_law_edits  = st.session_state.edits_s1.get(law_id, {})
            s2_law_edits  = st.session_state.edits_s2.get(law_id, {})
            raw_j1        = st.session_state.raw_json1_map.get(law_id, "{}")
            total_s1_edits = len(s1_law_edits)
            total_s2_edits = len(s2_law_edits)
            total_all      = total_s1_edits + total_s2_edits

            # Summary line
            if total_all > 0:
                st.markdown(
                    f'<div style="background:var(--color-background-info);'
                    f'border-radius:var(--border-radius-md);padding:8px 14px;'
                    f'font-size:13px;color:var(--color-text-info);margin-bottom:10px">'
                    f'📋 {total_all} تعديل محفوظ لـ {law_name or law_id} — '
                    f'قسطاس: {total_s1_edits} | الجريدة الرسمية: {total_s2_edits}'
                    f'</div>',
                    unsafe_allow_html=True
                )
            else:
                st.caption("لا توجد تعديلات بعد — عدّل النصوص وسيتم حفظها تلقائياً")

            sv1, sv2, sv3 = st.columns([3, 3, 1])

            with sv1:
                if total_s1_edits > 0:
                    try:
                        out = build_edited_json(raw_j1, s1_law_edits, is_source1=True)
                        st.download_button(
                            f"📥 حفظ ملف قسطاس ({total_s1_edits} مادة معدّلة)",
                            data=out.encode("utf-8"),
                            file_name=f"edited_s1_{law_id}.json",
                            mime="application/json",
                            use_container_width=True,
                            type="primary",
                            key=f"dl_s1_{law_id}"
                        )
                    except Exception as e:
                        st.error(f"Error building file: {e}")
                else:
                    st.button(
                        "📥 حفظ ملف قسطاس",
                        disabled=True,
                        use_container_width=True,
                        key=f"dl_s1_disabled_{law_id}",
                        help="لا توجد تعديلات محفوظة لقسطاس بعد"
                    )

            with sv2:
                if total_s2_edits > 0:
                    import json as _j2
                    s2_out = {}
                    for res in successful_results:
                        if res["report"].law_id == law_id:
                            for a in res["report"].articles:
                                txt = s2_law_edits.get(
                                    a.article_number, a.txt_text or ""
                                )
                                if txt:
                                    s2_out[a.article_number] = txt
                    out2 = _j2.dumps(s2_out, ensure_ascii=False, indent=4)
                    st.download_button(
                        f"📥 حفظ ملف الجريدة الرسمية ({total_s2_edits} مادة معدّلة)",
                        data=out2.encode("utf-8"),
                        file_name=f"edited_s2_{law_id}.json",
                        mime="application/json",
                        use_container_width=True,
                        type="primary",
                        key=f"dl_s2_{law_id}"
                    )
                else:
                    st.button(
                        "📥 حفظ ملف الجريدة الرسمية",
                        disabled=True,
                        use_container_width=True,
                        key=f"dl_s2_disabled_{law_id}",
                        help="لا توجد تعديلات محفوظة للجريدة الرسمية بعد"
                    )

            with sv3:
                if total_all > 0:
                    if st.button(
                        "↩ إعادة تعيين الكل",
                        use_container_width=True,
                        key=f"rst_law_{law_id}"
                    ):
                        st.session_state.edits_s1[law_id] = {}
                        st.session_state.edits_s2[law_id] = {}
                        st.session_state.staging[law_id]  = {}
                        st.rerun()
