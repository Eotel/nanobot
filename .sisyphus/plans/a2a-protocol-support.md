# A2A Protocol Support Plan for nanobot

## TL;DR

> **Quick Summary**: Current nanobot has internal multi-agent orchestration (`SpawnTool` + `SubagentManager` + `MessageBus`) and channel bridges, but it does not expose standards-compliant A2A protocol endpoints. This plan adds an A2A server surface with strict MVP boundaries and TDD-first verification.
>
> **Deliverables**:
> - A2A discovery endpoint (`/.well-known/agent-card.json`)
> - A2A core task operations (`send/get/list/cancel`) mapped to existing `AgentLoop`
> - Task lifecycle state machine and cancellation behavior
> - Authentication, input limits, and protocol error mapping
> - Contract/integration/regression tests and rollout docs
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 -> Task 2 -> Task 4 -> Task 5 -> Task 7

---

## Context

### Original Request
- Investigate whether communication via A2A protocol is already possible.
- If not possible, create a plan to add A2A functionality.

### Interview Summary
**Key Discussions**:
- Internal agent-to-agent style behavior exists through subagents and the message bus.
- Existing external bridge pattern exists for WhatsApp via WebSocket.
- No direct evidence of A2A protocol surfaces was found.

**Research Findings**:
- Existing internal orchestration:
  - `nanobot/agent/subagent.py:20`
  - `nanobot/agent/tools/spawn.py:11`
  - `nanobot/bus/events.py:8`
  - `nanobot/bus/queue.py:11`
- Existing transport adapter pattern:
  - `nanobot/channels/whatsapp.py:15`
  - `bridge/src/server.ts:19`
  - `bridge/src/index.ts:1`
- Runtime and extension anchors:
  - `nanobot/cli/commands.py:321`
  - `nanobot/channels/base.py:12`
  - `nanobot/channels/manager.py:19`
  - `nanobot/config/schema.py:185`
- Negative evidence (A2A protocol artifacts absent): no repository matches for
  - `jsonrpc`
  - `/.well-known/agent-card.json`
  - `SendMessage`, `GetTask`, `ListTasks`, `CancelTask`
  - `A2A-Version`

### Metis Review
**Identified Gaps (addressed in this plan)**:
- Lock A2A spec/version and method/binding early to avoid drift.
- Prevent scope creep with explicit MUST/MUST NOT boundaries.
- Define task-state mapping before implementation tasks.
- Add protocol contract tests as source-of-truth for compatibility claims.
- Include cancellation race/error handling and unsupported content behavior.

---

## Work Objectives

### Core Objective
Expose a standards-aligned A2A server interface in nanobot while reusing current `AgentLoop` and `MessageBus` internals, and preserving existing channel behavior.

### Concrete Deliverables
- A2A adapter module under `nanobot/a2a/` (new package)
- Discovery endpoint `/.well-known/agent-card.json`
- Core task methods: send/get/list/cancel (MVP)
- A2A task lifecycle store (MVP in-memory)
- Auth and security controls in config/runtime
- TDD contract, integration, and regression test suites
- Updated operator/developer documentation

### Definition of Done
- [x] `python -m pytest tests/a2a -q` passes (36 tests)
- [x] `python -m pytest tests -q` passes (52 tests, no regressions)
- [x] A2A endpoint tests pass for discovery + core operations
- [x] Existing channels still boot and route messages with A2A disabled

### Must Have
- Protocol/version lock at the beginning of implementation
- Text-only MVP payload support with explicit unsupported-type errors
- Explicit task state transitions and cancellation semantics
- Bearer-token auth option and safe defaults
- Zero manual verification steps in acceptance criteria

### Must NOT Have (Guardrails)
- No A2A client/federation implementation in this phase
- No broad refactor of `AgentLoop`/`MessageBus` internals
- No multimodal/file payload support in MVP
- No persistent DB requirement for MVP task state
- No breaking behavior change for existing channel integrations

