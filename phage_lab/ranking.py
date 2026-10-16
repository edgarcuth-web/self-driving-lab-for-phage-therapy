"""Host-range ranking by independently validated external tools.

A ranker orders candidate phages against one host genome using a published
tool, and records what the tool reported together with enough provenance to
reproduce it: which tool, which version, which parameters, which host genome.

Two rules hold throughout.

Nothing here invents an ordering. If the configured tool is missing or fails,
ranking raises; it never falls back to a heuristic, an alphabetical order or
the source database's row order while presenting the result as a ranking.

A tool statistic is not a probability of infection. Shared k-mers between a
phage and a host genome are evidence that the two have exchanged sequence or
share composition, which correlates with host range but does not measure it.
Every ranking block carries that caveat, and no code here converts a p-value
into a success probability.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Protocol

from .interaction_evidence import phist_ranking_to_evidence
from .sequences import SequenceStore

RANKING_FIELDS = ("tool", "tool_version", "ranked_at", "host_genome_sha256",
                  "statistic", "interpretation", "reported")
PHIST_CAVEAT = ("Shared k-mers between phage and host genomes. Correlates with host "
                "range; it is not a probability of successful infection.")
NO_MATCH_NOTE = ("The tool reported no significant k-mer sharing with this host. That is "
                 "an absence of this signal, not evidence that infection cannot occur.")
MAX_CANDIDATES = 2_000
TOOL_TIMEOUT = 3600.0


class RankingError(RuntimeError):
    pass


class HostRangeRanker(Protocol):
    """Orders candidates against one host genome using an external tool."""

    def describe(self) -> dict: ...

    def rank(self, host_fasta: Path, candidates: list[dict],
             sequences: SequenceStore) -> list[dict]: ...


def _host_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PhistHit:
    accession: str
    common_kmers: int
    pvalue: float
    adj_pvalue: float


class PhistRanker:
    """Runs PHIST (Zielezinski et al.) over candidate phage genomes and one host.

    PHIST counts exact k-mer matches between each phage genome and each host
    genome and reports a p-value for the match. It is a published, independently
    benchmarked tool; this class only invokes it and parses its output.
    """

    name = "phist"

    def __init__(self, phist_script: Path, *, k: int = 25, threads: int = 2,
                 python_executable: str | None = None):
        self.script = Path(phist_script)
        if not self.script.is_file():
            raise RankingError(
                f"PHIST script not found at {self.script}. Install PHIST and pass its "
                "phist.py path; ranking never falls back to an invented ordering.")
        if not 10 <= k <= 64:
            raise RankingError("PHIST k must be between 10 and 64.")
        if threads < 1:
            raise RankingError("threads must be at least 1.")
        self.k = k
        self.threads = threads
        self.python = python_executable or sys.executable
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            try:
                completed = subprocess.run(
                    [self.python, str(self.script), "--version"],
                    capture_output=True, text=True, timeout=120, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise RankingError(f"Could not run PHIST: {exc}") from None
            version = (completed.stdout or completed.stderr).strip().splitlines()
            self._version = version[0].strip() if version else "unknown"
        return self._version

    def describe(self) -> dict:
        return {"tool": self.name, "tool_version": self.version(),
                "parameters": {"k": self.k, "threads": self.threads},
                "script": str(self.script),
                "statistic": f"shared_{self.k}mers",
                "interpretation": PHIST_CAVEAT}

    def _run(self, virus_dir: Path, host_dir: Path, out_dir: Path) -> Path:
        command = [self.python, str(self.script), "-k", str(self.k),
                   "-t", str(self.threads), str(virus_dir), str(host_dir), str(out_dir)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=TOOL_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise RankingError("PHIST did not finish within the time limit.") from None
        except OSError as exc:
            raise RankingError(f"Could not run PHIST: {exc}") from None
        predictions = out_dir / "predictions.csv"
        if completed.returncode != 0 or not predictions.is_file():
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise RankingError(
                "PHIST failed to produce predictions"
                + (f": {detail[-1]}" if detail else ".")
                + " No ranking was produced; the run is not ordered.")
        return predictions

    @staticmethod
    def _parse(predictions: Path, by_filename: dict[str, str]) -> dict[str, PhistHit]:
        """Read predictions.csv, treating value-less rows as 'no significant match'.

        PHIST writes a row per query phage, but a phage with no significant
        k-mer sharing gets its name alone and no host or statistics. Those rows
        are an answer, not a malformed file.
        """
        hits: dict[str, PhistHit] = {}
        with predictions.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            expected = {"phage", "host", "#common-kmers", "pvalue", "adj-pvalue"}
            if not expected.issubset(set(reader.fieldnames or ())):
                raise RankingError(
                    "PHIST predictions.csv does not have the expected columns "
                    f"({', '.join(sorted(expected))}); found "
                    f"{', '.join(reader.fieldnames or ['(none)'])}.")
            for row in reader:
                name = (row.get("phage") or "").strip()
                accession = by_filename.get(name) or by_filename.get(Path(name).stem)
                if accession is None:
                    continue
                values = [row.get("#common-kmers"), row.get("pvalue"), row.get("adj-pvalue")]
                if any(value is None or not str(value).strip() for value in values):
                    continue  # reported with no match against this host
                try:
                    hit = PhistHit(accession=accession, common_kmers=int(values[0]),
                                   pvalue=float(values[1]), adj_pvalue=float(values[2]))
                except (TypeError, ValueError):
                    raise RankingError(
                        f"PHIST reported unparseable statistics for {name!r}: "
                        f"{', '.join(str(value) for value in values)}.") from None
                previous = hits.get(accession)
                if previous is None or hit.common_kmers > previous.common_kmers:
                    hits[accession] = hit
        return hits

    def rank(self, host_fasta: Path, candidates: list[dict],
             sequences: SequenceStore) -> list[dict]:
        if not candidates:
            raise RankingError("Ranking needs at least one candidate.")
        if len(candidates) > MAX_CANDIDATES:
            raise RankingError(f"Ranking is limited to {MAX_CANDIDATES} candidates per run.")
        accessions = [candidate["accession"] for candidate in candidates
                      if isinstance(candidate.get("accession"), str)]
        if len(accessions) != len(candidates):
            raise RankingError("Every candidate needs an accession to look its sequence up.")
        missing = sequences.missing(accessions)
        if missing:
            raise RankingError(
                f"Sequence snapshot {sequences.snapshot.version} has no genome for "
                f"{', '.join(missing[:5])}"
                + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
                + ". Rank only candidates whose sequences are present.")

        host_digest = _host_digest(host_fasta)
        stamp = {"tool": self.name, "tool_version": self.version(),
                 "parameters": dict(self.describe()["parameters"]),
                 "ranked_at": datetime.now(timezone.utc).isoformat(),
                 "host_genome_sha256": host_digest,
                 "sequence_snapshot_version": sequences.snapshot.version,
                 "sequence_snapshot_sha256": sequences.snapshot.sha256,
                 "statistic": f"shared_{self.k}mers",
                 "interpretation": PHIST_CAVEAT}

        with tempfile.TemporaryDirectory(prefix="phage-lab-rank-") as temporary:
            workspace = Path(temporary)
            virus_dir = workspace / "virus"
            host_dir = workspace / "host"
            written = sequences.write_fasta_dir(accessions, virus_dir)
            host_dir.mkdir()
            shutil.copyfile(host_fasta, host_dir / "host.fna")
            predictions = self._run(virus_dir, host_dir, workspace / "out")
            by_filename = {path.name: accession for accession, path in written.items()}
            by_filename.update({path.stem: accession for accession, path in written.items()})
            hits = self._parse(predictions, by_filename)

        reported, unreported = [], []
        for candidate in candidates:
            hit = hits.get(candidate["accession"])
            if hit is None:
                unreported.append({**candidate,
                                   "ranking": {**stamp, "reported": False, "rank": None,
                                               "note": NO_MATCH_NOTE}})
                continue
            reported.append(({**candidate,
                              "ranking": {**stamp, "reported": True, "rank": None,
                                          "value": hit.common_kmers,
                                          "pvalue": hit.pvalue,
                                          "adj_pvalue": hit.adj_pvalue}}, hit))

        reported.sort(key=lambda item: (-item[1].common_kmers, item[1].adj_pvalue,
                                        item[0]["accession"]))
        ranked = []
        for position, (record, _) in enumerate(reported, start=1):
            record["ranking"]["rank"] = position
            ranked.append(record)
        unreported.sort(key=lambda record: record["accession"])
        ordered = ranked + unreported
        for record in ordered:
            evidence = phist_ranking_to_evidence(record)
            record["interaction_evidence"] = [evidence.to_dict()]
        return ordered


def phist_from_environment(path: str | Path | None = None, **kwargs) -> PhistRanker:
    """Locate phist.py from an explicit path, PHIST_PATH, or PATH."""
    import os

    candidate = path or os.environ.get("PHIST_PATH") or shutil.which("phist.py")
    if not candidate:
        raise RankingError(
            "PHIST was not found. Pass --phist /path/to/phist.py or set PHIST_PATH. "
            "Ranking has no built-in fallback: without the tool there is no ordering.")
    return PhistRanker(Path(candidate), **kwargs)


RANKERS = {PhistRanker.name: phist_from_environment}

_SUSPECT_NAMES = re.compile(r"(probab|likelihood|success|efficacy|infectivity)", re.I)


def assert_no_invented_probability(record: dict) -> None:
    """Guard against a ranking block growing a field that reads as P(infection)."""
    block = record.get("ranking")
    if not isinstance(block, dict):
        return
    offenders = [key for key in block if _SUSPECT_NAMES.search(key)]
    if offenders:
        raise RankingError(
            f"Ranking block contains {', '.join(offenders)}; tool statistics must not be "
            "presented as a probability of infection.")
