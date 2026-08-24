# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from genlayer import *
import genlayer.gl.vm as glvm


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

    def _verify_evidence(self, description: str, evidence_url: str) -> dict:
        def leader_fn() -> dict:
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
    "satisfied": bool,
    "reasoning": str
}}
It is mandatory that you respond only using the JSON format above,
nothing else. Don't include any other words or characters,
your output must be only JSON without any formatting prefix or suffix.
This result should be perfectly parsable by a JSON parser without errors.
""",
                response_format="json",
            )
            return {
                "satisfied": bool(verdict.get("satisfied")),
                "reasoning": str(verdict.get("reasoning", "")),
            }

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, glvm.Return):
                return False
            # Partial field matching: only the "satisfied" verdict needs to
            # match between leader and validator re-execution. Free-text
            # "reasoning" is expected to vary in wording between independent
            # LLM calls, so it is excluded from the consensus comparison.
            v = leader_fn()
            return leader_result.calldata["satisfied"] == v["satisfied"]

        return glvm.run_nondet_unsafe(leader_fn, validator_fn)

    def _is_expired(self, deadline: str) -> bool:
        now_date = str(gl.message_raw["datetime"])[:10]
        return now_date >= deadline

    @gl.public.write.payable
    def create_task(self, description: str, deadline: str) -> str:
        if gl.message.value <= 0:
            raise gl.vm.UserError("Task must be funded with a positive amount")
        if not description.strip():
            raise gl.vm.UserError("Description cannot be empty")

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

        task.evidence_url = evidence_url
        task.status = "submitted"

    @gl.public.write
    def resolve_task(self, task_id: str) -> dict:
        task = self.tasks[task_id]
        if task.status != "submitted":
            raise gl.vm.UserError("Task has no evidence pending resolution")

        verdict = self._verify_evidence(task.description, task.evidence_url)
        task.reasoning = str(verdict.get("reasoning", ""))

        if bool(verdict.get("satisfied")):
            task.status = "approved"
            gl.get_contract_at(task.worker).emit_transfer(
                value=u256(int(task.amount)), on="finalized"
            )
        else:
            task.status = "rejected"

        return verdict

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
