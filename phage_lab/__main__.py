"""Command-line entry point for real execution and the explicit simulation harness."""

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys

from .simulation import FAULT_MODES, OPERATIONS
from .workflow import run_demo


def scale(value: str) -> float:
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("time scale must be a number") from None
    if not math.isfinite(result) or not 0.01 <= result <= 10:
        raise argparse.ArgumentTypeError("time scale must be between 0.01 and 10")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Self-driving laboratory orchestration for phage research.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "demo", "dashboard", "version"])
    parser.add_argument("--genome", type=Path,
                        default=Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta")
    parser.add_argument("--agent", choices=["rule", "openrouter"], default="rule")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fault", choices=FAULT_MODES, default="hang")
    parser.add_argument("--fault-step", choices=OPERATIONS)
    parser.add_argument("--time-scale", type=scale, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    parser.add_argument("--port", type=int, default=8765, help="Local dashboard port")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the dashboard")
    args = parser.parse_args(argv)

    if args.command == "version":
        from .provenance import source_identity
        print(json.dumps(source_identity(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "run":
        print(
            "真实运行不会回退到模拟器。当前仓库尚未配置具体仪器驱动和候选数据源；"
            "请通过 phage_lab.workflow.run_experiment 注入真实 drivers/candidates，"
            "或先实现对应 adapter。",
            file=sys.stderr,
        )
        return 2

    if args.command == "dashboard":
        if not 1024 <= args.port <= 65535:
            parser.error("dashboard port must be between 1024 and 65535")
        from .dashboard import serve
        try:
            serve(args.output_dir, args.port, args.time_scale, open_browser=not args.no_browser)
        except OSError as exc:
            print(f"面板无法启动：{exc}\n若端口已被占用，可以添加 --port 8766。", file=sys.stderr)
            return 2
        return 0

    print("SIMULATION TEST HARNESS: 候选、订单、设备和读数均为模拟。", flush=True)
    print("决策模式：" + ("离线规则（没有调用 AI）" if args.agent == "rule" else "OpenRouter API（真实模型调用）"), flush=True)
    try:
        report, directory = asyncio.run(run_demo(
            args.genome, args.output_dir, seed=args.seed, fault=args.fault,
            fault_step=args.fault_step, agent_mode=args.agent, time_scale=args.time_scale))
    except (OSError, ValueError) as exc:
        print(f"无法启动或保存报告：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    print(f"\n流程状态：{report['status']}\n报告：{directory / 'report.md'}", flush=True)
    return 0 if report["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