---

## Verification Strategy (MANDATORY)

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
>
> All verification in this plan is agent-executed via commands/tools only.
> No manual browser clicks, no “user visually checks”, no human-in-the-loop acceptance checks.

### Test Decision
- **Infrastructure exists**: YES (`pytest` in `pyproject.toml` and existing `tests/`)
- **Automated tests**: TDD
- **Framework**: `pytest` + `pytest-asyncio`

### TDD Structure for Each Implementation Task
1. **RED**: add/extend failing protocol test first
2. **GREEN**: implement minimum code to pass
3. **REFACTOR**: cleanup while keeping tests green

### Agent-Executed QA Scenarios (applies to every task)
- Frontend/UI: N/A for this plan
- API/Backend: `curl` + `pytest`
- CLI/TUI: shell commands for startup/health checks

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation):
├── Task 1: Protocol lock + scope guardrails
└── Task 2: Runtime/config scaffolding

Wave 2 (Core Build):
├── Task 3: Agent Card discovery endpoint
├── Task 4: Task store + state machine mapping
└── Task 6: Auth/limits/error policy (depends on Task 2, can start before Task 5)

Wave 3 (Integration + Quality):
├── Task 5: send/get/list/cancel method implementation
├── Task 7: Contract/integration/regression suite
└── Task 8: Documentation + rollout notes

