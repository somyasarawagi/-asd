> **Tagore Career Institute ecosystem** (student / parent / teacher / office / director app, PTM, fees, accounts) lives in [`tagore/`](tagore/README.md) - run `python run_tagore.py demo`.

# OMR Reader – आसान OMR चेकिंग (Windows / Mac / Linux desktop app)

Scan your students' OMR sheets (many batches, many sets) → get **rank list, batch-wise results and an
Excel file** in minutes. Works offline. Your data stays on your PC.

## Start (Windows)
1. Install Python 3.10+ from python.org (tick *Add Python to PATH*) – only once.
2. Double-click **`START-OMR-READER.bat`**. The app opens in your browser (`http://127.0.0.1:5757`).
3. Click **▶ Try demo** to see everything working with sample sheets in 1 click.

Want a single `.exe` that needs no Python? Double-click `build_exe.bat` (or run the *Build Windows app*
GitHub Action) → `OMR-Reader.exe`.

Mac/Linux: `pip install -r requirements.txt && python run.py`

## 4 simple steps (the app itself guides you in Hindi + English)
| Step | What you do | Time |
|---|---|---|
| **1 Sheet Setup** | Upload *one* filled sample scan. The app finds all bubble blocks itself; you only confirm "this block = roll no / answers / set code". Press *Test read* to see green dots on the marks it read. | once per sheet type |
| **2 Exam & Key** | Name the exam, give marks (+4 / −1), subject sections (Physics 1-45…). Answer key: paste `ABCD…`, type per question, **or scan a master sheet**. Separate key for Set A/B/C/D. | 2 min |
| **3 Scan** | Type the batch name, drag-drop the scanner's images / PDFs (or a whole folder). | seconds per sheet |
| **4 Results** | Rank list, batch summary, per-question analysis, **Download Excel**. | instant |

### Answer-key problems – handled
* **Key changed after the exam?** Edit the key → every result is recalculated **instantly. No rescanning.**
* **Disputed question?** Write `(AC)` = both A and C accepted, `*` = bonus (everyone gets marks), `-` = cancelled.
* **Is my key even right?** *Question analysis* shows how many students chose each option. If most students
  chose a different option than the key, the row says **CHECK KEY**.
* **Multiple sets?** Set code is read from the sheet and the matching key is used.

### Many sheets, many batches
* Batch comes from the batch box on your sheet, or from the batch name you type while scanning.
* Doubtful sheets (unreadable roll no, faint / erased marks, cut page, duplicate roll no) are collected in
  **Needs attention** – open one, see the highlighted question on the sheet image, fix with one click.
  Sheets that cannot be read are never silently scored 0.
* Import a student list (Roll, Name, Batch) and names appear in results.
* Your OMR machine exports a CSV/Excel? Use **Import machine file** (Roll, Set, Responses / Q1..Qn).

### Scanning tips
200–300 dpi, colour or grey, JPG/PNG/TIFF/PDF. Slightly tilted or upside-down pages are fixed automatically.
Pencil or pen both work (change *Mark sensitivity* in Sheet Setup for very light pencil).

## For developers
```
omr/engine.py     bubble detection, deskew, grid grouping, mark reading (OpenCV)
omr/scoring.py    key parsing, negative marking, sections, ranks, key analysis
omr/server.py     Flask API + scan pipeline;  omr/static/index.html  the UI
omr/samplegen.py  synthetic sheet generator (tests + demo)
pytest tests
```
Data (SQLite + sheet previews) is stored in `~/OMR-Reader-Data` (override with env `OMR_DATA`).
