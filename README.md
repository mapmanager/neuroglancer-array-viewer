# ng-array-demo v2

Fresh, standalone v2 Neuroglancer experiments. There is no CloudScope, NiceWidgets, or NiceGUI.

The default demo is a repaired Python `LocalVolume` reference displayed in an iframe controlled by our own page. A separate `direct-js/` app mounts Neuroglancer directly into our `<div>`. It can show the known-supported public FIB-25 source or AcqImage-backed NumPy datasets supplied by the local Python transport.

## Prerequisites

- `uv`
- Git
- A C++ compiler (Xcode Command Line Tools on macOS)
- Node.js is needed while installing Neuroglancer from its Git source. Upstream also carries a Node wheel build dependency, but having a current local Node installation is the least surprising clean-room setup.

This project pins the verified development interpreter to Python 3.13.8 and declares compatibility with Python 3.11–3.13. Neuroglancer is installed only from official GitHub commit `576c94b08ad7609919eb42f8a93b9cf0e161df14`. There is no PyPI fallback.

## Iframe reference

```bash
uv sync --frozen
uv run python server.py
```

Open <http://127.0.0.1:8000>. Add `--no-browser` to prevent automatic opening, or `--port 8010` to change the control-page port.

Native Neuroglancer controls inside the image:

- mouse wheel: move through Z
- Ctrl+wheel: zoom at the pointer (on macOS a browser/trackpad may report the platform-equivalent modifier)
- drag: pan
- `h`: Neuroglancer help, when its help UI is enabled

The diagnostics distinguish our last requested Z from Neuroglancer's actual state, so native wheel interaction is observable even though v2 does not attempt a polished two-way toolbar.

The Dataset selector atomically swaps complete synthetic datasets without replacing the iframe. Dataset A has 70Z/2C/1024² data, Dataset B has 31Z/1C/512×768 data, and Dataset C has 18Z/3C/640×384 data. Each has distinct pixels, physical calibration, Z limits, channel controls, colors, and contrast state.

## Direct-JS Phase A

In a second terminal:

```bash
cd direct-js
npm install
npm run dev
```

Open the Vite URL it prints. This is a direct mount into our `<div>` with no iframe. Its custom toolbar includes composite XY, one-XY-panel-per-channel side-by-side and stacked layouts, XY + 3D, 4-panel, and 3D. A right-side overlay provides per-channel LUT color and linked slider/number contrast controls. It requires internet access only for the public demonstration datasource. See `direct-js/README.md`.

AcqStore is an optional demo/loading dependency, not a core Neuroglancer viewer dependency. The current local AcqStore checkout requires Python 3.12 or newer. Install the optional editable sibling integration with:

```bash
uv sync --extra acqstore-demo
```

For the NumPy transport milestones, run this from the project root in another terminal:

```bash
uv run --extra acqstore-demo python direct_numpy_server.py
```

The direct selector includes the original A/B/C arrays, two long Gaussian-band AcqImage synthetics (`C,Y,X = 2,50000,1024` and `1,30000,100`), and the `rr30a-two-channel` AcqStore sample. The server creates volumes lazily. Selecting rr30a calls `ensure_sample_file`, downloads and caches it when absent, then opens the local path with `AcqImage`. The server calculates each materialized channel's exact observed minimum and maximum once; those values remain the hard slider limits. A uint16 histogram supplies a separate 1st–99th percentile automatic range used for initial display and each channel's Auto button.

Before transport, each AcqImage `(Y,X)` plane is transposed and flipped along the new display-Y axis. The long source-Y dimension therefore becomes horizontal Neuroglancer X; X/Y calibration and units are swapped with the data orientation. The long sources use `0.002 s` per displayed-X sample and `0.25 um` per displayed-Y sample. Neuroglancer's coordinate-space scales preserve their non-square physical aspect, and the adapter initially fits that calibrated extent into the XY panel.

The direct adapter publishes view-state snapshots through `getViewState()` and `subscribeViewState()`, including named index position, calibrated physical position, and both index and physical XY ranges for every slice panel. The optional Python server receives coalesced snapshots at `/api/view-state` and exposes non-blocking callbacks through `ViewStateDispatcher.subscribe()`. Its example `log_view_state()` subscriber logs dataset, layout, calibrated Z, and calibrated XY bounds with source file, function, and line context.

### Python integration boundary

The current Python boundary is deliberately small. `acquisition_to_ng(acquisition)` converts a complete AcqImage to display-oriented C,X,Y,Z data. `ViewStateDispatcher.subscribe(callback)` registers a non-blocking callback for browser state:

```python
from direct_numpy_server import ViewStateDispatcher


def on_view_state(state: dict[str, object]) -> None:
    """Receive calibrated viewer state on the dispatcher thread."""
    print(state["physicalPosition"])
    print(state["xyPhysicalBounds"])


dispatcher = ViewStateDispatcher()
unsubscribe = dispatcher.subscribe(on_view_state)

# During shutdown:
unsubscribe()
dispatcher.close()
```

The standalone server wires browser POSTs into that dispatcher. This is a verified demo contract, not yet a packaged application API. The next high-priority architecture milestone is a small public server/application wrapper that registers datasets, owns lifecycle, exposes subscriptions, and shuts down cleanly without requiring callers to configure request-handler class attributes.

For the full design record and clean-room checklist, read `roadmap-dev-ng.md`.
