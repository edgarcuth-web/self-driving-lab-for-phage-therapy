"""Reference command handlers."""

import json
import sys

from .io import _load_candidates


def _fetch_snapshot(args, parser) -> int:
    from ..snapshots import SnapshotError, create_snapshot
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
    from ..candidates import ProviderError, load_snapshot_dir
    from ..snapshots import SnapshotError
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
    from ..biology import read_fasta
    from ..host_profile import load_host_profile
    from ..ranking import RankingError, phist_from_environment
    from ..sequences import SequenceError, SequenceStore
    from ..snapshots import SnapshotError, load_snapshot

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