Critical Path: 1 -> 2 -> 4 -> 5 -> 7
Parallel Speedup: ~30-40% vs pure sequential
```

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|----------------------|
| 1 | None | 2,3,4,5,6,7,8 | 2 |
| 2 | 1 | 3,4,5,6,7 | 1 |
| 3 | 2 | 7,8 | 4,6 |
| 4 | 2 | 5,7 | 3,6 |
| 5 | 4 | 7,8 | 6 |
| 6 | 2 | 7,8 | 3,4,5 |
| 7 | 3,4,5,6 | 8 | None |
| 8 | 3,5,6,7 | None | None |

### Agent Dispatch Summary

| Wave | Tasks | Recommended Agents |
|------|-------|--------------------|
| 1 | 1,2 | `task(category="unspecified-high", load_skills=["git-master"], run_in_background=false)` |
| 2 | 3,4,6 | dispatch in parallel after Wave 1 |
| 3 | 5,7,8 | dispatch in sequence for integration quality gates |

---

## TODOs

- [x] 1. Lock A2A Protocol Contract and MVP Scope

  **What to do**:
  - Define target A2A spec/version and binding used in this repo for MVP.
  - Freeze method names, payload shapes, error code mapping, and unsupported capability behavior.
  - Produce a short implementation contract markdown used by all subsequent tasks.

  **Must NOT do**:
  - Do not implement code before contract is frozen.
  - Do not include streaming/push/client-mode in MVP contract.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: protocol-level design with cross-cutting impact.
  - **Skills**: [`git-master`]
    - `git-master`: enforce disciplined atomic commits around contract changes.
  - **Skills Evaluated but Omitted**:
    - `playwright`: no browser flow in this task.
    - `frontend-ui-ux`: no UI design work.
    - `dev-browser`: no browser automation required.

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: 2,3,4,5,6,7,8
  - **Blocked By**: None

  **References**:
  - `nanobot/agent/loop.py:25` - execution engine to preserve; avoid core refactor.
  - `nanobot/bus/events.py:8` - internal message contract to map from A2A.
  - `nanobot/channels/base.py:61` - existing allow-list security pattern.
  - `https://a2a-protocol.org/latest/specification/` - canonical protocol behavior.
  - `https://a2a-protocol.org/latest/topics/agent-discovery/` - discovery card requirements.
  - `https://github.com/a2aproject/A2A/blob/main/specification/a2a.proto` - field-level schema baseline.

  **Acceptance Criteria**:
  - [x] Protocol lock document exists and names exact MVP methods and response/error contracts.
  - [x] Scope section explicitly lists out-of-scope features.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Contract document completeness
    Tool: Bash
    Preconditions: repository checked out
    Steps:
      1. Verify contract file exists under docs/planning path chosen in implementation.
      2. Grep for required sections: version, methods, errors, out-of-scope.
      3. Assert all required headings are present.
    Expected Result: single authoritative protocol contract exists
    Failure Indicators: missing required headings or undefined methods
    Evidence: captured grep output in .sisyphus/evidence/task-1-contract-check.txt

  Scenario: Scope guardrails enforce MVP boundaries
    Tool: Bash
    Preconditions: contract file committed in working branch
    Steps:
      1. Assert contract lists streaming/push/client mode as out-of-scope.
      2. Assert text-only payload policy is explicit.
    Expected Result: guardrails are explicit and machine-verifiable
    Evidence: .sisyphus/evidence/task-1-guardrails.txt
  ```

  **Commit**: YES
  - Message: `docs(a2a): lock protocol contract and MVP boundaries`
  - Files: `docs/a2a-contract.md` (or equivalent path selected during execution)
  - Pre-commit: `python -m pytest -q`

- [x] 2. Add A2A Runtime Config and Gateway Wiring

  **What to do**:
  - Extend config schema with A2A block (`enabled`, `host`, `port`, `auth`, `limits`, `version`).
  - Wire A2A runtime startup/shutdown into gateway lifecycle.
  - Ensure disabled-by-default behavior.

  **Must NOT do**:
  - Do not break existing channel startup in `ChannelManager`.
  - Do not force A2A startup unless enabled.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: startup lifecycle and configuration are high-impact integration points.
  - **Skills**: [`git-master`]
    - `git-master`: manage safe incremental commits across config/runtime wiring.
  - **Skills Evaluated but Omitted**:
    - `dev-browser`: not needed for backend runtime wiring.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: 3,4,5,6,7
  - **Blocked By**: 1

  **References**:
  - `nanobot/config/schema.py:185` - root config pattern for adding new sections.
  - `nanobot/cli/commands.py:321` - `gateway` lifecycle where services are started/stopped.
  - `nanobot/channels/manager.py:140` - async startup model to mirror for A2A service lifecycle.

  **Acceptance Criteria**:
  - [x] New A2A config keys parse correctly through existing config loader.
  - [x] `nanobot gateway` runs unchanged when A2A disabled.
  - [x] `nanobot gateway` starts A2A service when enabled.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Gateway boot unaffected when A2A disabled
    Tool: Bash
    Preconditions: config has a2a.enabled=false
    Steps:
      1. Start gateway process.
      2. Wait for startup logs.
      3. Assert process remains healthy for 10s.
      4. Stop process and assert clean exit code 0.
    Expected Result: no regressions in baseline startup behavior
    Evidence: .sisyphus/evidence/task-2-gateway-disabled.log

  Scenario: Gateway boots A2A service when enabled
    Tool: Bash
    Preconditions: config has a2a.enabled=true with test port
    Steps:
      1. Start gateway process.
      2. Assert A2A startup log includes host/port.
      3. Probe A2A listen port with curl health/discovery endpoint.
    Expected Result: A2A listener reachable
    Evidence: .sisyphus/evidence/task-2-a2a-enabled.log
  ```

  **Commit**: YES
  - Message: `feat(a2a): add config schema and gateway lifecycle wiring`
  - Files: `nanobot/config/schema.py`, `nanobot/cli/commands.py`, new `nanobot/a2a/*`
  - Pre-commit: `python -m pytest tests -q`

