"""Command-line entry point for snapshots, candidate retrieval and orchestration."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from .workflow import (
    DEFAULT_SELECTION_SIZE,
    EXECUTION_MODES,
    STANDARD_WORKFLOW,
    WorkflowError,
    run_experiment,
)

MAX_INPUT_BYTES = 4_000_000
COMMANDS = ("run", "host-profile", "phage-profiles", "fetch-snapshot", "candidates", "rank", "version")


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


def _load_workflow(path: Path | None) -> dict:
    if path is None:
        return dict(STANDARD_WORKFLOW)
    data = _load_json(path, "Workflow")
    if not isinstance(data, dict):
        raise ValueError("Workflow file must contain a JSON object of operation -> dependencies.")
    return {key: tuple(value) if isinstance(value, list) else value for key, value in data.items()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Closed-loop phage R&D tools and laboratory orchestration.")
    parser.add_argument("command", nargs="?", default="run", choices=COMMANDS)

    parser.add_argument("--genome", type=Path,
                        default=Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta",
                        help="Host bacterial FASTA; only a hash and summary are retained.")
    parser.add_argument("--candidates", type=Path,
                        help="JSON array of candidate records retrieved earlier.")
    parser.add_argument("--snapshot", type=Path,
                        help="Snapshot directory to retrieve candidates from.")
    parser.add_argument("--host", help="Host organism to search the snapshot for.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum candidates to retrieve.")
    parser.add_argument("--out", type=Path, help="Write the command output artifact here.")
    parser.add_argument("--execution-mode", choices=EXECUTION_MODES,
                        help="Required for a run. No default: state which hardware you expect.")
    parser.add_argument("--require-snapshot", action="store_true",
                        help="Refuse candidates that do not name a pinned snapshot.")
    parser.add_argument("--sample-id", help="Caller-owned sample identifier.")
    parser.add_argument("--workflow", type=Path,
                        help="JSON object of operation -> dependency list. Defaults to the standard pipeline.")
    parser.add_argument("--agent", choices=["rule", "openrouter"], default="rule")
    parser.add_argument("--select-min", type=int, default=DEFAULT_SELECTION_SIZE[0],
                        help="Fewest candidates a plan may select.")
    parser.add_argument("--select-max", type=int, default=DEFAULT_SELECTION_SIZE[1],
                        help="Most candidates a plan may select.")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    parser.add_argument("--quiet", action="store_true",
                        help="Do not echo the event stream; it is still written to events.jsonl.")

    parser.add_argument("--sequences", type=Path,
                        help="Genome FASTA snapshot directory, for tools that need sequences.")
    parser.add_argument("--host-genome", type=Path,
                        help="Host bacterial FASTA to rank candidates against.")
    parser.add_argument("--host-profile", type=Path,
                        help="Optional HostProfile JSON to bind InteractionEvidence to a profile ID.")
    parser.add_argument("--ranker", choices=["phist"], default="phist")
    parser.add_argument("--phist", type=Path,
                        help="Path to phist.py. Falls back to PHIST_PATH, then PATH.")
    parser.add_argument("--k", type=int, default=25, help="k-mer length for PHIST.")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--only-ranked", action="store_true",
                        help="Drop candidates the tool did not report.")

    parser.add_argument("--source", default="inphared", help="Snapshot source name.")
    parser.add_argument("--version", dest="snapshot_version",
                        help="Upstream release identifier, e.g. 1Oct2026.")
    parser.add_argument("--url", help="https URL to download the snapshot from.")
    parser.add_argument("--from-file", type=Path,
                        help="Use a file already on disk instead of downloading.")
    parser.add_argument("--source-uri", help="Where the data came from upstream.")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip re-hashing a large snapshot on load.")
    return parser



def _host_profile(args, parser) -> int:
    """Create the first version of a host record without inventing annotations."""

    missing = [name for name, value in (("--sample-id", args.sample_id), ("--out", args.out))
               if not value]
    if missing:
        parser.error("host-profile requires " + ", ".join(missing))
    from .biology import read_fasta
    from .host_profile import new_host_profile, write_host_profile
    try:
        genome = read_fasta(args.genome)
        profile = new_host_profile(args.sample_id, genome)
        write_host_profile(profile, args.out)
    except (OSError, ValueError) as exc:
        print(f"HostProfile 创建失败：{exc}", file=sys.stderr)
        return 2
    print(f"HostProfile {profile.profile_id} → {args.out}", flush=True)
    print("所有 biological feature class 初始为 unknown；尚未运行表征 analyzer。",
          file=sys.stderr)
    return 0


def _phage_profiles(args, parser) -> int:
    """Convert sourced candidate records into retrieved PhageProfile records."""

    missing = [name for name, value in (("--candidates", args.candidates), ("--out", args.out))
               if not value]
    if missing:
        parser.error("phage-profiles requires " + ", ".join(missing))
    from .phage_profile import retrieved_candidate_to_phage_profile
    try:
        candidates = _load_candidates(args.candidates)
        profiles = [
            retrieved_candidate_to_phage_profile(candidate).to_dict()
            for candidate in candidates
        ]
        args.out.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"PhageProfile 转换失败：{exc}", file=sys.stderr)
        return 2
    print(f"{len(profiles)} 个 PhageProfile → {args.out}", flush=True)
    print(
        "retrieved provenance 只表示外部记录来源；不会自动声明 biological origin。",
        file=sys.stderr,
    )
    return 0


def _fetch_snapshot(args, parser) -> int:
    from .snapshots import SnapshotError, create_snapshot
    missing = [name for name, value in (("--snapshot", args.snapshot),
                                        ("--version", args.snapshot_version))
               if not value]
    if missing:
        parser.error("fetch-snapshot requires " + ", ".join(missing))
    if bool(args.url) == bool(args.from_file):
        parser.error("fetch-snapshot requires exactly one of --url or --from-file")
    source_uri = args.source_uri or args.url
    if not source_uri:
        parser.error("fetch-snapshot with --from-file also requires --source-uri")
    try:
        snapshot = create_snapshot(args.snapshot, source=args.source,
                                   version=args.snapshot_version, source_uri=source_uri,
                                   url=args.url, from_file=args.from_file)
    except (SnapshotError, OSError) as exc:
        print(f"快照获取失败：{exc}", file=sys.stderr)
        return 2
    print(f"快照已记录：{args.snapshot}\n  来源 {snapshot.source} {snapshot.version}"
          f"\n  sha256 {snapshot.sha256}\n  {snapshot.bytes} bytes", flush=True)
    return 0


def _retrieve_candidates(args, parser) -> int:
    from .candidates import ProviderError, load_snapshot_dir
    from .snapshots import SnapshotError
    missing = [name for name, value in (("--snapshot", args.snapshot), ("--host", args.host))
               if not value]
    if missing:
        parser.error("candidates requires " + ", ".join(missing))
    try:
        provider = load_snapshot_dir(args.snapshot, verify=not args.skip_verify)
        records = provider.search(args.host, limit=args.limit)
    except (ProviderError, SnapshotError, OSError, ValueError) as exc:
        print(f"候选检索失败：{exc}", file=sys.stderr)
        return 2
    payload = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"{len(records)} 条候选 → {args.out}", flush=True)
    else:
        print(payload, end="")
    print("提示：host 字段是 depositor 的注释，不是实验测定的 host range。", file=sys.stderr)
    return 0


def _rank(args, parser) -> int:
    from .biology import read_fasta
    from .host_profile import load_host_profile
    from .ranking import RankingError, phist_from_environment
    from .sequences import SequenceError, SequenceStore
    from .snapshots import SnapshotError, load_snapshot

    missing = [name for name, value in (("--candidates", args.candidates),
                                        ("--sequences", args.sequences),
                                        ("--host-genome", args.host_genome)) if not value]
    if missing:
        parser.error("rank requires " + ", ".join(missing))
    try:
        candidates = _load_candidates(args.candidates)
        store = SequenceStore(load_snapshot(args.sequences, verify=not args.skip_verify))
        host_profile_id = None
        if args.host_profile:
            profile = load_host_profile(args.host_profile)
            genome = read_fasta(args.host_genome)
            if profile.genome.sha256 != genome.sha256:
                raise ValueError(
                    "HostProfile genome identity does not match --host-genome."
                )
            host_profile_id = profile.profile_id
        ranker = phist_from_environment(args.phist, k=args.k, threads=args.threads)
        print(f"{ranker.describe()['tool']} {ranker.describe()['tool_version']}："
              f"{len(candidates)} 个候选 vs {args.host_genome.name}", flush=True)
        ranked = ranker.rank(
            args.host_genome,
            candidates,
            store,
            host_profile_id=host_profile_id,
        )
    except (RankingError, SequenceError, SnapshotError, OSError, ValueError) as exc:
        print(f"排序失败：{exc}", file=sys.stderr)
        return 2

    reported = [record for record in ranked if record["ranking"]["reported"]]
    if args.only_ranked:
        ranked = reported
        if not ranked:
            print("没有候选被工具报告出显著匹配；没有可用的排序结果。", file=sys.stderr)
            return 2
    payload = json.dumps(ranked, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"{len(ranked)} 条 → {args.out}", flush=True)
    else:
        print(payload, end="")
    print(f"工具报告 {len(reported)} 条显著匹配，{len(ranked) - len(reported)} 条未报告。\n"
          f"统计量是 phage 与 host 基因组之间的共享 k-mer，不是感染成功概率；"
          f"未报告只代表没有这一信号，不代表不能感染。", file=sys.stderr)
    return 0


def _run(args, parser) -> int:
    if bool(args.candidates) == bool(args.snapshot):
        parser.error("run requires exactly one of --candidates or --snapshot")
    missing = [name for name, value in (("--execution-mode", args.execution_mode),
                                        ("--sample-id", args.sample_id)) if not value]
    if args.snapshot and not args.host:
        missing.append("--host")
    if missing:
        parser.error("run requires " + ", ".join(missing))
    if not 1 <= args.select_min <= args.select_max:
        parser.error("--select-min must be at least 1 and no greater than --select-max")

    from .agents import AgentError, OpenRouterAgent, RuleAgent
    from .candidates import ProviderError, load_snapshot_dir
    from .snapshots import SnapshotError
    try:
        agent = RuleAgent() if args.agent == "rule" else OpenRouterAgent.from_environment()
        if args.snapshot:
            provider = load_snapshot_dir(args.snapshot, verify=not args.skip_verify)
            manifest = provider.describe()
            candidates = provider.search(args.host, limit=args.limit)
            print(f"候选来自 {manifest['provider']} 快照 {manifest['snapshot_version']}："
                  f"{len(candidates)} 条", flush=True)
        else:
            candidates = _load_candidates(args.candidates)
        workflow = _load_workflow(args.workflow)
    except (AgentError, ProviderError, SnapshotError, OSError, ValueError) as exc:
        print(f"无法启动：{exc}", file=sys.stderr)
        return 2

    if args.execution_mode == "virtual_hardware":
        print("VIRTUAL HARDWARE: 设备动作与读数由软件 twin 产生，不是湿实验证据。", flush=True)

    try:
        report, directory = asyncio.run(run_experiment(
            args.genome, args.output_dir, sample_id=args.sample_id,
            candidates=candidates, devices=None, workflow=workflow, agent=agent,
            execution_mode=args.execution_mode,
            selection_size=(args.select_min, args.select_max),
            require_snapshot=args.require_snapshot,
            timeout_seconds=args.timeout_seconds, echo=not args.quiet))
    except WorkflowError as exc:
        print(f"运行被拒绝：{exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"无法启动或保存报告：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    print(f"\n流程状态：{report['status']}\n报告：{directory / 'report.md'}", flush=True)
    return 0 if report["status"] == "succeeded" else 2


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        from .provenance import source_identity
        print(json.dumps(source_identity(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "host-profile":
        return _host_profile(args, parser)
    if args.command == "phage-profiles":
        return _phage_profiles(args, parser)
    if args.command == "fetch-snapshot":
        return _fetch_snapshot(args, parser)
    if args.command == "candidates":
        return _retrieve_candidates(args, parser)
    if args.command == "rank":
        return _rank(args, parser)
    return _run(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
