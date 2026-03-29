import pdfplumber 

with pdfplumber.open("As101B-Winter-2026.pdf") as pdf:
    for page in pdf.pages:
        tables = None
        text = page.extract_text()
        if page.extract_tables():
            tables = page.extract_tables()
        print(text)
        if tables:
            print(tables)
