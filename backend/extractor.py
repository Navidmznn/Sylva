import pdfplumber, docx2python

def doc_recognizer(file):
    if file.endswith(".pdf"):
        pdf_extractor(file)
    elif file.endswith(".doc"):
        doc_extractor(file)
    else:
        return
    
def pdf_extractor():
    return
def doc_extractor():
    return