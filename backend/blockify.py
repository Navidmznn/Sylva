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
                        gap_to_next = int(lines[i]["top"] - last_short_bottom)
                    else:
                        gap_to_next = None
                    
                    block = Block(temp_text.rstrip("\n"), block_number, gap_to_next, page_index + 1)
                    all_blocks.append(block)
                    block_number += 1

                if i < len(lines):
                    current_line = lines[i]

                    if i < len(lines) - 1:
                        gap_to_next = int(lines[i + 1]["top"] - current_line["bottom"])
                    else:
                        gap_to_next = None

                    block = Block(current_line["text"], block_number, gap_to_next, page_index + 1)
                    all_blocks.append(block)
                    block_number += 1
                    i += 1
    
    link_blocks(all_blocks)
    return all_blocks, gaps


def get_gap_threshold(gaps):
    if not gaps:
        return None

    gaps = sorted(gaps)
    n = len(gaps)
    midpoint = n // 2

    if n % 2 == 1:
        median = gaps[midpoint]
    else:
        median = (gaps[midpoint - 1] + gaps[midpoint]) / 2

    gap_threshold = max(4, int(median) + 1)
    return gap_threshold



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



def merge_blocks_by_gap(blocks, gap_threshold):
    if not blocks:
        return
    
    current = blocks[0]

    while current is not None:

        if current.gap_to_next is not None and current.gap_to_next <= gap_threshold:
            merged_block = current.next_block
            current.merge(merged_block)
            blocks.remove(merged_block)

        else:
            current = current.next_block



def merge_small_blocks(blocks, min_lines):
    if not blocks:
        return
    
    current = blocks[0]

    while current is not None:
        if current.next_block is not None and len(current.lines) < min_lines:
            merged_block = current.next_block
            current.merge(merged_block)
            blocks.remove(merged_block)
        else:
            current = current.next_block


def should_use_gap_rule(gaps):
    if not gaps:
        return False

    most_common_count = 0

    for gap in gaps:
        count = gaps.count(gap)
        if count > most_common_count:
            most_common_count = count

    return most_common_count / len(gaps) < 0.90