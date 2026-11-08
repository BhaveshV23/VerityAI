"""File-name, size, signature, and content validation."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import zipfile

from app.documents.errors import DocumentInputError


@dataclass(frozen=True, slots=True)
class ValidatedDocument:
    original_filename: str
    extension: str
    detected_content_type: str
    byte_size: int
    content: bytes


_CONTENT_TYPES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain; charset=utf-8"}


def safe_original_filename(filename: str | None) -> str:
    """Keep only a short display name; never use caller paths as storage paths."""
    normalized = (filename or "document").replace("\\", "/")
    basename = PurePosixPath(normalized).name.strip()
    if not basename or basename in {".", ".."}:
        raise DocumentInputError("invalid_filename", "Provide a valid document filename.")
    return basename[:255]


def validate_document(filename: str | None, content: bytes, max_bytes: int) -> ValidatedDocument:
    name = safe_original_filename(filename)
    extension = PurePosixPath(name).suffix.lower()
    if extension not in _CONTENT_TYPES:
        raise DocumentInputError("unsupported_format", "Supported formats are PDF, DOCX, and TXT.", 415)
    if len(content) > max_bytes:
        raise DocumentInputError("file_too_large", "The document exceeds the configured upload size limit.", 413)
    if not content:
        raise DocumentInputError("empty_document", "The uploaded document is empty.")

    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise DocumentInputError("invalid_file_content", "The file content does not match a valid PDF document.")
    elif extension == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise DocumentInputError("invalid_file_content", "The file content does not match a valid DOCX document.")
                if sum(item.file_size for item in archive.infolist()) > max(max_bytes * 20, max_bytes):
                    raise DocumentInputError("document_expansion_limit", "The DOCX content exceeds the safe processing limit.", 413)
        except zipfile.BadZipFile as exc:
            raise DocumentInputError("invalid_file_content", "The file content does not match a valid DOCX document.") from exc
    else:
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentInputError("invalid_file_content", "TXT files must contain UTF-8 text.") from exc
        if "\x00" in decoded:
            raise DocumentInputError("invalid_file_content", "The TXT file contains binary data rather than plain text.")

    return ValidatedDocument(name, extension, _CONTENT_TYPES[extension], len(content), content)
