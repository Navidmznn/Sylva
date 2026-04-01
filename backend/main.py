import pdfplumber 
from extractor import doc_recognizer
from parser import word_parser
from blockify import blockify_pdf
from block import Block

file = r"C:\Users\Navid\Downloads\Syllabi\2310 Syllabus Social Psychology F25 REV.pdf"


text, table = doc_recognizer(file)
list, gaps = blockify_pdf(file, 60)

for block in list:
    print('------------------')
    print(block.text)

print("\nGaps:")
for gap in gaps:
    print(gap)

midpoint = int(len(list)/2)
print(f" The median is {gaps[midpoint]}")