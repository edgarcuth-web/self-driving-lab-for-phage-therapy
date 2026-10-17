"""Small shared mechanics for versioned JSON artifacts.

Domain modules own their schemas and admission rules. These functions only handle
primitive validation, canonical hashing and file I/O; serialized formats stay stable.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonempty string.")
    return value.strip()


def parse_timestamp(value: str, field_name: str = "Timestamp") -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")
    return parsed


def validate_digest(value: str, field_name: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


def canonical_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(data) -> str:
    return sha256(canonical_json(data).encode("utf-8")).hexdigest()


def with_content_hash(content: dict) -> dict:
    """Hash the exact content being exported, without rebuilding it."""
    return {"content_sha256": content_hash(content), **content}


def atomic_write_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{label} could not be loaded: {exc}") from None
