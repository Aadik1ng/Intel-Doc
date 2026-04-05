import fitz  # PyMuPDF
import docx
from pathlib import Path

def parse_document(file_path: str, filename: str):
    path = Path(file_path)
    file_type = path.suffix.lower().replace(".", "")
    text = ""
    pages_text = []

    if file_type == "pdf":
        doc = fitz.open(file_path)
        for page_num in range(len(doc)):
            page_text = doc[page_num].get_text()
            text += page_text
            pages_text.append({"page": page_num + 1, "text": page_text})
        doc.close()
    elif file_type == "docx":
        doc = docx.Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
        pages_text.append({"page": 1, "text": text})
    elif file_type == "txt":
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        pages_text.append({"page": 1, "text": text})
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    return {
        "text": text,
        "pages": pages_text,
        "metadata": {
            "filename": filename,
            "file_type": file_type,
            "size_bytes": path.stat().st_size
        }
    }
