"""Run command handlers."""

import asyncio
import sys

from ..workflow import WorkflowError, run_experiment
from .io import _load_candidates, _load_material_batches, _load_workflow


def _run(args, parser) -> int:
    spec_mode = args.experiment_spec is not None
    if spec_mode:
        if not args.candidates or args.snapshot:
            parser.error(
                "run --experiment-spec requires --candidates and does not accept --snapshot"
            )
        if args.workflow is not None:
            parser.error(
                "run --experiment-spec uses the workflow locked in the spec; omit --workflow"
            )
    elif bool(args.candidates) == bool(args.snapshot):
        parser.error("run requires exactly one of --candidates or --snapshot")
    if args.material_batches is not None and not spec_mode:
        parser.error("--material-batches requires --experiment-spec")

    missing = [
        name
        for name, value in (
            ("--execution-mode", args.execution_mode),
            ("--sample-id", args.sample_id),
        )
        if not value
    ]
    if not spec_mode and args.snapshot and not args.host:
        missing.append("--host")
    if missing:
        parser.error("run requires " + ", ".join(missing))
    if not 1 <= args.select_min <= args.select_max:
        parser.error("--select-min must be at least 1 and no greater than --select-max")

    from ..agents import AgentError, OpenRouterAgent, RuleAgent
    from ..candidates import ProviderError, load_snapshot_dir
    from ..experiment_spec import load_experiment_spec
    from ..snapshots import SnapshotError

    try:
        agent = RuleAgent() if args.agent == "rule" else OpenRouterAgent.from_environment()
        spec = load_experiment_spec(args.experiment_spec) if spec_mode else None
        material_batches = (
            _load_material_batches(args.material_batches)
            if args.material_batches is not None
            else None
        )
        if spec_mode:
            candidates = _load_candidates(args.candidates)
            workflow = spec.workflow_dict()
        elif args.snapshot:
            provider = load_snapshot_dir(args.snapshot, verify=not args.skip_verify)
            manifest = provider.describe()
            candidates = provider.search(args.host, limit=args.limit)
            print(
                f"候选来自 {manifest['provider']} 快照 {manifest['snapshot_version']}："
                f"{len(candidates)} 条",
                flush=True,
            )
            workflow = _load_workflow(args.workflow)
        else:
            candidates = _load_candidates(args.candidates)
            workflow = _load_workflow(args.workflow)
    except (AgentError, ProviderError, SnapshotError, OSError, ValueError) as exc:
        print(f"无法启动：{exc}", file=sys.stderr)
        return 2

    if args.execution_mode == "virtual_hardware":
        print(
            "VIRTUAL HARDWARE: 设备动作与读数由软件 twin 产生，不是湿实验证据。",
            flush=True,
        )

    try:
        report, directory = asyncio.run(
            run_experiment(
                args.genome,
                args.output_dir,
                sample_id=args.sample_id,
                candidates=candidates,
                devices=None,
                workflow=workflow,
                agent=agent,
                execution_mode=args.execution_mode,
                selection_size=(args.select_min, args.select_max),
                require_snapshot=args.require_snapshot,
                timeout_seconds=args.timeout_seconds,
                echo=not args.quiet,
                experiment_spec=spec,
                material_batches=material_batches,
            )
        )
    except WorkflowError as exc:
        print(f"运行被拒绝：{exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"无法启动或保存报告：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    print(
        f"\n流程状态：{report['status']}\n报告：{directory / 'report.md'}",
        flush=True,
    )
    return 0 if report["status"] == "succeeded" else 2
