# AGENTS.md

This file defines project-wide instructions for coding agents working on `multicuts`.

## 1. Primary rule: use only the context you need

Do **not** preload or read every file under `docs/` at the start of a task.

Documentation is task-specific reference material. Read only the document, section, or keyword range required to make the current change correctly.

Large context is not a substitute for understanding the task.

### Documentation map

Use this map to decide whether a document is necessary:

| Document | Read it when the task involves |
| --- | --- |
| `README.md` | high-level project purpose, user-facing CLI examples, current project scope |
| `docs/prd.md` | product behavior, requirements, acceptance criteria, scoring semantics, MVP scope |
| `docs/architecture.md` | module boundaries, data flow, adapters, artifacts/cache, integration architecture |
| `docs/conventions.md` | code style, Python practices, tests, typing, FFmpeg/yt-dlp/`multisubs` conventions |

### Context-loading rules

- If the task is small and local, do not read unrelated documentation.
- Search headings/keywords first when possible; read the narrow relevant section instead of the whole document.
- Do not copy large documentation sections into working context unless the task genuinely requires them.
- Do not read `docs/prd.md` for a formatting-only change.
- Do not read `docs/conventions.md` when changing prose only.
- Do not read `docs/architecture.md` for a trivial isolated bug unless the fix may change a module boundary or data flow.
- If the task changes product behavior, read the relevant PRD requirement before implementing it.
- If the task changes architecture or external integration boundaries, read the relevant architecture section.
- If the task adds or changes Python code/tests, consult only the relevant conventions sections when needed.
- Do not create new documentation files unless the user/task explicitly requests them or an existing required project contract cannot reasonably be represented in the current files.

## 2. Source-of-truth precedence

When instructions conflict, use this order:

1. explicit user/task instructions;
2. `AGENTS.md`;
3. the relevant project documentation;
4. existing implementation behavior/tests, unless the task is explicitly changing that behavior.

If product requirements and implementation disagree, do not silently choose one. Make the smallest change consistent with the requested task and update the affected existing documentation when required.

## 3. Project scope

`multicuts` is a Python CLI that:

- accepts a local video or supported YouTube URL;
- transcribes the source once;
- generates and ranks short-form clip candidates;
- assigns explainable scores;
- renders selected clips;
- burns subtitles using `multisubs`.

The MVP is intentionally synchronous and processes one source video per invocation.

Do not introduce distributed or framework-heavy architecture unless explicitly required.

## 4. Technology baseline

Assume:

```text
Python >=3.10,<3.14
multisubs >=4.1,<5
FFmpeg
ffprobe
yt-dlp
pytest
Ruff
Pyright
```

Early development may pin `multisubs==4.1.0`.

Do not silently raise the minimum Python version.

## 5. Architecture rules

Follow these rules unless a task explicitly changes them:

- keep one readable synchronous pipeline;
- domain logic must not depend directly on external providers/tools;
- isolate yt-dlp, `multisubs`, FFmpeg, and semantic scorers at narrow boundaries;
- use project-owned models between stages;
- transcribe the source only once per relevant configuration;
- never retranscribe each selected clip just to generate subtitles;
- generate subtitle layout for the final clip geometry;
- use `multisubs` templates/fonts/animations instead of duplicating its subtitle engine;
- use only supported public `multisubs` APIs;
- do not import `multisubs` private implementation modules;
- prefer filesystem JSON artifacts over databases for the MVP;
- keep caches stage-specific and simple.

## 6. Avoid overengineering

Before introducing an abstraction, ask whether the current task actually needs it.

Do not add by default:

- dependency-injection containers;
- repositories around simple file operations;
- service layers with no independent responsibility;
- event buses;
- workflow engines;
- plugin registries;
- ORMs/databases;
- async pipeline infrastructure;
- queues/workers;
- microservices;
- generic factories;
- base classes with one implementation.

Prefer:

- functions;
- dataclasses;
- small modules;
- `Protocol` only at real substitutable boundaries;
- explicit orchestration.

A little duplication is preferable to the wrong abstraction. Refactor when the repeated concept is understood.

## 7. Coding rules

Code and technical documentation must be in English.

Use:

- `pathlib.Path`;
- type hints on shared/public boundaries;
- project-owned dataclasses for normalized data;
- explicit exceptions;
- UTF-8 text files;
- argument lists for subprocesses;
- `logging.getLogger(__name__)`.

Do not:

