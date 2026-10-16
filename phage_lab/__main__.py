"""Command-line entry point for experiment orchestration."""

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


def _load_json(path: Path, label: str):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{label} file exceeds the {MAX_INPUT_BYTES // 1_000_000} MB limit.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} file is not valid JSON: {exc}") from None


def _load_candidates(path: Path) -> list[dict]:
    """Load externally supplied candidate records.

    This is a stopgap entry point: it reads records someone else retrieved. It
    does not fetch anything, so the provenance fields in the file are only as
    honest as whoever wrote it. A CandidateProvider that queries a real
    database and stamps provenance itself is the next piece of work.
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-driving laboratory orchestration for phage research.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "version"])
    parser.add_argument("--genome", type=Path,
                        default=Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta",
                        help="Host bacterial FASTA; only a hash and summary are retained.")
    parser.add_argument("--candidates", type=Path,
                        help="JSON array of externally supplied candidate records.")
    parser.add_argument("--execution-mode", choices=EXECUTION_MODES,
                        help="Required for a run. No default: state which hardware you expect.")
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
    args = parser.parse_args(argv)

    if args.command == "version":
        from .provenance import source_identity
        print(json.dumps(source_identity(), ensure_ascii=False, indent=2))
        return 0

    missing = [name for name, value in (("--candidates", args.candidates),
                                        ("--execution-mode", args.execution_mode),
                                        ("--sample-id", args.sample_id)) if not value]
    if missing:
        parser.error("run requires " + ", ".join(missing))
    if not 1 <= args.select_min <= args.select_max:
        parser.error("--select-min must be at least 1 and no greater than --select-max")

    from .agents import AgentError, OpenRouterAgent, RuleAgent
    try:
        agent = RuleAgent() if args.agent == "rule" else OpenRouterAgent.from_environment()
        candidates = _load_candidates(args.candidates)
        workflow = _load_workflow(args.workflow)
    except (AgentError, OSError, ValueError) as exc:
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
            timeout_seconds=args.timeout_seconds))
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


if __name__ == "__main__":
    raise SystemExit(main())
