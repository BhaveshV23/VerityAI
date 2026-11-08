"""Format-specific extraction hidden behind one replaceable boundary."""

from io import BytesIO

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from app.documents.errors import DocumentProcessingError
from app.documents.validation import ValidatedDocument


def extract_text(document: ValidatedDocument) -> str:
    try:
        if document.extension == ".txt":
            return document.content.decode("utf-8-sig")
        if document.extension == ".pdf":
            reader = PdfReader(BytesIO(document.content), strict=False)
            if reader.is_encrypted:
                raise DocumentProcessingError("encrypted_document", "Encrypted PDFs are not supported.")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if document.extension == ".docx":
            source = Document(BytesIO(document.content))
            blocks = []
            for block in source.iter_inner_content():
                if isinstance(block, Paragraph):
                    blocks.append(block.text)
                elif isinstance(block, Table):
                    blocks.extend("\t".join(cell.text for cell in row.cells) for row in block.rows)
            return "\n".join(blocks)
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError("extraction_failed", "The document could not be read. Verify it is not damaged or encrypted.") from exc
    raise DocumentProcessingError("unsupported_format", "The document format is not supported.")