- use `shell=True`;
- leak raw provider dictionaries/objects into domain code;
- use broad `dict[str, Any]` throughout the application;
- log secrets/cookies/tokens;
- silently overwrite completed files;
- invent missing ASR timestamps;
- use `print()` from domain modules.

Keep comments focused on why a constraint exists.

## 8. Dependency rules

Before adding a dependency:

1. verify the requirement cannot be handled clearly with the standard library/current dependencies;
2. verify Python 3.10–3.13 support;
3. verify it solves a current, concrete problem;
4. keep provider-specific dependencies inside their adapter.

Do not add libraries merely to implement simple retries, filesystem operations, dependency injection, or trivial configuration.

## 9. `multisubs` rules

`multisubs` is a core provider.

Agents must:

- use the public package contract;
- keep integration logic inside the `MultisubsAdapter`;
- normalize transcript output into `multicuts` models;
- support automatic language detection when requested;
- preserve word timings;
- preserve provider version/template provenance;
- build clip-local timestamps without new ASR;
- resolve subtitles against final clip geometry.

If a required capability exists only as a private `multisubs` function, do not couple `multicuts` to it. Prefer evolving the public `multisubs` contract.

## 10. FFmpeg and media rules

- validate FFmpeg/ffprobe before expensive work;
- inspect real presentation geometry, including rotation;
- render incomplete outputs to temporary paths;
- publish final files only after successful completion;
- prefer correct timestamps/geometry over premature stream-copy optimization;
- use explicit tolerances in media tests;
- keep FFmpeg command construction out of domain code.

## 11. yt-dlp rules

- access yt-dlp only through the source adapter;
- prefer its Python API;
- download to project-controlled paths;
- normalize metadata;
- never expose credentials in logs/errors;
- do not implement DRM/access-control bypasses.

## 12. Scoring rules

The viral-potential score is an explainable ranking signal, not a probability.

Keep separate:

- deterministic features;
- semantic-provider output;
- score composition;
- penalties;
- ranking/deduplication.

Validate structured provider responses.

Never invent a provider result after a failure.

Version any change that alters scoring meaning or composition.

## 13. Testing requirements

Behavior changes require tests unless testing is impossible for a clearly documented reason.

Use pytest.

Prefer:

- unit tests for pure domain logic;
- contract tests for external-provider assumptions;
- integration tests only for real external tools.

The default test suite must remain hermetic:

- no network;
- no Whisper downloads;
- no GPU requirement;
- no YouTube dependency;
- no remote scorer credentials.

Mock external boundaries, not chains of private helpers.

Keep fixtures small.

## 14. Validation commands

Run the narrowest relevant tests first.

Before considering a normal code change complete, run when applicable:

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
```

When external dependencies are available and the change affects them, also run the relevant integration tests.

For packaging changes:

```bash
python -m build
```

If a command cannot be run in the environment, state that clearly. Do not claim it passed.

## 15. Change discipline

- make the smallest coherent change;
- do not perform unrelated refactors;
- preserve existing public behavior unless the task changes it;
- do not rename modules/types just for preference;
- update tests together with behavior;
- update an existing relevant document when a stable product/architecture contract changes;
- do not add speculative TODO architecture.

## 16. Completion checklist

Before finishing a task, verify only the items relevant to that task:

- requested behavior is implemented;
- code follows the existing architecture;
- no unnecessary abstraction was introduced;
- external-provider logic stays behind adapters;
- tests cover the changed behavior;
- relevant checks were run;
- no secrets or unsafe shell execution were introduced;
- existing documentation remains consistent with the change.

Do not expand the task beyond what is required to satisfy it correctly.

## 17. Git delivery workflow

- for every repository-changing implementation task, follow the `deliver-feature` skill before editing files;
- use GitHub Flow with one short-lived branch per coherent change;
- create the branch from the remote default branch before implementation;
- name branches `<type>/<issue-id>-<slug>`, omitting the issue ID when none is available;
- use lowercase kebab-case branch names and Conventional Commits 1.0.0;
- do not discard, stash, move, stage, or include pre-existing user changes without explicit permission;
- after implementation and validation, stop before staging or committing;
- present the exact branch, changed files, validation results, proposed commits, and pull request content;
- stage, commit, push, and open the pull request only after explicit user approval of that delivery package;
- if the approved content or target changes materially, request approval again;
- never merge a pull request or delete its branch without separate explicit authorization.

Read-only analysis, diagnosis, review, and status requests do not require a new branch.
