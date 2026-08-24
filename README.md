# GenLayer Task Escrow
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/license/mit/)
[![Discord](https://img.shields.io/badge/Discord-Join%20us-5865F2?logo=discord&logoColor=white)](https://discord.gg/8Jm4v89VAu)
[![Telegram](https://img.shields.io/badge/Telegram--T.svg?style=social&logo=telegram)](https://t.me/genlayer)
[![Twitter](https://img.shields.io/twitter/url/https/twitter.com/yeagerai.svg?style=social&label=Follow%20%40GenLayer)](https://x.com/GenLayer)

## About

TaskEscrow is a GenLayer Intelligent Contract that trustlessly pays out for **any** task whose completion can be checked from a web link — not just code or GitHub pull requests. A requester locks real funds against a plain-English description of "done." A worker (human or AI agent) submits a URL as evidence. GenLayer validators fetch that page and use an LLM, under the Equivalence Principle, to independently judge whether the evidence actually satisfies the description — and the contract releases or withholds the escrowed payment automatically, with no human arbiter.

This is a direct implementation of what GenLayer's own docs call its flagship use case — the "Adjudication Layer for the Agentic Economy": paying out escrowed funds once a natural-language-defined deliverable is verifiably complete. Unlike the bounty/PR-specific tooling already in the GenLayer ecosystem, TaskEscrow is domain-agnostic: a landing page deploy, a data-scraping job, a design mockup, a piece of writing, or an AI agent's task output can all be adjudicated the same way, as long as "done" can be checked from a URL.

## How it works

1. **`create_task(description, deadline)`** — payable. The requester locks GEN as the bounty and describes what counts as complete, in natural language.
2. **`claim_task(task_id)`** — a worker claims the task, so only one party can submit evidence for it.
3. **`submit_evidence(task_id, evidence_url)`** — the worker submits a link proving the task is done.
4. **`resolve_task(task_id)`** — validators fetch `evidence_url` and ask an LLM whether it satisfies `description`. Under the Equivalence Principle, leader and validator nodes each run this check independently and must agree on the `satisfied` verdict (free-text reasoning is allowed to vary in wording — only the boolean matters for consensus). If satisfied, the escrowed amount is transferred to the worker immediately; if not, the task is marked `rejected` and the worker can submit new evidence.
5. **`reclaim_expired(task_id)`** — if the deadline passes without an approved submission, the requester can reclaim the locked funds.
6. **`cancel_task(task_id)`** — the requester can cancel and get an instant refund, but only before anyone has claimed the task.

Views (`get_task`, `list_open_tasks`, `get_tasks_by_requester`, `get_tasks_by_worker`) let a frontend or script list and track tasks without needing an indexer.

## What's included

- **`contracts/task_escrow.py`** — the Intelligent Contract described above
- **Direct mode tests** (`tests/direct/test_task_escrow.py`) — 14 fast, in-memory tests covering funding, claiming, evidence submission, LLM-adjudicated approval/rejection, expiry refunds, and cancellation
- **Contract linting** — static analysis to catch common contract issues before deployment
- **CI pipeline** — GitHub Actions workflow for linting and direct tests
- Configuration file template and deployment scripts (`deploy/deployScript.ts`)

## Requirements
- Python >= 3.12
- [GenLayer CLI](https://github.com/genlayerlabs/genlayer-cli) globally installed: `npm install -g genlayer`
- GenLayer Studio (for integration tests and deployment): Install from [Docs](https://docs.genlayer.com/developers/intelligent-contracts/tooling-setup#using-the-genlayer-studio) or use the hosted [GenLayer Studio](https://studio.genlayer.com/)

## Project Structure

```
contracts/
  task_escrow.py         # The TaskEscrow Intelligent Contract
tests/
  direct/                 # Fast in-memory tests (no Studio required)
    test_task_escrow.py    # Full lifecycle: fund, claim, submit, resolve, expire, cancel
  integration/             # Full tests against GenLayer Studio
deploy/                   # TypeScript deployment scripts
gltest.config.yaml         # Test runner network configuration
pyproject.toml             # Python/pytest configuration
.github/workflows/         # CI pipeline
```

## Quick Start

### 1. Set up Python environment

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Lint the contract

```shell
genvm-lint check contracts/task_escrow.py
```

> **Known linter note:** the linter flags the two `gl.nondet.*` calls inside `_verify_evidence`'s `leader_fn` as "not reachable from equivalence principle block." This is a false positive — `leader_fn`/`validator_fn` are passed to `gl.vm.run_nondet_unsafe(...)`, which *is* the equivalence-principle wrapper, matching the exact pattern this repo's own `contracts/PatternTest.py` uses (and which triggers the identical warning there). It's a static-analysis gap in the linter, not a contract defect.

### 3. Run direct mode tests

```shell
pytest tests/direct/ -v
```

All 14 tests run in-memory in well under a second, using `direct_vm.mock_web(...)` / `direct_vm.mock_llm(...)` to simulate evidence pages and LLM verdicts, and `direct_vm.warp(...)` to test deadline expiry.

### 4. Deploy the contract

1. Choose your network: `genlayer network`
2. Deploy: `genlayer deploy` (runs `deploy/deployScript.ts`, which deploys `contracts/task_escrow.py`)

### 5. Run integration tests

```shell
gltest tests/integration/ -v -s
```

Requires GenLayer Studio running (local or hosted).

## Design notes

- **Real escrow, not a points system.** `create_task` is `@gl.public.write.payable` and locks `gl.message.value`; approval pays the worker via `gl.get_contract_at(worker).emit_transfer(value=..., on="finalized")`. Every status transition to a terminal/paid state happens *before* the transfer call (checks-effects-interactions), so a task can't be double-paid.
- **Consensus on a boolean, not free text.** Rather than requiring leader and validator LLM calls to produce byte-identical JSON (`strict_eq`, brittle for subjective judgments) or relying on `prompt_non_comparative` (not exercisable in this SDK's direct-mode test harness at the time of writing), `_verify_evidence` uses `gl.vm.run_nondet_unsafe` with a custom validator that only compares the `satisfied` boolean between leader and validator re-execution — the "partial field matching" pattern documented in `contracts/PatternTest.py`. This is both testable end-to-end in direct mode and more robust to LLM wording variance than exact-match approaches.

## Community
- **[Discord](https://discord.gg/8Jm4v89VAu)**: Discussions, support, and announcements
- **[Telegram](https://t.me/genlayer)**: Informal chats and quick updates

## Documentation
For detailed information, see the [GenLayer documentation](https://docs.genlayer.com/).

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
