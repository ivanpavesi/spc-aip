"""Servizio di caricamento, estrazione e indicizzazione di documenti e trascrizioni (STEP 6 & 7)."""

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_text_from_file(filename: str, content_bytes: bytes) -> str:
    """Estrae testo da file .txt, .pdf, .docx in modo sicuro e protetto."""
    clean_filename = filename.lower()

    if clean_filename.endswith(".txt"):
        try:
            return content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return content_bytes.decode("latin-1", errors="replace")

    elif clean_filename.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content_bytes))
            pages_text = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
            return "\n\n".join(pages_text)
        except Exception as exc:
            logger.error(f"Errore estrazione PDF: {exc}")
            raise ValueError(f"Impossibile leggere il file PDF: {exc}") from exc

    elif clean_filename.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(content_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text]
            return "\n\n".join(paragraphs)
        except Exception as exc:
            logger.error(f"Errore estrazione DOCX: {exc}")
            raise ValueError(f"Impossibile leggere il file DOCX: {exc}") from exc

    else:
        raise ValueError("Formato file non supportato. Formati ammessi: .txt, .pdf, .docx")
