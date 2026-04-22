from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import tempfile, os, json
from pathlib import Path
from extractor import extract_document
from scorer import score_and_size_blocks
from parser import word_parser
from constants import CONTEXT_SIZES

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

STORE_FILE = Path("results.json")

def load_store():
    if STORE_FILE.exists():
        with open(STORE_FILE, "r") as f:
            return json.load(f)
    return []

def save_store(store):
    with open(STORE_FILE, "w") as f:
        json.dump(store, f)

results_store = load_store()

@app.post("/upload")
async def upload_syllabus(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        blocks = extract_document(tmp_path)
        score_and_size_blocks(blocks)

        pruned_blocks = []
        for block in blocks:
            if block.is_table or block.importance_score >= 3:
                pruned_blocks.append(block)

        text_parts = []
        for block in pruned_blocks:
            text_parts.append(block.text)
        full_text = "\n\n".join(text_parts)

        result = word_parser(full_text, CONTEXT_SIZES["balanced"])
        parsed = json.loads(result)

        entry = {"filename": file.filename, "data": parsed}
        results_store.append(entry)
        save_store(results_store)

        return entry
    finally:
        os.unlink(tmp_path)

@app.get("/results")
def get_results():
    return results_store