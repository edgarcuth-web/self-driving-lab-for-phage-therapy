"""Pinned local copies of external reference data.

A snapshot is a file that was downloaded once, hashed, and described by a
manifest beside it. Every run then reads that fixed file rather than whatever
the upstream database happens to serve today, so two runs of the same plan see
the same candidates and a report's provenance names a version that can be
fetched again.

Downloading is deliberately a separate step from running an experiment: the
orchestrator never reaches the network mid-run.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from urllib import request
from urllib.parse import urlparse

MANIFEST_NAME = "manifest.json"
READ_CHUNK = 1 << 20
MAX_SNAPSHOT_BYTES = 2_000_000_000


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    """A verified local copy of one upstream file."""

    source: str
    version: str
    data_file: str
    sha256: str
    source_uri: str
    downloaded_at: str
    bytes: int

    @property
    def directory(self) -> Path:
        return self._directory

    def path(self) -> Path:
        return self._directory / self.data_file

    def provenance(self) -> dict:
        """The provenance stamp every candidate from this snapshot carries."""
        return {"source_db": self.source, "retrieved_at": self.downloaded_at,
                "source_uri": self.source_uri, "snapshot_version": self.version,
                "snapshot_sha256": self.sha256}


def _digest(path: Path) -> tuple[str, int]:
    digest = sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            total += len(chunk)
            if total > MAX_SNAPSHOT_BYTES:
                raise SnapshotError("Snapshot exceeds the size limit.")
            digest.update(chunk)
    return digest.hexdigest(), total


def create_snapshot(directory: Path, *, source: str, version: str, source_uri: str,
                    url: str | None = None, from_file: Path | None = None,
                    timeout: float = 300.0) -> Snapshot:
    """Fetch or copy one upstream file into ``directory`` and record its identity.

    Exactly one of ``url`` (download) or ``from_file`` (a copy already on disk,
    for networks that cannot reach the source) must be given. ``source_uri``
    always records where the data actually came from upstream, even when the
    bytes arrived by hand.
    """
    if bool(url) == bool(from_file):
        raise SnapshotError("Provide exactly one of url or from_file.")
    if not version.strip() or not source.strip() or not source_uri.strip():
        raise SnapshotError("A snapshot needs a source, a version and a source URI.")
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / MANIFEST_NAME).exists():
        raise SnapshotError(f"{directory} already holds a snapshot; choose a new directory.")

    if from_file is not None:
        name = from_file.name
        shutil.copyfile(from_file, directory / name)
    else:
        if not url.lower().startswith("https://"):
            raise SnapshotError("Snapshot downloads must use https.")
        name = Path(urlparse(url).path).name or "snapshot.dat"
        try:
            with request.urlopen(url, timeout=timeout) as response, \
                    (directory / name).open("wb") as handle:
                shutil.copyfileobj(response, handle, READ_CHUNK)
        except OSError as exc:
            raise SnapshotError(f"Could not download the snapshot: {exc}") from None

    checksum, size = _digest(directory / name)
    snapshot = Snapshot(source=source, version=version, data_file=name, sha256=checksum,
                        source_uri=source_uri,
                        downloaded_at=datetime.now(timezone.utc).isoformat(), bytes=size)
    object.__setattr__(snapshot, "_directory", directory)
    (directory / MANIFEST_NAME).write_text(
        json.dumps(asdict(snapshot), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot


def load_snapshot(directory: Path, *, verify: bool = True) -> Snapshot:
    """Read a snapshot manifest and re-check the data file against it."""
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SnapshotError(f"No {MANIFEST_NAME} in {directory}.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SnapshotError(f"Snapshot manifest is not valid JSON: {exc}") from None
    fields = {field for field in Snapshot.__dataclass_fields__}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise SnapshotError("Snapshot manifest does not match the expected fields.")
    snapshot = Snapshot(**manifest)
    object.__setattr__(snapshot, "_directory", directory)
    if not snapshot.path().is_file():
        raise SnapshotError(f"Snapshot data file {snapshot.data_file} is missing.")
    if verify:
        checksum, size = _digest(snapshot.path())
        if checksum != snapshot.sha256 or size != snapshot.bytes:
            raise SnapshotError(
                f"Snapshot {snapshot.version} does not match its manifest checksum; "
                "the local copy changed after it was recorded.")
    return snapshot
