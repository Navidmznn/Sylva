import pdfplumber 
from extractor import doc_recognizer
from parser import word_parser
from blockify import blockify_pdf, merge_blocks_by_gap, merge_small_blocks, should_use_gap_rule, get_gap_threshold
from scorer import score_and_size_blocks
from block import Block

file = r"C:\Users\Navid\Downloads\Syllabi\PSYC221 (ASO) Fall 2025 Syllabus.pdf"


text, table = doc_recognizer(file)
list, gaps = blockify_pdf(file, 60)
gap_threshold = get_gap_threshold(gaps)
if should_use_gap_rule(gaps):
    merge_blocks_by_gap(list, gap_threshold)
    min_lines = 3
else:
    min_lines = 5
merge_small_blocks(list, min_lines)


for block in list:
    print('------------------')
    print(block.text)

print(len(list))