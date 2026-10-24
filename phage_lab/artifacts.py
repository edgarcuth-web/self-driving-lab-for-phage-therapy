"""Small shared mechanics for versioned JSON artifacts.

Domain modules own their schemas and admission rules. These functions only handle
primitive validation, canonical hashing and file I/O; serialized formats stay stable.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
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


def is_sha256(value) -> bool:
    """True for a lowercase 64-character hexadecimal SHA-256 digest."""
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def validate_digest(value: str, field_name: str) -> None:
    if not is_sha256(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


def require_text_tuple(values: tuple[str, ...], field_name: str, *, nonempty: bool = False) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    if nonempty and not values:
        raise ValueError(f"{field_name} must not be empty.")
    for value in values:
        require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


def validate_scalar(value, field_name: str, *, allow_none: bool = True, allow_bool: bool = True) -> None:
    """Accept a finite JSON scalar; null and booleans can be disallowed per field."""
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{field_name} must not be null; omit unknown values.")
    if isinstance(value, bool):
        if allow_bool:
            return
        raise ValueError(f"{field_name} must not be a boolean.")
    if isinstance(value, (str, int)) or (isinstance(value, float) and math.isfinite(value)):
        return
    suffix = " or null" if allow_none else ""
    raise ValueError(f"{field_name} must be a finite JSON scalar{suffix}.")


def validate_scalar_mapping(value: dict, field_name: str, *, allow_bool: bool = True) -> None:
    """Require text keys and finite JSON scalar or null values."""
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        require_text(key, f"{field_name} key")
        validate_scalar(item, field_name, allow_bool=allow_bool)


def canonical_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(data) -> str:
    return sha256(canonical_json(data).encode("utf-8")).hexdigest()


def with_content_hash(content: dict) -> dict:
    """Hash the exact content being exported, without rebuilding it."""
    return {"content_sha256": content_hash(content), **content}


class ContentAddressed:
    """Mixin for records whose content_sha256 covers exactly ``_content_dict()``."""

    __slots__ = ()

    def _content_dict(self) -> dict:
        raise NotImplementedError

    @property
    def content_sha256(self) -> str:
        return content_hash(self._content_dict())

    def to_dict(self) -> dict:
        return with_content_hash(self._content_dict())


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

def read_json_object_with_digest(
    path: str | Path,
    *,
    label: str = "JSON artifact",
) -> tuple[dict, str]:
    """Read one JSON object and hash the exact bytes that were parsed."""
    source = Path(path)

    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant {value!r} is not allowed")

    try:
        raw = source.read_bytes()
        digest = sha256(raw).hexdigest()
        data = json.loads(raw.decode("utf-8-sig"), parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} could not be loaded from {source}: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{label} at {source} must contain a JSON object.")
    return data, digest


def read_json_object(path: str | Path, *, label: str = "JSON artifact") -> dict:
    """Read one strict JSON object."""
    document, _ = read_json_object_with_digest(path, label=label)
    return document


def canonical_content_sha256(document: dict) -> str:
    """Hash canonical content while excluding an optional content_sha256 field."""
    if not isinstance(document, dict):
        raise ValueError("content to hash must be a JSON object.")
    content = dict(document)
    content.pop("content_sha256", None)
    return content_hash(content)


def sha256_file(path: str | Path) -> str:
    """Hash exact file bytes without loading the complete file into memory."""
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

