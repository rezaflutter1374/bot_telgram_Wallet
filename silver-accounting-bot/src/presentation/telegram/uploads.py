from __future__ import annotations

from aiogram.types import Message

from application.errors import ValidationError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
ALLOWED_BACKUP_EXTENSIONS = {".json", ".enc", ".txt"}


def extract_secure_attachment_file_id(message: Message) -> str:
    if message.photo:
        largest = message.photo[-1]
        if largest.file_size and largest.file_size > MAX_UPLOAD_BYTES:
            raise ValidationError("Photo too large")
        return largest.file_id

    if message.document:
        document = message.document
        if document.file_size and document.file_size > MAX_UPLOAD_BYTES:
            raise ValidationError("Document too large")
        if document.mime_type not in ALLOWED_DOCUMENT_MIME_TYPES:
            raise ValidationError("Only PDF and image documents are allowed")
        return document.file_id

    raise ValidationError("Attachment required")


def validate_backup_document(message: Message) -> str:
    if not message.document:
        raise ValidationError("Backup document required")
    document = message.document
    if document.file_size and document.file_size > MAX_UPLOAD_BYTES:
        raise ValidationError("Backup file too large")
    name = (document.file_name or "").lower()
    if not any(name.endswith(ext) for ext in ALLOWED_BACKUP_EXTENSIONS):
        raise ValidationError("Invalid backup file type")
    return document.file_id
