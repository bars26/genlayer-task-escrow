"""Direct-mode tests for the TaskEscrow contract."""

CONTRACT_PATH = "contracts/task_escrow.py"


def test_create_task_locks_value(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    direct_vm.value = 1000
    contract = direct_deploy(CONTRACT_PATH)

    task_id = contract.create_task("Deploy a landing page and share the URL", "2099-01-01")

    task = contract.get_task(task_id)
    assert task.status == "open"
    assert int(task.amount) == 1000
    assert task.evidence_url == ""
    assert task.description == "Deploy a landing page and share the URL"


def test_create_task_requires_positive_value(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    direct_vm.value = 0
    contract = direct_deploy(CONTRACT_PATH)

    with direct_vm.expect_revert("Task must be funded with a positive amount"):
        contract.create_task("Do something", "2099-01-01")


def test_create_task_requires_description(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)

    with direct_vm.expect_revert("Description cannot be empty"):
        contract.create_task("   ", "2099-01-01")


def test_claim_task_assigns_worker(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)

    task = contract.get_task(task_id)
    assert task.status == "claimed"


def test_claim_task_blocks_second_worker(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)

    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("Task is not open for claiming"):
        contract.claim_task(task_id)


def test_submit_evidence_requires_assigned_worker(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)

    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("Only the assigned worker can submit evidence"):
        contract.submit_evidence(task_id, "https://example.com/proof")


def test_submit_evidence_updates_status(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)
    contract.submit_evidence(task_id, "https://example.com/proof")

    task = contract.get_task(task_id)
    assert task.status == "submitted"
    assert task.evidence_url == "https://example.com/proof"


def test_cancel_task_before_claim_refunds_requester(direct_vm, direct_deploy, direct_alice):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    contract.cancel_task(task_id)

    task = contract.get_task(task_id)
    assert task.status == "cancelled"


def test_cancel_task_blocked_once_claimed(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)

    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Task can only be cancelled while open"):
        contract.cancel_task(task_id)


def test_reclaim_expired_blocked_before_deadline(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)

    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Task deadline has not passed yet"):
        contract.reclaim_expired(task_id)


def test_reclaim_expired_after_deadline(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Write a blog post", "2024-01-01")

    direct_vm.warp("2024-06-01T00:00:00")
    direct_vm.sender = direct_alice
    contract.reclaim_expired(task_id)

    task = contract.get_task(task_id)
    assert task.status == "refunded"


def test_list_open_tasks(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    contract.create_task("Task one", "2099-01-01")

    direct_vm.value = 700
    contract.create_task("Task two", "2099-01-01")

    open_tasks = contract.list_open_tasks()
    assert len(open_tasks) == 2


def test_resolve_task_approves_and_pays_worker(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    direct_vm.mock_web(r".*example\.com.*", {"status": 200, "body": "Landing page is live and looks great."})
    direct_vm.mock_llm(r".*", '{"satisfied": true}')

    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Deploy a landing page", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)
    contract.submit_evidence(task_id, "https://example.com/proof")

    contract.resolve_task(task_id)

    task = contract.get_task(task_id)
    assert task.status == "approved"
    assert "satisfies" in task.reasoning.lower()


def test_resolve_task_rejects_and_allows_resubmit(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    direct_vm.mock_web(r".*example\.com.*", {"status": 200, "body": "This page is empty."})
    direct_vm.mock_llm(r".*", '{"satisfied": false}')

    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract = direct_deploy(CONTRACT_PATH)
    task_id = contract.create_task("Deploy a landing page", "2099-01-01")

    direct_vm.sender = direct_bob
    direct_vm.value = 0
    contract.claim_task(task_id)
    contract.submit_evidence(task_id, "https://example.com/proof")
    contract.resolve_task(task_id)

    task = contract.get_task(task_id)
    assert task.status == "rejected"

    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*example\.com.*", {"status": 200, "body": "Now the page is live."})
    direct_vm.mock_llm(r".*", '{"satisfied": true}')

    contract.submit_evidence(task_id, "https://example.com/proof-v2")
    task = contract.get_task(task_id)
    assert task.status == "submitted"
