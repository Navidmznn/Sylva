import pdfplumber 
from pathlib import Path
from extractor import doc_recognizer
from blockify import blockify_pdf, merge_blocks_by_gap, merge_small_blocks, should_use_gap_rule, get_gap_threshold
from block import Block



input_folder = Path(r"C:\Users\Navid\Downloads\Syllabi")
output_folder = input_folder / "block_outputs"
output_folder.mkdir(exist_ok=True)

for file in input_folder.iterdir():
    if file.is_file() and file.suffix.lower() == ".pdf":
        print(f"Processing: {file.name}")

        text, table = doc_recognizer(str(file))
        blocks, gaps = blockify_pdf(str(file), 60)

        gap_threshold = get_gap_threshold(gaps)
        if should_use_gap_rule(gaps):
            merge_blocks_by_gap(blocks, gap_threshold)
            min_lines = 3
        else:
            min_lines = 5

        merge_small_blocks(blocks, min_lines)

        output_file = output_folder / f"{file.stem}.txt"

        with open(output_file, "w", encoding="utf-8") as f_out:
            f_out.write(f"FILE: {file.name}\n")
            f_out.write("=" * 60 + "\n\n")

            for i, block in enumerate(blocks, start=1):
                f_out.write(f"BLOCK {i}\n")
                f_out.write("-" * 40 + "\n")
                f_out.write(block.text.strip())
                f_out.write("\n\n")