# ng-array-demo — Agent Instructions

## Repository purpose

`ng-array-demo` is an independent experimental repository for evaluating
Neuroglancer with Python-owned NumPy image data and a directly embedded
JavaScript viewer. The implementation is evolving; this file defines working
and safety practices, not a permanent application architecture.

Current areas include:

- `server.py` and `web/`: the iframe reference implementation;
- `direct_numpy_server.py`: local NumPy datasource transport;
- `direct-js/`: the directly mounted Neuroglancer client;
- `roadmap-dev-ng.md`: implementation history, decisions, and next steps.

Treat current filenames and boundaries as descriptive rather than immutable.
Do not introduce a broader architectural rule unless the user requests or
approves it.

## Default task scope

Work only in this repository unless the user explicitly includes another
repository.

- Start with files named by the user and their direct dependencies.
- Keep changes focused on the requested behavior.
- Preserve unrelated user changes.
- Avoid speculative abstractions and unrelated cleanup.
- Do not add or change production dependencies without asking first.
- When a material choice cannot be resolved from the repository or verified
  upstream behavior, ask a focused question and provide a recommendation.

## Sibling repositories

The local workspace may contain sibling repositories, including:

| Repository | Local path | Expected relevance |
|---|---|---|
| AcqStore | `../acqstore/` | Acquisition models, `AcqImage`, loaders, metadata, and sample data |

Before inspecting a sibling repository, obtain the user's approval for the
exact repository or path. Approval to install or use a sibling dependency does
not imply permission to edit it.

- Prefer verified public sibling APIs; do not invent paths, methods, events,
  metadata fields, shapes, or return types.
- Do not inspect sibling tests or private implementation details unless the
  public API and documentation are insufficient and the user approves the
  expanded inspection.
- Do not edit a sibling repository unless the user explicitly requests a
  cross-repository change or approves it after the need is explained.
- Report and verify changes separately for every repository touched.

## Inspection and search policy

Use targeted inspection and keep output small.

- Prefer user-named paths and their direct dependencies.
- Default all searches to this repository; do not broaden to parent folders,
  sibling repositories, or the home directory without task-specific need and
  permission.
- Prefer targeted `rg` searches over unrestricted recursive file listings.
- Do not print large lockfiles, generated bundles, minified files, binary-file
  lists, or large data contents unless specifically required.
- For conceptual questions, answer from established context when tree
  inspection would add no value.
- Internet research does not grant permission to broaden local inspection.

## Search exclusions

Never inspect, list, search, or traverse virtual environments, including any
directory named `.venv`, beginning with `.venv-`, named `venv`, or beginning
with `venv-`. Use project metadata and normal package APIs instead.

Never inspect, list, search, or traverse JavaScript dependency trees such as
`node_modules/`. Use `package.json`, lockfiles through targeted queries, and
package or upstream documentation instead.

Unless the task explicitly requires them, also exclude:

- `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, and tool
  caches;
- `build/`, `dist/`, coverage output, and generated bundles;
- `.git/` contents;
- archives, wheels, application bundles, and other generated artifacts;
- large generated datasets and binary assets;
- temporary, log, and editor-generated files.

Git status and other normal Git commands that do not traverse `.git/` contents
are allowed. If an excluded path appears necessary, explain why and ask for
explicit approval for that exact path.

## Dependencies and upstream APIs

- Use the GitHub-pinned Neuroglancer revisions declared by this repository; do
  not replace them with a PyPI Neuroglancer fallback.
- Neuroglancer APIs may differ across revisions. Verify uncertain APIs against
  the pinned source, current authoritative upstream documentation, or existing
  verified repository usage. Do not guess API names or behavior.
- Keep any workaround for an upstream limitation narrow, documented, and
  covered by relevant verification. Do not patch installed dependency trees.
- Use `uv` for Python environment commands and `npm` for `direct-js/` commands.
- Ask before adding a new runtime dependency or changing dependency sources.

## Common commands

Run Python commands from the repository root:

```bash
uv sync
uv run python server.py
uv run python direct_numpy_server.py
```

Run direct-JS commands from `direct-js/`:

```bash
npm ci
npm run dev
npm run build
```

The direct NumPy demo currently uses two development processes: the Python
datasource server from the repository root and Vite from `direct-js/`.

## Verification

Match verification to the change and report exactly what ran.

- Python changes: run a focused syntax or test check and exercise affected
  metadata/chunk endpoints when applicable.
- Direct-JS changes: run `npm run build` and perform a browser smoke test when
  behavior or integration changes.
- NumPy datasource changes: verify representative metadata and a real encoded
  chunk, including shape, dtype, dimensions, units, and scales.
- Dataset switching changes: test distinct datasets and rapid switching; check
  final source, position, Z behavior, channels, rendering, and diagnostics.
- Viewer-control changes: test both programmatic control and native
  Neuroglancer interaction when synchronization is intended to be
  bidirectional.

Do not claim browser rendering is fixed solely because syntax checks or builds
pass. If live verification is unavailable, identify the change as unverified
and give the user a short, itemized smoke test.

Add focused automated tests when an interface or invariant has stabilized and
the test will reduce regression risk. Do not create broad test scaffolding
solely for rapidly changing exploratory UI behavior.

## Documentation

Update the relevant documentation when behavior, setup, dependencies,
limitations, milestones, or smoke-test expectations change.

- Keep `README.md` focused on current setup and run instructions.
- Record development decisions, verified limitations, milestones, and deferred
  work in `roadmap-dev-ng.md`.
- Keep `direct-js/README.md` aligned with the direct viewer's current behavior.
- Do not document planned behavior as already implemented or verified.

## Git discipline

This directory is an independent Git repository.

- Check `git status` before and after material work.
- Preserve unrelated user changes and do not overwrite them.
- Do not commit, push, create branches, rewrite history, or open pull requests
  unless the user explicitly requests it.
- Provide a concise suggested commit message when the user asks for one.
