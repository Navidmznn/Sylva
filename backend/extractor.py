from block import Block
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.document import DocItemLabel
import torch


pdf_options = PdfPipelineOptions()

device = AcceleratorDevice.CUDA if torch.cuda.is_available() else AcceleratorDevice.CPU
pdf_options.accelerator_options = AcceleratorOptions(
    device=device,
    num_threads=8   
)

pdf_options.do_ocr = True
pdf_options.do_picture_description = False
pdf_options.do_picture_classification = False
pdf_options.generate_page_images = False
pdf_options.generate_picture_images = False

use_gpu = torch.cuda.is_available()
pdf_options.ocr_options = EasyOcrOptions(
    use_gpu=use_gpu,
    force_full_page_ocr=True,
    lang=["en"]
)

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)
    }
)


def extract_document(file):
    result = converter.convert(file)
    doc = result.document

    blocks = []

    for item, _ in doc.iterate_items():
        if item.label == DocItemLabel.TABLE:
            text = extract_table_as_text(item).strip()
            if text:
                blocks.append(Block(text, True))
        else:
            text = getattr(item, 'text', '').strip()
            if text:
                blocks.append(Block(text, False))

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return blocks

def extract_table_as_text(table_item):
    cells = table_item.data.table_cells
    num_rows = table_item.data.num_rows
    num_cols = table_item.data.num_cols

    grid = [[""] * num_cols for _ in range(num_rows)]
    for cell in cells:
        r = cell.start_row_offset_idx
        c = cell.start_col_offset_idx
        grid[r][c] = cell.text.strip()

    rows = []
    for row in grid:
        rows.append(" | ".join(row))
    return "\n".join(rows)