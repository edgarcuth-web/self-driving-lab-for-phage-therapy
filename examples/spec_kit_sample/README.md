# Spec Kit 样例：Two-Round Closed Loop with Live Dashboard

**这是一个样例，不是一个已立项的特性。**

## 它是什么

一份完整的 Spec Kit 产物样例，用来演示本仓库的 spec-driven 流程长什么样：

```
examples/spec_kit_sample/
├── spec.md              # what & why（US1–US5 + Given/When/Then + Edge Cases + FR + SC）
├── plan.md              # how（Technical Context / Constitution Check / Project Structure / 所有权 / 风险）
├── research.md          # Phase 0 实测依据
├── tasks.md             # 按 user story 分阶段（T001–T022，[P]/[USn]）
├── contracts/           # 冻结接口契约 5 份
└── checklists/
    └── requirements.md  # 需求质量清单
```

## 它不是什么

- **不是已批准的工作项**：没有 issue 编号，未走本仓库的 issue 流程。
- **没有实现**：`tasks.md` 中 T001–T022 全部未执行；`plan.md` 点名的 `phage_lab/demo.py`、`phage_lab/server.py`、`phage_lab/feedback.py`、`web/`、`examples/fixtures/`、`scripts/smoke.sh` 均不存在。
- **不占用 `specs/` 正式编号位**：它原先位于 `specs/001-round2-loop-dashboard/`，为避免被误当作正式特性，已降级迁到此处。

## 来源（可追溯）

1. 最早是一套仓库内未跟踪的黑客松演练文档 `docs/hackathon/`（含 `PLAYBOOK.md` / `INTERFACE-CONTRACT.md` / `SCOREBOARD.md`）。
2. 2026-10-17 的 Spec Kit 集成会话中，先把它们重组为 `docs/agent_colab/` 并补出 Spec Kit 式骨架。
3. 用户指示"改造成 speckit"后，该骨架被迁入 `specs/001-round2-loop-dashboard/`，内容基本是重写格式而非新建需求。
4. 随后按用户指示由 `specs/` 降级到此目录作为样例。

`docs/hackathon/`、`docs/agent_colab/` 均已不在磁盘上。

## 怎么用它

- **当模板**：复制一份到 `specs/NNN-<feature>/`，按真实 issue 重写 `spec.md` 的 Input 与验收，再逐条执行 `tasks.md`。
- **当流程参照**：看 `plan.md` 的 Constitution Check 一栏如何对齐 [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md)。
- **当命令验证物**：`.specify/scripts/powershell/check-prerequisites.ps1 -Json` 曾在原位解析通过（`FEATURE_DIR` / `AVAILABLE_DOCS`）。

> 若把它重新提升为正式特性，必须先补 issue 编号，再按 `AGENTS.md` 建分支。
