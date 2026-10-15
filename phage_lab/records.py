"""Append-only events and final artifacts, with unique per-run directories."""

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRecords:
    def __init__(self, output_root: Path, echo: bool = True, on_event=None):
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:10]
        self.directory = output_root / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self._events = (self.directory / "events.jsonl").open("x", encoding="utf-8")
        self.echo = echo
        self.sequence = 0
        self.on_event = on_event

    def emit(self, event: str, **details) -> None:
        self.sequence += 1
        record = {"seq": self.sequence, "at": utc_now(), "run_id": self.run_id,
                  "event": event, "details": details}
        self._events.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._events.flush()
        if self.on_event is not None:
            self.on_event(record)
        if self.echo:
            print(f"[{self.sequence:02d}] {event} {json.dumps(details, ensure_ascii=False)}", flush=True)

    def finish(self, report: dict) -> None:
        report["run_id"] = self.run_id
        report["finished_at"] = utc_now()
        report["events_file"] = "events.jsonl"
        for name, content in (("report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
                              ("report.md", render_report(report))):
            temporary = self.directory / (name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(self.directory / name)

    def close(self) -> None:
        self._events.close()


def evaluate(results: dict) -> dict:
    readout = results.get("measure", {}).get("readings")
    if readout is None:
        return {"quality": "incomplete", "biological_conclusion": "not_assessed"}
    return {"quality": "synthetic_readout_complete", "reading_count": len(readout),
            "mean_simulated_signal": round(mean(readout), 4),
            "unit": "arbitrary_simulation_units", "biological_conclusion": "not_assessed"}


def render_report(report: dict) -> str:
    lines = ["# 模拟实验运行报告", "", "> 全部候选、合成订单、设备及读数均为模拟。不能据此判断感染率或疗效。", "",
             f"- 运行编号：`{report['run_id']}`", f"- 流程状态：`{report['status']}`",
             f"- 决策模式：`{report['agent']}`", f"- 随机种子：`{report['seed']}`",
             f"- 实际注入故障次数：`{report['fault']['injected_count']}`", "",
             "## 候选组合", "", ", ".join(report.get("plan", {}).get("candidate_ids", [])) or "未产生计划", "",
             "## 完成的步骤", ""]
    lines.extend(f"- `{step}`" for step in report["results"])
    if not report["results"]:
        lines.append("尚无完成步骤。")
    lines.extend(["", "## 质量与结果", "", "```json",
                  json.dumps(report["evaluation"], ensure_ascii=False, indent=2), "```", "",
                  "## 恢复记录", "", "```json",
                  json.dumps(report["recoveries"], ensure_ascii=False, indent=2), "```"])
    if report.get("error"):
        lines.extend(["", "## 未完成原因", "", "```json", json.dumps(report["error"], ensure_ascii=False), "```"])
    if report.get("source"):
        lines.extend(["", "## 运行代码版本", "", "```json",
                      json.dumps(report["source"], ensure_ascii=False, indent=2), "```"])
    lines.extend(["", "完整步骤结果见 report.json；顺序事件见 events.jsonl。", ""])
    return "\n".join(lines)
