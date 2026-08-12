# Neuroglancer Array Viewer

`neuroglancer-array-viewer` is a framework-neutral Python package for viewing
NumPy and AcqImage volumes with a directly mounted Neuroglancer frontend.

- Distribution: `neuroglancer-array-viewer`
- Python import: `ng_viewer`
- Repository: https://github.com/mapmanager/neuroglancer-array-viewer
- Python owns datasets, transport, configuration, and callbacks.
- The packaged JavaScript frontend is served by the same Python process.
- Volume pixels are **uint16 only** (`register_numpy` rejects other dtypes).
- Neuroglancer is pinned to official GitHub commit
  [`576c94b08ad7609919eb42f8a93b9cf0e161df14`](https://github.com/google/neuroglancer/commit/576c94b08ad7609919eb42f8a93b9cf0e161df14);
  there is no PyPI fallback. Upstream project:
  [google/neuroglancer](https://github.com/google/neuroglancer).
- Optional AcqImage support uses
  [mapmanager/acqstore](https://github.com/mapmanager/acqstore) (Python 3.12+).

## Install from source

Requires Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mapmanager/neuroglancer-array-viewer.git
cd neuroglancer-array-viewer
uv sync
```

Core package install needs only NumPy and the pinned Neuroglancer commit.
The default `dev` group also installs AcqStore from GitHub `main` when
Python is 3.12 or newer (used by demos and tests that load sample
acquisitions).

### Local sibling AcqStore (optional)

If you develop next to a checkout of
[acqstore](https://github.com/mapmanager/acqstore), replace the AcqStore entry
in `[tool.uv.sources]` with an editable path, then re-sync:

```toml
acqstore = { path = "../acqstore", editable = true }
```

```bash
uv sync
```

## Run demos

```bash
uv run python examples/python/python_demo.py
```

Open the single URL printed by Python. The example loads the AcqStore
`rr30a-two-channel` sample and runs until Ctrl+C.

NiceGUI remains optional:

```bash
uv run --with nicegui python examples/python/demo_nicegui.py
```

The NiceGUI page embeds `viewer.viewer_url`; NiceGUI does not own the
Neuroglancer implementation or data transport.

## Python API

```python
from ng_viewer import NgArrayViewer, NgConfig, ViewState

viewer = NgArrayViewer(config=NgConfig())
viewer.register_numpy("sample", array, axes=("Z", "Y", "X"))


def on_view_state(state: ViewState) -> None:
    print(state.layout, state.x, state.y, state.z, state.z_unit)


unsubscribe = viewer.subscribe_view_state(on_view_state)
viewer.start()
print(viewer.viewer_url)
viewer.wait()
```

`register_numpy()` is part of the core package and accepts **uint16** arrays
only. `register_acqimage()` registers an
[AcqStore](https://github.com/mapmanager/acqstore) acquisition and requires
that dependency. `select_dataset(key)` changes the active dataset in an
already-open viewer. `start()` and `stop()` support application hosts;
`run()` and `wait()` support scripts.

`ViewState.layout` is a `ViewerLayout` enum. Its X/Y ranges and Z position are
calibrated typed values. `ViewState.raw` retains the complete browser payload
for diagnostics and forward-compatible fields.

## Configuration

`NgConfig` controls initial presentation. Optional presentation chrome,
dataset selection, and diagnostics default hidden. Options and multi-plane Z
navigation default visible. See the `NgConfig` class docstring for each field.

Important fields include:

- `chrome_placement`
- `show_options_control`
- `show_z_control`
- `show_scale_bar`
- `show_axis_lines`
- `show_display_dimensions`
- `show_native_layout_buttons`
- `show_channels_control`
- `show_layout_control`
- `show_dataset_control`
- `show_diagnostics`

## Frontend development

`direct-js/` is the editable frontend source and build project. Normal Python
users do not need Node or Vite at runtime.

```text
direct-js/src/           reusable adapter and viewer UI
direct-js/examples/      runnable JavaScript development examples
src/ng_viewer/static/    generated frontend packaged with Python
```

Build the packaged frontend:

```bash
cd direct-js
npm ci
npm run build
```

For hot-reload development, start `direct_numpy_server.py`, point
`NG_ARRAY_DEMO_NUMPY_SERVER` at its URL, and run `npm run dev`. See
`direct-js/README.md` and `direct-js/examples/README.md`.

## Data conventions

AcqImage `(Y, X)` planes are transposed and flipped along display Y before
transport, preserving the established scientific-display orientation. Axis
spacing and units follow the transformed data. Channel contrast controls use
the observed uint16 domain; initial and Auto contrast use the calculated
1st–99th percentile range (`AUTO_PERCENTILES` in `ng_viewer.contrast`).

## License

Apache-2.0. Copyright (c) 2026 Robert H. Cudmore.

The retired Python-hosted iframe experiment is preserved as development
history in `roadmap-dev-ng.md`; it is not part of the current implementation.
