# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from datetime import date
from genlayer import *


@allow_storage
@dataclass
class Task:
    id: str
    requester: Address
    worker: Address
    description: str
    evidence_url: str
    amount: u256
    status: str
    deadline: str
    reasoning: str


class TaskEscrow(gl.Contract):
    tasks: TreeMap[str, Task]
    task_count: u256

    def __init__(self):
        self.task_count = u256(0)

    def _verify_evidence(self, description: str, evidence_url: str) -> bool:
        def get_verdict() -> str:
            web_data = gl.nondet.web.render(evidence_url, mode="text")

            verdict = gl.nondet.exec_prompt(
                f"""
Task description (what counts as "done"):
{description}

Evidence content fetched from the submitted URL:
{web_data}

Decide whether the evidence demonstrates the task was completed as described.
Respond in JSON:
{{
    "satisfied": bool
}}
It is mandatory that you respond only using the JSON format above,
nothing else. Don't include any other words or characters,
your output must be only JSON without any formatting prefix or suffix.
This result should be perfectly parsable by a JSON parser without errors.
""",
                response_format="json",
            )
            satisfied = verdict.get("satisfied")
            # Require an actual JSON boolean rather than coercing arbitrary
            # values with bool(...): a malformed or malicious LLM response
            # like {"satisfied": "false"} would coerce to True under
            # Python truthiness (any non-empty string is truthy), silently
            # flipping a rejection into an approval. Reject anything that
            # isn't literally true/false instead of guessing.
            if not isinstance(satisfied, bool):
                raise gl.vm.UserError(
                    "LLM response 'satisfied' field must be a JSON boolean"
                )

            # Only the boolean verdict is part of the equivalence-checked
            # value. Free-text reasoning is deliberately excluded here: two
            # independent LLM calls (leader and validator) should agree on
            # *whether* the evidence satisfies the task, but strict_eq
            # requires byte-identical output, and open-ended text would
            # rarely match word-for-word between calls.
            return json.dumps({"satisfied": satisfied}, sort_keys=True)

        result_json = json.loads(gl.eq_principle.strict_eq(get_verdict))
        satisfied = result_json["satisfied"]
        if not isinstance(satisfied, bool):
            raise gl.vm.UserError("Equivalence-checked verdict was not a boolean")
        return satisfied

    def _current_date(self) -> str:
        return str(gl.message_raw["datetime"])[:10]

    def _is_expired(self, deadline: str) -> bool:
        return self._current_date() >= deadline

    def _validate_future_deadline(self, deadline: str) -> None:
        try:
            parsed = date.fromisoformat(deadline)
        except (ValueError, TypeError):
            raise gl.vm.UserError(
                "Deadline must be a valid ISO date in YYYY-MM-DD format"
            )
        # str(parsed) re-normalizes to zero-padded YYYY-MM-DD so this
        # compares correctly even if the input had, e.g., single-digit
        # month/day accepted by fromisoformat in a lenient parser build.
        if str(parsed) <= self._current_date():
            raise gl.vm.UserError("Deadline must be in the future")

    @gl.public.write.payable
    def create_task(self, description: str, deadline: str) -> str:
        if gl.message.value <= 0:
            raise gl.vm.UserError("Task must be funded with a positive amount")
        if not description.strip():
            raise gl.vm.UserError("Description cannot be empty")
        self._validate_future_deadline(deadline)

        task_id = f"task_{int(self.task_count)}"
        self.task_count = u256(int(self.task_count) + 1)

        self.tasks[task_id] = Task(
            id=task_id,
            requester=gl.message.sender_address,
            worker=Address("0x0000000000000000000000000000000000000000"),
            description=description,
            evidence_url="",
            amount=u256(gl.message.value),
            status="open",
            deadline=deadline,
            reasoning="",
        )
        return task_id

    @gl.public.write
    def claim_task(self, task_id: str) -> None:
        task = self.tasks[task_id]
        if task.status != "open":
            raise gl.vm.UserError("Task is not open for claiming")
        # Blocking claim/submit/approve once the deadline has passed keeps
        # reclaim_expired the only path that can move funds after expiry —
        # otherwise a worker could still get paid via resolve_task in the
        # same window the requester reclaims via reclaim_expired, racing
        # two transfers of the same escrowed amount.
        if self._is_expired(task.deadline):
            raise gl.vm.UserError("Task deadline has passed; it can no longer be claimed")

        task.worker = gl.message.sender_address
        task.status = "claimed"

    @gl.public.write
    def submit_evidence(self, task_id: str, evidence_url: str) -> None:
        task = self.tasks[task_id]
        if task.worker != gl.message.sender_address:
            raise gl.vm.UserError("Only the assigned worker can submit evidence")
        if task.status not in ("claimed", "rejected"):
            raise gl.vm.UserError("Task is not awaiting evidence")
        if not evidence_url.strip():
            raise gl.vm.UserError("Evidence URL cannot be empty")
        if self._is_expired(task.deadline):
            raise gl.vm.UserError(
                "Task deadline has passed; evidence can no longer be submitted"
            )

        task.evidence_url = evidence_url
        task.status = "submitted"

    @gl.public.write
    def resolve_task(self, task_id: str) -> bool:
        task = self.tasks[task_id]
        if task.status != "submitted":
            raise gl.vm.UserError("Task has no evidence pending resolution")
        if self._is_expired(task.deadline):
            raise gl.vm.UserError(
                "Task deadline has passed; the requester must use reclaim_expired"
            )

        satisfied = self._verify_evidence(task.description, task.evidence_url)

        if satisfied:
            task.status = "approved"
            task.reasoning = "Validators agreed the submitted evidence satisfies the task description."
            gl.get_contract_at(task.worker).emit_transfer(
                value=u256(int(task.amount)), on="finalized"
            )
        else:
            task.status = "rejected"
            task.reasoning = "Validators agreed the submitted evidence does not satisfy the task description."

        return satisfied

    @gl.public.write
    def reclaim_expired(self, task_id: str) -> None:
        task = self.tasks[task_id]
        if task.requester != gl.message.sender_address:
            raise gl.vm.UserError("Only the requester can reclaim funds")
        if task.status == "approved":
            raise gl.vm.UserError("Task was already approved and paid out")
        if task.status in ("refunded", "cancelled"):
            raise gl.vm.UserError("Task funds were already returned")
        if not self._is_expired(task.deadline):
            raise gl.vm.UserError("Task deadline has not passed yet")

        task.status = "refunded"
        gl.get_contract_at(task.requester).emit_transfer(
            value=u256(int(task.amount)), on="finalized"
        )

    @gl.public.write
    def cancel_task(self, task_id: str) -> None:
        task = self.tasks[task_id]
        if task.requester != gl.message.sender_address:
            raise gl.vm.UserError("Only the requester can cancel")
        if task.status != "open":
            raise gl.vm.UserError("Task can only be cancelled while open (not yet claimed)")

        task.status = "cancelled"
        gl.get_contract_at(task.requester).emit_transfer(
            value=u256(int(task.amount)), on="finalized"
        )

    @gl.public.view
    def get_task(self, task_id: str) -> Task:
        return self.tasks[task_id]

    @gl.public.view
    def list_open_tasks(self) -> list:
        return [t for t in self.tasks.values() if t.status == "open"]

    @gl.public.view
    def get_tasks_by_requester(self, address: str) -> list:
        addr = Address(address)
        return [t for t in self.tasks.values() if t.requester == addr]

    @gl.public.view
    def get_tasks_by_worker(self, address: str) -> list:
        addr = Address(address)
        return [t for t in self.tasks.values() if t.worker == addr]
