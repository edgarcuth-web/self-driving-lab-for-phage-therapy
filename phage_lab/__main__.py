"""Run with python -m phage_lab demo from the repository root."""

import argparse
import asyncio
import math
from pathlib import Path
import sys

from .devices import FAULT_MODES, OPERATIONS
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
    parser = argparse.ArgumentParser(description="Simulated lab workflow with visible fault recovery.")
    parser.add_argument("command", nargs="?", default="demo", choices=["demo"])
    parser.add_argument("--genome", type=Path,
                        default=Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta")
    parser.add_argument("--agent", choices=["rule", "anthropic"], default="rule")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fault", choices=FAULT_MODES, default="hang")
    parser.add_argument("--fault-step", choices=OPERATIONS)
    parser.add_argument("--time-scale", type=scale, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    print("SIMULATION: 候选、订单、设备和读数均为模拟。", flush=True)
    print("决策模式：" + ("离线规则（没有调用 AI）" if args.agent == "rule" else "Claude API（真实模型调用）"), flush=True)
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
