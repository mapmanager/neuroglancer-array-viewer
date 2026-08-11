# ng-array-demo v2

Fresh, standalone v2 Neuroglancer experiments. There is no CloudScope, NiceWidgets, or NiceGUI.

The default demo is a repaired Python `LocalVolume` reference displayed in an iframe controlled by our own page. A separate `direct-js/` Phase A mounts Neuroglancer directly into our `<div>` and uses a known-supported public HTTP datasource. The direct-JS demo intentionally does not yet expose the NumPy array; that custom datasource is v3 work.

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

Open the Vite URL it prints. This is a direct mount into our `<div>` with no iframe. Its custom toolbar switches among XY, XY + 3D, 4-panel, and 3D layouts and can float at three viewer edges or sit outside the viewer. It requires internet access for the public demonstration datasource. See `direct-js/README.md`.

For the full design record and clean-room checklist, read `roadmap-dev-ng.md`.
