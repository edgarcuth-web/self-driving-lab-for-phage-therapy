"""Runtime source identity works for both Git clones and downloaded ZIP archives."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess

from . import __version__


def source_identity(root: Path | None = None) -> dict:
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    paths = sorted(path for path in (root / "phage_lab").rglob("*")
                   if path.is_file() and path.suffix in {".py", ".html", ".css", ".js", ".json"}
                   and "__pycache__" not in path.parts)
    for name in ("examples/toy_genome.fasta", "start-dashboard.bat"):
        if (root / name).is_file():
            paths.append(root / name)
    manifest = []
    for path in sorted(paths):
        # Windows Git checkouts can use CRLF; normalize that harmless difference.
        content = path.read_bytes().replace(b"\r\n", b"\n")
        manifest.append([path.relative_to(root).as_posix(), sha256(content).hexdigest()])
    identity = {"version": __version__, "source_sha256": sha256(json.dumps(
        manifest, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest(),
        "source_files": len(manifest), "git_commit": None, "git_dirty": None}
    # A ZIP inside some unrelated parent repo is still a ZIP, not that parent's commit.
    if not (root / ".git").exists():
        return identity
    try:
        options = {"cwd": root, "text": True, "stderr": subprocess.DEVNULL,
                   "timeout": 3, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], **options).strip()
        if Path(top).resolve() != root:
            return identity
        identity["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], **options).strip()
        changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all",
                                           "--", "phage_lab", "examples/toy_genome.fasta", "start-dashboard.bat"], **options)
        identity["git_dirty"] = bool(changes.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return identity
