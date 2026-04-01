from pydoc import doc
import pdfplumber, docx2python

def doc_recognizer(file):
    if file.endswith(".pdf"):
        return pdf_extractor(file)
    elif file.endswith(".doc"):
        return doc_extractor(file)
    else:
        return
    
def pdf_extractor(file):
    extracted_text = ""
    table = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            extracted_text += page.extract_text()
            if page.extract_table():
                table.extend(page.extract_table())

    return extracted_text, table




def doc_extractor(file):
    extracted_text = ""
    with docx2python(file) as docx:
        for paragraph in docx.paragraphs:
            extracted_text += paragraph
        for table in docx.tables:
            for row in table.rows:
                line = ""
                for cell in row.cells:
                    line += cell.text
                extracted_text += line + "\n"
    return extracted_text