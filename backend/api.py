from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import tempfile, os, json, sqlite3, threading
from pathlib import Path
from extractor import extract_document
from scorer import score_and_size_blocks, prune_blocks_to_context_limit
from parser import word_parser
from models import SyllabusData
from constants import CONTEXT_SIZES
import logging
logging.basicConfig(level=logging.DEBUG)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

DB_FILE = "results.db"
_db_lock = threading.Lock()


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """)

init_db()


def save_result(filename: str, data: dict):
    with _db_lock:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT INTO results (filename, data) VALUES (?, ?)",
                (filename, json.dumps(data))
            )


def load_results():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT filename, data FROM results").fetchall()
    return [{"filename": row[0], "data": json.loads(row[1])} for row in rows]


@app.post("/upload")
async def upload_syllabus(file: UploadFile = File(...)):
    # Validate file type
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    content = await file.read()

    # Validate file size (20MB limit)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 20MB.")

    # Validate PDF magic bytes — first 4 bytes of every PDF are %PDF
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        blocks = extract_document(tmp_path)
        score_and_size_blocks(blocks)

        # Use the same pruning strategy as main.py for consistency
        pruned_blocks = prune_blocks_to_context_limit(blocks, CONTEXT_SIZES["fast"])
        full_text = "\n\n".join(block.text for block in pruned_blocks)
        
        raw_result = await word_parser(full_text, CONTEXT_SIZES["fast"])

        try:
            parsed_json = json.loads(raw_result)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {e}")

        try:
            validated = SyllabusData.model_validate(parsed_json)
            parsed_json = validated.model_dump()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM output failed schema validation: {e}")

        save_result(file.filename, parsed_json)
        return {"filename": file.filename, "data": parsed_json}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.get("/results")
def get_results():
    return load_results()