- [x] 3. Implement Agent Card Discovery Endpoint

  **What to do**:
  - Add `GET /.well-known/agent-card.json` endpoint.
  - Include required fields (`name`, `description`, `version`, interfaces, capabilities, skills, input/output modes).
  - Reflect enabled auth scheme and unsupported capabilities accurately.

  **Must NOT do**:
  - Do not advertise capabilities that are not implemented.
  - Do not expose secrets/tokens in Agent Card.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: protocol compliance and security metadata correctness.
  - **Skills**: [`git-master`]
    - `git-master`: keep protocol metadata changes isolated and reviewable.
  - **Skills Evaluated but Omitted**:
    - `playwright`: no UI path.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with 4,6)
  - **Blocks**: 7,8
  - **Blocked By**: 2

  **References**:
  - `https://a2a-protocol.org/latest/topics/agent-discovery/` - required discovery endpoint behavior.
  - `https://a2a-protocol.org/latest/specification/` - required Agent Card field semantics.
  - `nanobot/providers/registry.py` - provider/capability metadata style to mirror.
  - `nanobot/config/schema.py:141` - config source for version/host/feature flags.

  **Acceptance Criteria**:
  - [x] Discovery endpoint returns valid JSON with required fields.
  - [x] `supportedInterfaces` and protocol version match locked contract.
  - [x] `capabilities` accurately reflect MVP (`streaming=false` unless implemented).

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Discovery endpoint returns required fields
    Tool: Bash (curl + jq)
    Preconditions: gateway running with A2A enabled on localhost:8088
    Steps:
      1. GET http://127.0.0.1:8088/.well-known/agent-card.json
      2. Assert status code 200.
      3. Assert JSON has keys: name, description, version, supportedInterfaces, capabilities, defaultInputModes, defaultOutputModes, skills.
      4. Assert supportedInterfaces[0].protocolVersion equals locked version.
    Expected Result: compliant discovery response
    Evidence: .sisyphus/evidence/task-3-agent-card.json

  Scenario: Unsupported capabilities are not falsely advertised
    Tool: Bash (jq)
    Preconditions: streaming not implemented in MVP
    Steps:
      1. Parse discovery payload.
      2. Assert .capabilities.streaming == false.
      3. Assert .capabilities.pushNotifications == false.
    Expected Result: truthful capability declaration
    Evidence: .sisyphus/evidence/task-3-capability-check.txt
  ```

  **Commit**: YES
  - Message: `feat(a2a): add agent card discovery endpoint`
  - Files: `nanobot/a2a/*`, tests under `tests/a2a/*`
  - Pre-commit: `python -m pytest tests/a2a -q`

- [x] 4. Build A2A Task Store and State Machine Mapping

  **What to do**:
  - Create in-memory task store keyed by `task_id`.
  - Implement explicit state transitions (`submitted`, `working`, `completed`, `failed`, `canceled`).
  - Define mapping between A2A message/task input and internal `AgentLoop` execution calls.
  - Implement cancellation behavior for running tasks (best-effort with clear terminal state).

  **Must NOT do**:
  - Do not bypass `AgentLoop` with alternate response generation logic.
  - Do not silently drop invalid transition attempts.

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
    - Reason: lifecycle mapping and concurrency/cancellation logic are correctness-critical.
  - **Skills**: [`git-master`]
    - `git-master`: maintain atomic commits for state machine logic and tests.
  - **Skills Evaluated but Omitted**:
    - `artistry`: no unconventional approach needed.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 5,7
  - **Blocked By**: 2

  **References**:
  - `nanobot/agent/loop.py:351` - `process_direct` as the safe execution bridge.
  - `nanobot/bus/events.py:8` - internal message model for mapping context.
  - `nanobot/bus/queue.py:25` - async patterns for publish/consume.
  - `nanobot/agent/subagent.py:49` - existing async task lifecycle and callback cleanup pattern.
  - `https://a2a-protocol.org/latest/specification/` - task lifecycle semantics.

  **Acceptance Criteria**:
  - [x] Transition table prevents illegal state transitions.
  - [x] Cancelling active tasks results in terminal canceled state.
  - [x] Task retrieval reports consistent state and timestamps.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Task lifecycle reaches completed state
    Tool: Bash (curl + jq)
    Preconditions: gateway A2A enabled
    Steps:
      1. POST send request with simple text prompt.
      2. Extract task id from response.
      3. Poll GET /tasks/{id} until terminal state or timeout 15s.
      4. Assert terminal state is completed and result artifact/message exists.
    Expected Result: deterministic lifecycle progression
    Evidence: .sisyphus/evidence/task-4-lifecycle.json

  Scenario: Cancel races are handled safely
    Tool: Bash
    Preconditions: long-running task prompt
    Steps:
      1. Submit task.
      2. Immediately POST /tasks/{id}:cancel.
      3. Assert cancel response is valid (success or already-terminal with explicit reason).
      4. GET /tasks/{id} and assert terminal state is canceled or completed with documented rule.
    Expected Result: race handled without inconsistent states
    Evidence: .sisyphus/evidence/task-4-cancel-race.json
  ```

  **Commit**: YES
  - Message: `feat(a2a): add task store and lifecycle state machine`
  - Files: `nanobot/a2a/*`, `tests/a2a/*`
  - Pre-commit: `python -m pytest tests/a2a/test_task_lifecycle.py -q`

- [x] 5. Implement Core A2A Methods (send/get/list/cancel)

  **What to do**:
  - Implement MVP method handlers according to locked contract.
  - Ensure send supports non-blocking task creation and optional blocking mode.
  - Implement list filtering/pagination rules defined in contract.
  - Map internal failures to stable protocol error responses.

  **Must NOT do**:
  - Do not expose internal stack traces in API responses.
  - Do not return schema-incompatible payloads.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: protocol method correctness + integration with task runtime.
  - **Skills**: [`git-master`]
    - `git-master`: keep endpoint-level changes and tests traceable.
  - **Skills Evaluated but Omitted**:
    - `dev-browser`: API-only work.

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: 7,8
  - **Blocked By**: 4

  **References**:
  - `nanobot/agent/loop.py:144` - message processing path and response object boundaries.
  - `nanobot/channels/manager.py:178` - dispatcher behavior to preserve while adding A2A.
  - `https://a2a-protocol.org/latest/specification/` - required operation semantics.
  - `https://a2a-protocol.org/latest/topics/key-concepts/` - task/message/artifact concept model.

  **Acceptance Criteria**:
  - [x] send/get/list/cancel endpoints pass contract tests.
  - [x] Unknown method/path returns stable protocol-defined error.
  - [x] Invalid payload returns 4xx with structured error body.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Happy path for send/get/list/cancel
    Tool: Bash (curl + jq)
    Preconditions: gateway A2A enabled and auth configured
    Steps:
      1. Send message request and capture task id.
      2. GET task by id and assert shape.
      3. GET task list and assert task id is present.
      4. Submit second long task, cancel it, assert canceled terminal state.
    Expected Result: all core operations behave per contract
    Evidence: .sisyphus/evidence/task-5-core-ops.json

  Scenario: Invalid method returns protocol error
    Tool: Bash
    Preconditions: gateway A2A enabled
    Steps:
      1. Call unsupported method/path.
      2. Assert error code and message match contract.
    Expected Result: deterministic, non-500 error handling
    Evidence: .sisyphus/evidence/task-5-invalid-method.json
  ```

  **Commit**: YES
  - Message: `feat(a2a): implement core task methods`
  - Files: `nanobot/a2a/*`, tests under `tests/a2a/*`
  - Pre-commit: `python -m pytest tests/a2a/test_methods.py -q`

- [x] 6. Add Auth, Limits, and Error Hardening

  **What to do**:
  - Implement bearer token validation for A2A operations.
  - Add request size/time limits and safe parsing behavior.
  - Define and enforce consistent error translation (auth, validation, unsupported, internal).
  - Reflect auth requirements in Agent Card security fields.

  **Must NOT do**:
  - Do not require auth for local development unless configured.
  - Do not leak sensitive config in error logs.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: security boundary implementation with operational implications.
  - **Skills**: [`git-master`]
    - `git-master`: isolate security changes for easier review.
  - **Skills Evaluated but Omitted**:
    - `playwright`: not applicable.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2/3 bridge task
  - **Blocks**: 7,8
  - **Blocked By**: 2

  **References**:
  - `nanobot/channels/base.py:61` - existing allowlist authorization model.
  - `SECURITY.md:214` - current auth/security posture.
  - `nanobot/config/schema.py:173` - existing timeout config pattern.
  - `https://a2a-protocol.org/latest/specification/` - security declaration expectations.

  **Acceptance Criteria**:
  - [x] Requests without token return 401 when auth enabled.
  - [x] Invalid token returns 401 with stable error body.
  - [x] Oversized payload returns defined 4xx code.
  - [x] Agent card security scheme fields match runtime policy.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Auth-required endpoint rejects anonymous call
    Tool: Bash (curl)
    Preconditions: a2a auth enabled with bearer token
    Steps:
      1. Call send endpoint without Authorization header.
      2. Assert status 401 and structured error payload.
    Expected Result: unauthorized request blocked
    Evidence: .sisyphus/evidence/task-6-auth-missing.json

  Scenario: Payload limit enforcement
    Tool: Bash
    Preconditions: payload max size configured
    Steps:
      1. Generate payload exceeding limit.
      2. POST to send endpoint.
      3. Assert request rejected with expected error code.
    Expected Result: server remains stable and rejects oversized input
    Evidence: .sisyphus/evidence/task-6-limit-check.json
  ```

  **Commit**: YES
  - Message: `feat(a2a): enforce auth and request hardening`
  - Files: `nanobot/a2a/*`, `nanobot/config/schema.py`, tests
  - Pre-commit: `python -m pytest tests/a2a/test_security.py -q`

- [x] 7. Build TDD Contract + Integration + Regression Test Suite

  **What to do**:
  - Add contract tests for discovery + core methods + error responses.
  - Add lifecycle tests for state transitions and cancellation races.
  - Add regression tests proving existing features/channels remain unaffected.

  **Must NOT do**:
  - Do not rely on manual checks for pass/fail.
  - Do not skip negative/failure-path tests.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: broad QA coverage across protocol and regression boundaries.
  - **Skills**: [`git-master`]
    - `git-master`: keep test-only commits isolated and revertible.
  - **Skills Evaluated but Omitted**:
    - `frontend-ui-ux`: no UI testing.

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: 8
  - **Blocked By**: 3,4,5,6

  **References**:
  - `tests/test_email_channel.py` - current project testing style for channels.
  - `tests/test_tool_validation.py` - existing pytest structure.
  - `pyproject.toml:39` - pytest dependencies/config.
  - `nanobot/cli/commands.py:321` - runtime boot path for integration tests.

  **Acceptance Criteria**:
  - [x] `python -m pytest tests/a2a -q` passes.
  - [x] `python -m pytest tests -q` passes.
  - [x] Test suite includes both happy-path and failure-path protocol cases.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: A2A contract suite passes
    Tool: Bash
    Preconditions: implementation complete
    Steps:
      1. Run python -m pytest tests/a2a -q
      2. Assert exit code 0.
      3. Assert no skipped tests for mandatory core methods.
    Expected Result: protocol compliance checks green
    Evidence: .sisyphus/evidence/task-7-a2a-pytest.txt

  Scenario: Full regression suite remains green
    Tool: Bash
    Preconditions: A2A changes integrated
    Steps:
      1. Run python -m pytest tests -q
      2. Assert exit code 0.
    Expected Result: no breakage outside A2A surface
    Evidence: .sisyphus/evidence/task-7-regression.txt
  ```

  **Commit**: YES
  - Message: `test(a2a): add protocol contract and regression coverage`
  - Files: `tests/a2a/*`, updated existing tests if required
  - Pre-commit: `python -m pytest tests -q`

- [x] 8. Document A2A Operation and Rollout Boundaries

  **What to do**:
  - Add docs for enabling/configuring A2A and auth.
  - Document MVP limitations and explicit out-of-scope items.
  - Add troubleshooting section for common error responses.

  **Must NOT do**:
  - Do not claim unsupported features (streaming/push/client mode).
  - Do not omit security recommendations for production.

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: precision documentation with operational safety focus.
  - **Skills**: [`git-master`]
    - `git-master`: clean docs-only commit separation.
  - **Skills Evaluated but Omitted**:
    - `dev-browser`: not required for markdown docs.

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Final sequential
  - **Blocks**: None
  - **Blocked By**: 3,5,6,7

  **References**:
  - `README.md` - primary user-facing docs location.
  - `SECURITY.md` - security posture and known limitations format.
  - `https://a2a-protocol.org/latest/specification/` - avoid doc/spec divergence.

  **Acceptance Criteria**:
  - [x] README (or dedicated doc) includes setup + endpoint summary + auth examples.
  - [x] Limitations section explicitly lists out-of-scope MVP features.
  - [x] Troubleshooting covers top protocol/auth errors with fixes.

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: Documentation includes required A2A sections
    Tool: Bash
    Preconditions: docs updated
    Steps:
      1. Grep docs for sections: "A2A", "Authentication", "Limitations", "Troubleshooting".
      2. Assert each section exists.
    Expected Result: operational docs are complete
    Evidence: .sisyphus/evidence/task-8-docs-check.txt

  Scenario: Doc examples execute successfully
    Tool: Bash
    Preconditions: gateway running with sample config
    Steps:
      1. Run documented curl discovery command.
      2. Run documented send command.
      3. Assert both return expected schemas.
    Expected Result: documentation is executable and correct
    Evidence: .sisyphus/evidence/task-8-doc-example.txt
  ```

  **Commit**: YES
  - Message: `docs(a2a): add operation guide and rollout constraints`
  - Files: `README.md`, `SECURITY.md`, optional `docs/a2a.md`
  - Pre-commit: `python -m pytest tests -q`

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | `docs(a2a): lock protocol contract and MVP boundaries` | contract docs | `python -m pytest -q` |
| 2 | `feat(a2a): add config schema and gateway lifecycle wiring` | config/runtime | `python -m pytest tests -q` |
| 3 | `feat(a2a): add agent card discovery endpoint` | a2a adapter + tests | `python -m pytest tests/a2a -q` |
| 4 | `feat(a2a): add task store and lifecycle state machine` | runtime + tests | `python -m pytest tests/a2a/test_task_lifecycle.py -q` |
| 5 | `feat(a2a): implement core task methods` | handlers + tests | `python -m pytest tests/a2a/test_methods.py -q` |
| 6 | `feat(a2a): enforce auth and request hardening` | auth/limits/tests | `python -m pytest tests/a2a/test_security.py -q` |
| 7 | `test(a2a): add protocol contract and regression coverage` | tests | `python -m pytest tests -q` |
| 8 | `docs(a2a): add operation guide and rollout constraints` | docs | `python -m pytest tests -q` |

---

## Success Criteria

### Verification Commands
```bash
python -m pytest tests/a2a -q
# Expected: all A2A protocol tests pass

python -m pytest tests -q
# Expected: full suite passes

# Example smoke checks after implementation
curl -sS http://127.0.0.1:8088/.well-known/agent-card.json | jq -e '.name and .supportedInterfaces and .skills'
# Expected: jq exits 0
```

### Final Checklist
- [x] All Must Have items are implemented
- [x] All Must NOT Have constraints are respected
- [x] Discovery + core task methods are contract-tested
- [x] Auth/limits/error behavior validated
- [x] Existing channel behavior remains intact
- [x] Documentation reflects actual implemented MVP scope
