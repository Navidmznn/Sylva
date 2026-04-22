import time
from parser import word_parser
from scorer import score_and_size_blocks, prune_blocks_to_context_limit
from extractor import extract_document
from constants import CONTEXT_SIZES

file = r"C:\Users\Navid\Downloads\Syllabi\MA238 W26 Course Outline - MA-238-A - Discrete Mathematics.pdf"

t = time.time()
blocks = extract_document(file)
print(f"extract_document: {time.time() - t:.2f}s")

t = time.time()
score_and_size_blocks(blocks)
print(f"score_and_size_blocks: {time.time() - t:.2f}s")

t = time.time()
pruned_blocks = prune_blocks_to_context_limit(blocks, CONTEXT_SIZES["fast"])
print(f"prune_blocks: {time.time() - t:.2f}s")

full_text = "\n\n".join(block.text for block in pruned_blocks)

t = time.time()
result = word_parser(full_text, CONTEXT_SIZES["fast"])
print(f"word_parser: {time.time() - t:.2f}s")
