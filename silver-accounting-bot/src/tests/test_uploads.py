from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.errors import ValidationError
from presentation.telegram.uploads import extract_secure_attachment_file_id, validate_backup_document


def test_extract_secure_attachment_from_photo() -> None:
    message = SimpleNamespace(
        photo=[SimpleNamespace(file_id="small", file_size=10), SimpleNamespace(file_id="large", file_size=20)],
        document=None,
    )
    assert extract_secure_attachment_file_id(message) == "large"


def test_extract_secure_attachment_rejects_invalid_document() -> None:
    message = SimpleNamespace(
        photo=None,
        document=SimpleNamespace(file_id="doc", file_size=10, mime_type="text/plain"),
    )
    with pytest.raises(ValidationError):
        extract_secure_attachment_file_id(message)


def test_validate_backup_document() -> None:
    message = SimpleNamespace(
        document=SimpleNamespace(file_id="backup", file_size=10, file_name="backup.enc.json"),
    )
    assert validate_backup_document(message) == "backup"
