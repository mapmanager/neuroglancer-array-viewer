# Direct-JS Phase A

This experiment imports the exact same pinned Neuroglancer GitHub commit as the Python project and mounts it into our `#ng-viewer` div through an `NgImageViewer` adapter. It uses no iframe.

It retains the official public FIB-25 precomputed datasource as a direct-embedding reference and also exposes AcqImage-backed NumPy datasets through Neuroglancer's upstream Python datasource protocol.

```bash
npm ci
npm run dev
```

To test NumPy transport and replacement, start its Python data server from the project root in another terminal before selecting a NumPy dataset:

```bash
uv sync --extra acqstore-demo
uv run --extra acqstore-demo python direct_numpy_server.py
```

AcqStore is an optional editable dependency from `../acqstore` and requires Python 3.12 or newer. It is used by this demo loader/transport only; it is not required by the core viewer installation.

Node.js 22.18 or newer is required by this Neuroglancer revision. The public source requires network access and WebGL2. Its metadata describes a single-channel `uint8` electron-microscopy image with X/Y/Z dimensions, 8 nm isotropic voxels at full resolution, and a full-resolution shape of 6446 × 6643 × 8090. It has no C or T dimension.

`vite.config.js` deliberately excludes Neuroglancer from Vite's development dependency optimizer and routes its pinned backend worker through `src/ng-chunk-worker.js`. Neuroglancer locates that worker beside an upstream module with `import.meta.url`; without the explicit project entry Vite does not bundle the dependency-owned worker correctly, metadata loads but pixel chunks are never requested, and the viewer remains gray. The configuration also prebundles the specific CommonJS modules imported by the frontend and worker graphs.

`src/NgImageViewer.js` is the sole unstable-API boundary. It demonstrates direct mounting, source initialization, programmatic layout, scale-bar and axis-line toggles, bidirectional Z state, per-channel display controls, XY viewport bounds, datasource diagnostics, and supported global chrome suppression. At the pinned revision, the per-panel related-layout buttons are constructed by the data-panel layout and have no granular public visibility option; this demo does not hide them with guessed CSS.

The custom layout chrome is our own DOM and can be placed over the top, left, or bottom of the viewer, or outside it. `XY` restores the additive composite. `Channels side-by-side` and `Channels stacked` create Neuroglancer layer-group viewers containing one XY channel layer each, with shared navigation. The other buttons select `XY + 3D`, `4 panel`, or `3D`. The Z number control and native wheel navigation observe the same viewer position.

The right-docked Channels overlay is generated from the active preset. Each channel has a color picker, a synchronized two-handle contrast range, and exact min/max number inputs. Every channel is a separate additive image layer whose pinned-upstream `#uicontrol invlerp` selects the corresponding shader channel and whose `vec3 color` control sets its LUT color. The invlerp control's `range` is the active contrast mapping, while its `window` is the allowed UI/histogram domain. Slider updates stay in JavaScript and do not wait for Python.

The adapter exposes `getViewState()` and `subscribeViewState(callback)`. State includes dataset/source identity, revision, named index and calibrated physical positions, units/scales, layout, and both index and physical XY limits derived from each live slice panel's pinned projection matrix. Vite coalesces changes and posts them to `/api/view-state`; `ViewStateDispatcher.subscribe()` provides non-blocking Python callbacks and returns an unsubscribe function. The included `log_view_state()` callback logs calibrated X/Y/Z with units. This narrow bridge is separate from the adapter and is optional when only the public datasource is running.

Neuroglancer's default-viewer stylesheet assumes it owns the full page and sets document overflow to hidden. This wrapper overrides that rule only on `.ng-array-demo-page`, so the embedded viewer retains its layout while the surrounding page and diagnostics remain scrollable.

Expected Phase A diagnostics are `directMount: true`, `iframeCount: 0`, and a layer whose datasource state changes from `loading` to `loaded` with at least one render layer. The initial position and zoom come from upstream's published FIB-25 example. If the public source cannot be reached, the concrete datasource error is shown there.

The datasource selector switches between the public Phase A reference and six AcqImage-backed arrays with different shapes, channel counts, pixels, and physical calibration. Each selection restores one complete viewer state, including source, coordinate space, centered position, shader, and layout.

Python owns each source through `AcqImage`, converts its full-resolution pixels once to contiguous `C,X,Y,Z`, and exposes it through a distinct pinned-upstream `python://volume/...` URL. The adapter applies `source_yx.T[::-1, :]` to every plane before transport, so source Y becomes displayed X and source X becomes reversed displayed Y; calibration follows that swap. Vite proxies protocol endpoints to `127.0.0.1:8001`, keeping worker requests same-origin.

The two long synthetic sources use `C,Y,X` shapes `2,50000,1024` and `1,30000,100`. Their periodic Gaussian-profile bands change local angle smoothly along displayed X. Source Y is calibrated at `0.002 s` and becomes displayed X; source X is calibrated at `0.25 um` and becomes displayed Y. Neuroglancer uses those coordinate scales for non-square physical pixels, and the adapter fits the initial calibrated extent to the XY panel. Native scale bars and the coordinate widget expose dimension names/units; this pinned slice canvas has no supported conventional ticked-axis-label API.

Volumes are created lazily on first selection to avoid allocating all large arrays at startup. The rr30a preset lazily calls AcqStore `ensure_sample_file("rr30a-two-channel")` and uses the cached local TIFF on subsequent runs. Every materialized dataset reports exact observed per-channel minima/maxima to the browser. Those values define the contrast-control domain and initial shader range; this is observed data, not camera bit-depth metadata.

NPZ is used for chunk encoding because the pinned upstream raw Python encoder still calls NumPy's removed `ndarray.tostring()` method. We do not patch the Git dependency.
