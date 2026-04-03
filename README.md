# ⚖️ Law Comparison Pipeline

**Arabic Legal Text Comparison System** — compares structured JSON law sources against OCR-extracted TXT files, producing professional HTML and Excel reports.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://your-app.streamlit.app)

---

## 🚀 Quick Start

```bash
# Clone and setup
git clone https://github.com/YOUR_USERNAME/comparison_law.git
cd comparison_law
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # Mac/Linux
pip install -r requirements.txt

# Copy environment config
cp .env.example .env

# Run Streamlit app
streamlit run app.py

# OR use CLI directly
python main.py --list data\source1\laws.json
python main.py --json data\source1\laws.json --txt data\source2\law.txt --law-index 0
```

---

## 📁 Project Structure

```
comparison_law/
├── app.py              ← Streamlit web interface
├── main.py             ← CLI entrypoint
├── requirements.txt    ← Dependencies
├── .env.example        ← Config template
├── .streamlit/
│   └── config.toml     ← Streamlit theme settings
└── src/
    ├── config.py       ← Environment config loader
    ├── normalizer.py   ← Arabic text normalization
    ├── ingestion.py    ← File loading & validation
    ├── extractor.py    ← TXT article extraction
    ├── comparator.py   ← Similarity scoring
    ├── reporter.py     ← HTML + Excel output
    └── diagnose.py     ← Gap analysis tool
```

---

## 🌐 Streamlit Cloud Deployment

1. Fork this repository to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click **Create app** → **Yup, I have an app**
4. Set: Repository = `your-username/comparison_law`, Branch = `main`, File = `app.py`
5. Click **Deploy**

Your app will be live at `https://your-app.streamlit.app` within minutes.

---

## 📊 What It Does

| Stage | Module | Input → Output |
|-------|--------|----------------|
| 1. Normalize | `normalizer.py` | Raw Arabic text → cleaned text |
| 2. Ingest | `ingestion.py` | JSON + TXT files → validated pair |
| 3. Extract | `extractor.py` | Raw TXT → structured articles |
| 4. Compare | `comparator.py` | Article pairs → similarity scores |
| 5. Report | `reporter.py` | Scores → HTML + Excel reports |

### Match Status Legend
| Status | Meaning | Threshold |
|--------|---------|-----------|
| ✅ Match | Articles are identical | ≥ 95% |
| ⚠️ Near Match | Minor differences | ≥ 80% |
| ❌ Mismatch | Significant differences | < 80% |
| 🔍 Missing | In JSON, not in TXT | — |
| ➕ Extra | In TXT, not in JSON | — |

---

## 🛠️ Tech Stack

- **Python 3.12** — Core pipeline
- **rapidfuzz** — Text similarity scoring
- **pyarabic** — Arabic NLP utilities
- **streamlit** — Web interface
- **pandas + openpyxl** — Excel generation
- **jinja2** — HTML report templating
- **python-dotenv** — Environment management

---

## 📄 License

Internal use. See LICENSE for details.