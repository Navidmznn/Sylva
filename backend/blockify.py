import pdfplumber
from block import Block


def get_line_gaps(lines):
    gaps = []

    for i in range(len(lines) - 1):
        gap = lines[i + 1]["top"] - lines[i]["bottom"]
        gaps.append(int(gap))

    return gaps


def blockify_pdf(pdf_path, short_threshold):
    all_blocks = []
    block_number = 0
    gaps = []

    with pdfplumber.open(pdf_path) as pdf:
        # iretating through each page
        for page_index, page in enumerate(pdf.pages):
            lines = page.extract_text_lines(strip=True)
            gaps.extend(get_line_gaps(lines))
            
            i = 0
            # iretating through each line inside the page
            while i < len(lines):
                current_line = lines[i]

                # if a line is shorted than some expected short threshold
                if len(current_line["text"]) <= short_threshold:
                    temp_text = ""
                    last_short_bottom = None

                    #this loop basically writes the text ofall the short lines into a sible string, and it keeps track of the last bottom (the page position)
                    while i < len(lines) and len(lines[i]["text"]) <= short_threshold:
                        temp_text += lines[i]["text"] + "\n"
                        last_short_bottom = lines[i]["bottom"]
                        i += 1

                    # checks to see if our last iretation was still within the page if so then it is a line so it has a top position
                    if i < len(lines):
                        gap_to_next = lines[i]["top"] - last_short_bottom
                    else:
                        gap_to_next = None
                    
                    block = Block(temp_text.rstrip("\n"), block_number, gap_to_next, page_index + 1)
                    all_blocks.append(block)
                    block_number += 1

                if i < len(lines):
                    current_line = lines[i]

                    if i < len(lines) - 1:
                        gap_to_next = lines[i + 1]["top"] - current_line["bottom"]
                    else:
                        gap_to_next = None

                    block = Block(current_line["text"], block_number, gap_to_next, page_index + 1)
                    all_blocks.append(block)
                    block_number += 1
                    i += 1
    gaps = sorted(gaps)
    return all_blocks, gaps


def link_blocks(blocks):
    for i in range(len(blocks)):
        if i > 0:
            blocks[i].prev_block = blocks[i - 1]
        else:
            blocks[i].prev_block = None

        if i < len(blocks) - 1:
            blocks[i].next_block = blocks[i + 1]
        else:
            blocks[i].next_block = None


#def merge_blocks_by_gap(blocks, gap_threshold):
