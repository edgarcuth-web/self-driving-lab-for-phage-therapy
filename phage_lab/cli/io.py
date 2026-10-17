"""Bounded JSON inputs shared by command handlers."""

import json
from pathlib import Path

from ..workflow import STANDARD_WORKFLOW

MAX_INPUT_BYTES = 4_000_000


def _load_json(path: Path, label: str):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{label} file exceeds the {MAX_INPUT_BYTES // 1_000_000} MB limit.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} file is not valid JSON: {exc}") from None


def _load_candidates(path: Path) -> list[dict]:
    """Load candidate records someone already retrieved.

    Provenance in such a file is only as honest as its author. Records produced
    by `candidates` carry snapshot fields, and `run --require-snapshot` insists
    on them.
    """
    data = _load_json(path, "Candidate")
    if not isinstance(data, list):
        raise ValueError("Candidate file must contain a JSON array of candidate records.")
    return data


def _load_material_batches(path: Path) -> list:
    from ..material_batch import material_batch_from_dict

    data = _load_json(path, "MaterialBatch")
    if not isinstance(data, list):
        raise ValueError("MaterialBatch file must contain a JSON array.")
    return [material_batch_from_dict(item) for item in data]


def _load_measurements(path: Path) -> list:
    from ..measurement import measurement_from_dict

    data = _load_json(path, "Measurement")
    records = data if isinstance(data, list) else [data]
    return [measurement_from_dict(item) for item in records]


def _load_workflow(path: Path | None) -> dict:
    if path is None:
        return dict(STANDARD_WORKFLOW)
    data = _load_json(path, "Workflow")
    if not isinstance(data, dict):
        raise ValueError("Workflow file must contain a JSON object of operation -> dependencies.")
    return {key: tuple(value) if isinstance(value, list) else value for key, value in data.items()}
