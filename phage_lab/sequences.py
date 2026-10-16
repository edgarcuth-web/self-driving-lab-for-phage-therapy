"""Genome sequences for candidates, read from a pinned FASTA snapshot.

Candidate metadata says which phage a record is; tools like PHIST need the
phage's actual sequence. Sequences come from a second snapshot — an upstream
multi-FASTA, pinned and checksummed the same way — so a ranking run can name
the exact sequence set it compared against.

The index is built once per snapshot and cached beside it. It stores byte
offsets, not sequences, so a multi-gigabyte genome file is never held in
memory.
"""

from dataclasses import dataclass
import json
from pathlib import Path

from .snapshots import Snapshot

INDEX_NAME = "accession_index.json"
INDEX_SCHEMA = 1
MAX_SEQUENCE_BYTES = 50_000_000


class SequenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SequenceRecord:
    accession: str
    header: str
    sequence: str

    def to_fasta(self) -> str:
        lines = [self.sequence[index:index + 70]
                 for index in range(0, len(self.sequence), 70)]
        return f">{self.header}\n" + "\n".join(lines) + "\n"


def _accession_of(header: str) -> str:
    """INPHARED and RefSeq headers start with the accession, then a description."""
    return header.split(maxsplit=1)[0] if header.strip() else ""


def build_index(snapshot: Snapshot, *, rebuild: bool = False) -> dict[str, list[int]]:
    """Map each accession to the (start, end) byte range of its FASTA record."""
    index_path = snapshot.directory / INDEX_NAME
    if index_path.is_file() and not rebuild:
        try:
            cached = json.loads(index_path.read_text(encoding="utf-8"))
        except ValueError:
            cached = None
        if (isinstance(cached, dict) and cached.get("schema") == INDEX_SCHEMA
                and cached.get("snapshot_sha256") == snapshot.sha256):
            return cached["offsets"]

    offsets: dict[str, list[int]] = {}
    duplicates: set[str] = set()
    current: str | None = None
    start = 0
    with snapshot.path().open("rb") as handle:
        position = 0
        for raw in handle:
            if raw.startswith(b">"):
                if current is not None:
                    offsets[current] = [start, position]
                header = raw[1:].decode("utf-8", "replace").strip()
                accession = _accession_of(header)
                if not accession:
                    raise SequenceError(
                        f"FASTA record at byte {position} has an empty header.")
                if accession in offsets:
                    duplicates.add(accession)
                current = accession
                start = position
            position += len(raw)
        if current is not None:
            offsets[current] = [start, position]

    if not offsets:
        raise SequenceError(f"Snapshot {snapshot.version} contains no FASTA records.")
    if duplicates:
        raise SequenceError(
            f"Snapshot {snapshot.version} has duplicate accessions "
            f"({', '.join(sorted(duplicates)[:5])}); an accession must identify one sequence.")

    index_path.write_text(json.dumps(
        {"schema": INDEX_SCHEMA, "snapshot_sha256": snapshot.sha256, "offsets": offsets},
        ensure_ascii=False), encoding="utf-8")
    return offsets


class SequenceStore:
    """Random access to the genome sequences in one FASTA snapshot."""

    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot
        self._offsets = build_index(snapshot)

    def describe(self) -> dict:
        return {"source_db": self.snapshot.source,
                "snapshot_version": self.snapshot.version,
                "snapshot_sha256": self.snapshot.sha256,
                "source_uri": self.snapshot.source_uri,
                "sequences": len(self._offsets)}

    def __contains__(self, accession: str) -> bool:
        return accession in self._offsets

    def get(self, accession: str) -> SequenceRecord:
        try:
            start, end = self._offsets[accession]
        except KeyError:
            raise SequenceError(
                f"Accession {accession!r} is not in sequence snapshot "
                f"{self.snapshot.version}.") from None
        if end - start > MAX_SEQUENCE_BYTES:
            raise SequenceError(f"Sequence {accession!r} exceeds the size limit.")
        with self.snapshot.path().open("rb") as handle:
            handle.seek(start)
            block = handle.read(end - start).decode("utf-8", "replace")
        header, _, body = block.partition("\n")
        sequence = "".join(body.split())
        if not sequence:
            raise SequenceError(f"Accession {accession!r} has an empty sequence.")
        return SequenceRecord(accession=accession, header=header[1:].strip(), sequence=sequence)

    def missing(self, accessions) -> list[str]:
        return [item for item in accessions if item not in self._offsets]

    def write_fasta_dir(self, accessions, directory: Path) -> dict[str, Path]:
        """Write one FASTA file per accession, as directory-oriented tools expect."""
        directory.mkdir(parents=True, exist_ok=True)
        written = {}
        for accession in accessions:
            record = self.get(accession)
            # Tools key their output on the file name, so keep it recoverable.
            path = directory / f"{accession.replace('/', '_')}.fna"
            path.write_text(record.to_fasta(), encoding="utf-8")
            written[accession] = path
        if not written:
            raise SequenceError("No sequences were written; nothing to compare.")
        return written
