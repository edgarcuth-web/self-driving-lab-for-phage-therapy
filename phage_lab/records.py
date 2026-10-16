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


def _evaluate_readout(measurement: dict) -> dict:
    readout = measurement.get("readings")
    if readout is None:
        readout = measurement.get("signal")
    if readout is None:
        return {"quality": "incomplete", "biological_conclusion": "not_assessed"}
    unit = measurement.get("unit")
    if measurement.get("simulated") is True or measurement.get("physical_execution") is False:
        result = {"quality": "virtual_readout_complete", "reading_count": len(readout),
                  "evidence": "none", "biological_conclusion": "not_assessed"}
        if readout and all(isinstance(value, (int, float)) for value in readout):
            result["mean_virtual_signal"] = round(mean(readout), 4)
    else:
        result = {"quality": "measurement_complete", "reading_count": len(readout),
                  "biological_conclusion": "not_assessed"}
        if readout and all(isinstance(value, (int, float)) for value in readout):
            result["mean_signal"] = round(mean(readout), 4)
    if unit is not None:
        result["unit"] = unit
    return result


def evaluate(results: dict) -> dict:
    """Summarize run readouts without inferring a biological conclusion."""

    measurement = results.get("measure", {})
    arms = measurement.get("arms")
    if isinstance(arms, dict) and arms:
        arm_summaries = {
            arm_id: _evaluate_readout(result)
            for arm_id, result in arms.items()
            if isinstance(result, dict)
        }
        qualities = {item.get("quality") for item in arm_summaries.values()}
        if qualities == {"virtual_readout_complete"}:
            quality = "virtual_arm_readouts_complete"
        elif qualities == {"measurement_complete"}:
            quality = "arm_measurements_complete"
        else:
            quality = "arm_readouts_incomplete"
        return {
            "quality": quality,
            "arms": arm_summaries,
            "biological_conclusion": "not_assessed",
        }
    return _evaluate_readout(measurement)
def render_report(report: dict) -> str:
    mode = report.get("execution_mode")
    physical = report.get("physical_execution") is True
    lines = ["# 实验运行报告" if physical else "# 虚拟硬件运行报告", ""]
    if not physical:
        lines.extend([
            "> 本次运行使用软件设备 twin；没有执行物理湿实验。虚拟设备输出不能作为实验或疗效证据。",
            "",
        ])
    lines.extend([f"- 运行编号：`{report['run_id']}`", f"- 流程状态：`{report['status']}`",
                  f"- 决策模式：`{report.get('agent', 'unknown')}`"])
    if mode:
        lines.append(f"- 执行模式：`{mode}`")
    if "physical_execution" in report:
        lines.append(f"- 真实物理执行：`{report['physical_execution']}`")
    if report.get("sample_id"):
        lines.append(f"- 样本编号：`{report['sample_id']}`")
    if report.get("candidate_sources"):
        candidate_sources = "`, `".join(report["candidate_sources"])
        lines.append(f"- 候选来源：`{candidate_sources}`")
    if report.get("material_batch_ids"):
        material_batch_ids = "`, `".join(report["material_batch_ids"])
        lines.append(f"- MaterialBatch：`{material_batch_ids}`")
    lines.extend(["", "## 候选组合", "",
                  ", ".join(report.get("plan", {}).get("candidate_ids", [])) or "未产生计划", "",
                  "## 完成的步骤", ""])
    lines.extend(f"- `{step}`" for step in report["results"])
    if not report["results"]:
        lines.append("尚无完成步骤。")
    lines.extend(["", "## 质量与结果", "", "```json",
                  json.dumps(report["evaluation"], ensure_ascii=False, indent=2), "```", "",
                  "## 恢复记录", "", "```json",
                  json.dumps(report["recoveries"], ensure_ascii=False, indent=2), "```"])
    physical = report.get("physical_state")
    if isinstance(physical, dict):
        # An operator reading this needs to know what they are walking up to
        # before they read anything else about why the run stopped.
        heading = ("## 设备物理状态 — 需要人工处理" if physical.get("operator_action_required")
                   else "## 设备物理状态")
        lines.extend(["", heading, "", f"- 状态：`{physical.get('status')}`",
                      f"- {physical.get('note', '')}"])
        if physical.get("devices"):
            lines.extend(["", "```json",
                          json.dumps(physical["devices"], ensure_ascii=False, indent=2), "```"])
    if report.get("error"):
        lines.extend(["", "## 未完成原因", "", "```json", json.dumps(report["error"], ensure_ascii=False), "```"])
    if report.get("source"):
        lines.extend(["", "## 运行代码版本", "", "```json",
                      json.dumps(report["source"], ensure_ascii=False, indent=2), "```"])
    lines.extend(["", "完整步骤结果见 report.json；顺序事件见 events.jsonl。", ""])
    return "\n".join(lines)
