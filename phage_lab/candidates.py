"""Candidate retrieval from pinned reference snapshots.

A provider is the only thing in the system that turns "a bacterium" into
candidate records. It stamps each record with the provenance the experiment
path requires, so a plan can be traced back to a named snapshot of a named
database rather than to whoever happened to write a JSON file.

Nothing here scores, ranks or predicts infection. A provider reports what the
source database says; ordering is by the source's own metadata, and the
records carry no probability of any kind.
"""

import csv
from pathlib import Path
import re
from typing import Iterable, Protocol

from .snapshots import Snapshot

# INPHARED's column headings have changed spelling and capitalization between
# releases, so columns are resolved by alias against normalized headers rather
# than by a fixed name. A missing required column fails loudly with the headers
# that were actually present.
INPHARED_COLUMNS = {
    "accession": ("accession", "accession number", "genbank accession"),
    "description": ("description", "title"),
    "host": ("host", "isolation host", "isolation host beware", "host organism"),
    "genome_length": ("genome length bp", "genome length", "length bp", "length"),
    "molecule": ("molecule", "molecule type"),
    "classification": ("classification", "lowest taxa", "genus"),
    "jumbophage": ("jumbophage",),
    "coding_capacity": ("coding capacity",),
    "cds_count": ("number cds", "number of cds", "cds"),
}
INPHARED_REQUIRED = ("accession", "description", "host")
MAX_ROWS = 2_000_000


class ProviderError(RuntimeError):
    pass


class CandidateProvider(Protocol):
    """Turns a host description into provenance-stamped candidate records."""

    def describe(self) -> dict:
        """Identify the provider and the snapshot behind it."""
        ...

    def search(self, host: str, *, limit: int = 20) -> list[dict]:
        """Return candidate records whose recorded host matches ``host``."""
        ...


def _normalize(header: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", header.strip().lower()).strip().replace("  ", " ")


def _resolve_columns(headers: Iterable[str]) -> dict[str, str]:
    available = {_normalize(header): header for header in headers if header}
    resolved = {}
    for field, aliases in INPHARED_COLUMNS.items():
        for alias in aliases:
            if alias in available:
                resolved[field] = available[alias]
                break
    missing = [field for field in INPHARED_REQUIRED if field not in resolved]
    if missing:
        raise ProviderError(
            f"Snapshot is missing required column(s) {', '.join(missing)}. "
            f"Headers present: {', '.join(sorted(available.values())) or '(none)'}. "
            "Add the release's spelling to INPHARED_COLUMNS if the format changed.")
    return resolved


def _host_terms(host: str) -> list[str]:
    terms = [part for part in _normalize(host).split(" ") if part]
    if not terms:
        raise ProviderError("A host query must contain at least one word.")
    return terms


class InpharedProvider:
    """Reads phage genome records from an INPHARED metadata snapshot.

    INPHARED is a monthly curated set of phage genomes with host annotation.
    The host field is the host recorded by whoever deposited the genome: it is
    an annotation, not an experimental host-range result, and this provider
    does not treat it as one.
    """

    name = "inphared"

    def __init__(self, snapshot: Snapshot, *, delimiter: str = "\t"):
        if snapshot.source != "inphared":
            raise ProviderError(
                f"Snapshot declares source {snapshot.source!r}, not 'inphared'.")
        self.snapshot = snapshot
        self.delimiter = delimiter

    def describe(self) -> dict:
        return {"provider": self.name, "snapshot_version": self.snapshot.version,
                "snapshot_sha256": self.snapshot.sha256,
                "source_uri": self.snapshot.source_uri,
                "retrieved_at": self.snapshot.downloaded_at,
                "notes": ("Host annotation is the depositor's, not an experimental "
                          "host-range measurement. No infection probability is implied.")}

    def _rows(self) -> Iterable[dict]:
        with self.snapshot.path().open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            if not reader.fieldnames:
                raise ProviderError("Snapshot has no header row.")
            columns = _resolve_columns(reader.fieldnames)
            for index, row in enumerate(reader):
                if index >= MAX_ROWS:
                    raise ProviderError("Snapshot exceeds the supported row count.")
                yield {field: (row.get(column) or "").strip()
                       for field, column in columns.items()}

    def search(self, host: str, *, limit: int = 20) -> list[dict]:
        if limit < 1:
            raise ProviderError("limit must be at least 1.")
        terms = _host_terms(host)
        stamp = self.snapshot.provenance()
        matches = []
        for row in self._rows():
            if not row["accession"]:
                continue
            haystack = _normalize(row["host"])
            if not all(term in haystack for term in terms):
                continue
            record = {"id": row["accession"], "accession": row["accession"],
                      "description": row["description"],
                      "recorded_host": row["host"],
                      "host_query": host,
                      "host_annotation_source": "depositor_metadata",
                      **stamp}
            for field in ("genome_length", "molecule", "classification",
                          "coding_capacity", "cds_count", "jumbophage"):
                if row.get(field):
                    record[field] = row[field]
            matches.append(record)
            if len(matches) >= limit:
                break
        if not matches:
            raise ProviderError(
                f"No genome in snapshot {self.snapshot.version} records a host matching "
                f"{host!r}. Try a genus alone, or check the snapshot's host spelling.")
        return matches


PROVIDERS = {InpharedProvider.name: InpharedProvider}


def open_provider(snapshot: Snapshot) -> CandidateProvider:
    """Build the provider that matches a snapshot's declared source."""
    try:
        factory = PROVIDERS[snapshot.source]
    except KeyError:
        raise ProviderError(
            f"No provider for snapshot source {snapshot.source!r}; "
            f"known sources: {', '.join(sorted(PROVIDERS))}.") from None
    return factory(snapshot)


def load_snapshot_dir(directory: Path, *, verify: bool = True) -> CandidateProvider:
    from .snapshots import load_snapshot
    return open_provider(load_snapshot(directory, verify=verify))
