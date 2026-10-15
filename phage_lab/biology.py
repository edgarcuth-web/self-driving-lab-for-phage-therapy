"""Input validation and synthetic fixtures, not a biological prediction model."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import random

MAX_BASES = 20_000_000
DNA_ALPHABET = frozenset("ACGTRYSWKMBDHVN")


@dataclass(frozen=True)
class GenomeSummary:
    sha256: str
    bases: int
    contigs: int

    def public_metadata(self) -> dict:
        return asdict(self)


def read_fasta(path: Path) -> GenomeSummary:
    """Hash normalized contigs without retaining DNA or header text."""
    if path.stat().st_size > MAX_BASES * 2:
        raise ValueError("FASTA file exceeds the demo size limit (40 MB).")
    digest = sha256()
    bases = contigs = current_bases = 0
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if not line[1:].strip():
                    raise ValueError(f"Empty FASTA header at line {line_number}.")
                if contigs and current_bases == 0:
                    raise ValueError("FASTA contains an empty contig.")
                digest.update(b"\0")
                contigs += 1
                current_bases = 0
                continue
            if not contigs:
                raise ValueError("FASTA sequence must follow a >header line.")
            sequence = line.upper()
            if set(sequence) - DNA_ALPHABET:
                raise ValueError(f"Invalid DNA characters at line {line_number}.")
            bases += len(sequence)
            current_bases += len(sequence)
            if bases > MAX_BASES:
                raise ValueError("FASTA exceeds 20 million bases in this demo.")
            digest.update(sequence.encode("ascii"))
    if not contigs or not current_bases:
        raise ValueError("FASTA has no sequence or ends with an empty contig.")
    return GenomeSummary(digest.hexdigest(), bases, contigs)


def mock_candidates(genome: GenomeSummary) -> list[dict]:
    """Fingerprint-derived scores only exercise the interface; they mean nothing biologically."""
    rng = random.Random("mock-candidates:" + genome.sha256)
    candidates = [
        {"id": f"SIM-PHAGE-{letter}", "simulation_score": round(rng.uniform(0.1, 0.9), 3),
         "source": "synthetic_fixture", "validated": False}
        for letter in "ABCDEF"
    ]
    return sorted(candidates, key=lambda candidate: (-candidate["simulation_score"], candidate["id"]))
