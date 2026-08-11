# Neuroglancer image viewer roadmap

**FIRST DEVELOPMENT VERSION — v2 source of truth**

Pinned upstream revision: `google/neuroglancer@576c94b08ad7609919eb42f8a93b9cf0e161df14` (verified as `master` while building v2 on 2026-08-11).

## Problem and standalone boundary

We need to learn whether Neuroglancer can become a reusable image-viewer primitive for an in-memory microscopy-style NumPy array while our application owns the surrounding controls. This is deliberately standalone: no CloudScope, NiceWidgets, or NiceGUI.

The representative array is `uint16`, natural Python order `Z,C,Y,X`, and shape `70,2,1024,1024`. Synthetic patterns make Z, channel, orientation, and contrast mistakes visible. Physical metadata is explicit:

| Dimension | Meaning | Scale | Unit |
|---|---|---:|---|
| `c^` | local color channel | 1 | unitless |
| `x` | horizontal sample | 0.25 | µm/pixel |
| `y` | vertical sample | 0.25 | µm/pixel |
| `z` | slice | 1.0 | µm/slice |

## V1 implementation and smoke-test evidence

V1 used the published Python integration, a Python-owned NumPy array, `LocalVolume`, the Neuroglancer integration server, and its viewer inside our iframe. Our controls sent HTTP updates back to Python for Z, C0/C1/composite display, and contrast.

It proved the essential chunked route: Python retained the array; the browser requested subvolumes through Neuroglancer; WebGL rendered the XY view. It also revealed:

- first installation could take a long time and appeared stalled during a source/compression-related build;
- the viewer was oversized on a 14-inch Retina laptop;
- the scale bar said `100 nm` because v1 itself declared 1 nm X/Y/Z samples;
- wheel changed native Z but our toolbar did not update;
- Ctrl+wheel zoomed and updated the scale display/location information;
- upper-left X/Y/Z location/dimension chrome remained;
- two upper-right buttons offered `4panel` and `xy-3d` related layouts;
- fixed red/green lines were Neuroglancer axis lines;
- the first control update could hang due to nested acquisition of a non-reentrant application lock.

## Diagnosis

The units were bad demo metadata, not an arbitrary scale invented by Neuroglancer. `CoordinateSpace` must carry physical spacing and a unitless channel dimension.

The red/green lines are controlled by viewer state `showAxisLines`; the scale bar by `showScaleBar`. Layout is programmatically controlled by the viewer `layout` state.

At the pinned source revision, supported configuration includes broad/global controls such as `showUIControls`, `showTopBar`, `showLocation`, `showLayerPanel`, help/settings/panel buttons, and panel borders. The two per-panel related-layout buttons are created unconditionally by `registerRelatedLayouts` in `src/data_panel_layout.ts`. There is no granular public state/config flag solely for those buttons. V2 may suppress the broader UI through supported properties and set layout programmatically, but it must not use guessed CSS to remove the remaining buttons.

The deadlock was application structure: code holding one application lock called a helper that attempted to acquire it again. Changing to `RLock` would mask this. V2 snapshots requested state under one ordinary lock, releases it, and then performs one Neuroglancer transaction; helpers used inside that transaction do not acquire the application lock.

## V2 implementation

### Repaired iframe reference

`server.py`:

- creates `(70,2,1024,1024)` ZCYX `uint16` synthetic data;
- exposes a zero-copy `C,X,Y,Z` transpose view with `c^,x,y,z` coordinate names;
- declares `0.25 um`, `0.25 um`, and `1.0 um` X/Y/Z spacing;
- defaults to XY, Z=35, scale bar on, axis lines off;
- supplies C0 green, C1 magenta, composite, and independent min/max contrast;
- structurally avoids nested application locks;
- constrains the iframe to at most about 980 × 570 CSS pixels and responds smaller;
- polls actual viewer state so native wheel Z is visible separately from requested Z;
- suppresses only chrome covered by upstream configuration properties.

V2 does not build a polished iframe two-way binding system. The polling readout is a diagnostic experiment because direct JS is the intended architecture.

### First local v2 smoke-test repair

The first local v2 run established that current master removes the local `c^` channel from global navigation position. The actual viewer position is therefore `[x,y,z]`, not `[c,x,y,z]`. The first build incorrectly wrote and read hard-coded position index 3, causing every toolbar POST to fail with `IndexError`; every control was affected because the browser sent the complete form, including Z, for every change.

The repaired reference now declares the global `x,y,z` navigation coordinate space explicitly, resolves Z by dimension name, sends partial control updates, serializes mutations, and publishes requested state only after the Neuroglancer transaction succeeds. Native wheel changes update the actual-Z slider unless it is being dragged. Routine diagnostic polling is omitted from the console access log and rewrites the diagnostics text only when state changes and the user is not selecting it.

The same smoke test also exposed a shader API mismatch: current master represents a `uint16` sample with its own GLSL `uint16_t`, so an ordinary `float(getDataValue(...))` conversion is invalid and left the default grayscale rendering visible. The shader now follows the pinned upstream API exactly with `toNormalized(getDataValue(channel))`, applies normalized uint16 min/max contrast, and multiplies each channel by a user-selectable RGB color. C0 is a moving filled circle/ramp (green by default); C1 is a moving square ring/diagonal-stripe pattern (magenta by default); composite adds both.

### Multiple-dataset iframe milestone

The final iframe milestone keeps one Viewer and iframe URL alive while atomically replacing all dataset-dependent state: NumPy array, `LocalVolume`, layer source/shader, global coordinate space, calibration, centered position, Z bounds, channel count, colors, contrast, and dynamic toolbar controls. Presentation toggles persist across swaps; dataset-specific navigation and channel settings reset to safe defaults.

- A: `70Z × 2C × 1024Y × 1024X`, `0.25 × 0.25 × 1.0 µm`, circle/ramp plus ring/stripes.
- B: `31Z × 1C × 512Y × 768X`, `0.65 × 0.40 × 2.5 µm`, diamond plus vertical bars.
- C: `18Z × 3C × 640Y × 384X`, `0.18 × 0.55 × 0.8 µm`, disk, rectangle, and horizontal bands.

Automated browser verification covered A/B/C rendering, dynamic 2/1/3-channel controls, centered Z resets, changed scale bars, nine repeated swaps with a stable iframe URL, and a rapid dataset/Z race ending in consistent requested, actual, and slider state. Retired NumPy arrays were confirmed garbage-collected after replacement.

### Native controls to smoke-test

- wheel over the panel: change Z;
- Ctrl+wheel: zoom at the current pointer (modifier behavior may vary by OS/browser input routing);
- drag: pan;
- our Z slider: request a specific Z;
- our scale-bar checkbox: update `showScaleBar`;
- our axis-lines checkbox: update `showAxisLines`;
- repeat Z → contrast → channel → Z → toggles many times: every request must return without deadlock.

The scale-bar number and SI prefix may change with zoom. It describes physical distance using the supplied calibration, not viewport pixel count.

### Useful diagnostics

The page reports requested controls, actual position/Z, layout, presentation flags, natural array shape/dtype, coordinate units/scales, and whether the transpose shares memory. This specifically distinguishes our last requested Z from a Z chosen by native Neuroglancer interaction.

## Direct-JS stub history and Phase A

The earlier direct-JS folder was intentionally only a mount/stub; unverified datasource and control methods threw instead of guessing.

V2 Phase A is now an implementation:

```text
our HTML and controls
        ↓
our explicitly sized #ng-viewer div
        ↓
NgImageViewer adapter (only unstable-import boundary)
        ↓
Neuroglancer current-master JS
        ↓
known-supported public precomputed HTTP source
```

There is no iframe. It demonstrates mounting, source initialization, datasource load/render diagnostics, scale bar, axis lines, bidirectional Z state, programmatic layout, and supported broad chrome suppression. Our own layout chrome switches between `xy`, `xy-3d`, `4panel-alt`, and `3d`, restores the default XY view explicitly, and can be placed over the viewer's top/left/bottom edge or outside the viewer. The adapter uses the verified `viewer.layout.restoreState(...)` API rather than simulating clicks on native chrome.

Phase A deliberately omits channel/color/contrast and dataset-selection controls because the public FIB-25 source is single-channel and those controls belong to NumPy dataset semantics. It intentionally does not implement the custom NumPy-backed datasource. That remains v3 so direct embedding is tested independently of a new transport.

Direct-embedding smoke testing exposed two integration-specific failures. Neuroglancer's full-page stylesheet disabled scrolling on the wrapper document; v2 now restores overflow only on the demo page. More importantly, Vite did not correctly bundle Neuroglancer's dependency-owned backend worker: metadata and render layers initialized, but the worker exited before requesting pixel chunks. V2 now routes the exact pinned worker entry through a project-owned Vite entry and prebundles its CommonJS CRC dependency. Verification confirmed a responsive worker, seven multiscale chunk sources, downloaded chunks, and visible FIB-25 electron-microscopy pixels.

## GitHub-only dependency policy

PyPI is not a fallback. Both Python and JS pin the exact official Git revision. The resolution order is:

1. inspect current official `master`;
2. verify and pin one exact known-good commit;
3. examine a branch or pull request only to troubleshoot a concrete upstream issue;
4. use PyPI only as historical comparison, never as an install source for this project.

The Python dependency uses a PEP 508 Git URL in `pyproject.toml`; the JS dependency uses a GitHub commit reference in `package.json`. Lockfiles are included after clean resolution.

## Current upstream install requirements

At the pinned revision:

- upstream Python metadata requires Python `>=3.11`;
- upstream's own `.python-version` is 3.13.9;
- this wrapper pins its verified development interpreter to Python 3.13.8 while permitting 3.11–3.13 (upstream's checkout independently names 3.13.9);
- installing Python Neuroglancer from remote Git requires Node.js and a C++ compiler because the client and native mesh extension may be built;
- the JS package declares Node `>=22.18`;
- a first GitHub build can take appreciable time and should not be described as an unexplained stall.

Consuming the Python Git dependency with `uv sync` does not require a manual Neuroglancer clone. Clone upstream only for editable upstream development, source modification, or its watch build.

## Branch/PR troubleshooting policy

Do not float to an arbitrary branch because it appears newer. Reproduce a concrete issue at the pinned commit, identify the relevant upstream change/PR, test that exact ref in isolation, record the evidence, and only then consider changing the pin. A new pin must be captured in both dependency files and regenerated lockfiles.

## Open questions after v2

- Does the pinned Git Python build complete cleanly on the target macOS/CPU toolchain, and how long is its first build?
- Does native wheel interaction update Python-observed state reliably under repeated use?
- Does the public FIB-25 source load from the target network? The adapter now reports datasource `loading`, `loaded`, or `error` state rather than leaving a gray canvas unexplained.
- Is broad `showUIControls=false` acceptable, or should a later direct integration retain selected native controls?
- Should v3 use an already-supported HTTP format (likely Zarr/OME-Zarr) or a purpose-built custom datasource for arbitrary NumPy subarrays?
- What chunk shape, downsampling, caching, cancellation, and dtype policy should the v3 transport use?

## V3 — NumPy transport milestone started

After Phase A passed, the first V3 milestone kept the direct `NgImageViewer` and added an optional Python-owned NumPy datasource. It deliberately reuses upstream's registered `python://volume/...` frontend/backend and `LocalVolume` metadata/chunk implementation rather than inventing a parallel JS datasource API. A small Python server owns synthetic Dataset A, while Vite proxies same-origin protocol requests to it.

The milestone preserves C,X,Y,Z rank, two channels, `uint16`, and 0.25 × 0.25 × 1.0 µm calibration. A fixed green/magenta shader validates both channels. NPZ transport is used because the pinned raw Python encoder calls the NumPy-removed `ndarray.tostring()` method; upstream is not patched. Verified results include loaded source state, a healthy chunk worker, nine active/nonempty chunk sources, and visible two-channel pixels.

The next V3 milestone now exposes synthetic A/B/C as three distinct Python datasource URLs. They deliberately differ in shape, channel count, pixels, and physical calibration. The adapter replaces the complete viewer state in one restore operation, resetting source, coordinate space, centered position, shader, and layout together. Repeated switching has distinct source identities, so old chunks cannot be mistaken for the newly selected dataset.

Replacement stress/race testing and dynamic NumPy-derived channel/color/contrast controls remained next at that point. The following milestone integrates AcqStore/AcqImage from the sibling local-source checkout while keeping file loading outside the viewer adapter. A broad unit-test suite remains deferred during rapid UI shaping, while stable orientation and calibration invariants receive focused tests.

## V3 — AcqImage demo integration and scientific orientation

AcqStore is now an optional editable demo extra from `../acqstore`; it is deliberately not part of the core Neuroglancer installation. Because current AcqStore requires Python 3.12+, the extra is version-gated while the core project retains upstream Neuroglancer's Python 3.11 compatibility. The direct NumPy server uses only public APIs: `AcqImage.from_array`, `AcqImage.pixels`, and `ensure_sample_file` followed by `AcqImage(path)`.

One narrow adapter materializes full-resolution AcqPixels and converts supported YX/CYX/ZYX/CZYX axis sets into contiguous Neuroglancer `C,X,Y,Z`. It performs the established scientific-display mutation once for the entire volume: each source plane becomes `source_yx.T[::-1, :]`. Therefore source Y becomes displayed X, source X becomes reversed displayed Y, and their calibration/units swap accordingly. Unsupported axes such as T fail clearly rather than being guessed. Focused deterministic tests lock this orientation and calibration contract.

The server now constructs all datasets lazily on first request. Existing A/B/C pass through AcqImage, two new synthetic acquisitions use source `C,Y,X` shapes `2,50000,1024` and `1,30000,100`, and their Gaussian-profile diagonal bands vary angle smoothly along the long displayed-X axis. A sixth preset uses the remote catalog ID `rr30a-two-channel`; selection downloads/caches it through AcqStore and opens the resulting local TIFF. Its verified native metadata is `Z,C,Y,X = 70,2,1024,1024`, uint16, with pixel-unit calibration.

Verification covered orientation tests, Python syntax, production JS build, all six metadata endpoints, a real encoded NPZ chunk from every source, visible long-band rendering, visible two-channel rr30a rendering, rapid six-source replacement, and Z control after replacement. The next logical milestone is generated per-channel color/contrast controls derived from the selected AcqImage metadata.

Current memory policy is lazy creation plus process-lifetime caching: startup is light, but every selected volume remains cached. Before general multi-file runtime use, add an explicit active-dataset/generation lifecycle so retired AcqImage/LocalVolume arrays can be released without allowing late chunk requests from an old source to repopulate stale data.

## V3 — per-channel chrome, view-state API, and channel layouts

The direct viewer now follows the pinned upstream multichannel pattern: one additive image layer per channel, a shared `#uicontrol invlerp contrast` shader, a `vec3 color` LUT control, and an explicit shader channel index. Our right-docked, collapsible Channels overlay generates one row per active channel with a color input, overlaid min/max range handles, and exact numeric inputs. Continuous changes update Neuroglancer trackables directly in JavaScript.

Two layer-group layouts extend composite XY without using `4panel-alt`: `Channels side-by-side` restores a root row and `Channels stacked` restores a root column. Each child is an XY viewer whose layer subset contains exactly one channel layer. Navigation remains linked, while channel rendering is isolated. One-channel sources safely return to ordinary XY.

The public adapter API now includes `getViewState()` and `subscribeViewState(callback)`. The stable snapshot names coordinates and reports dataset/source identity, revision, layout, position, units/scales, and per-panel XY bounds. Bounds are calculated from the actual slice-panel viewport corners and inverse view matrix; access to that pinned internal remains contained in `NgImageViewer`. Display updates and viewer-state updates are animation-frame coalesced, and unchanged snapshots are not emitted.

Upstream's Python integration was re-reviewed before implementing callbacks. Its hosted viewer already uses SockJS to synchronize complete shared state, offers `shared_state.add_changed_callback`, and provides explicit action-to-Python callbacks. The direct `<div>` experiment does not use that Python-hosted client lifecycle, so importing its complete control server would couple the adapter to a second viewer architecture. Instead, this demo preserves the same non-blocking subscription semantics behind a narrow transport: JavaScript posts coalesced snapshots to `/api/view-state`, and `ViewStateDispatcher.subscribe()` invokes Python callbacks on a separate dispatcher thread and returns an unsubscribe function.

Live browser verification at the pinned commit covered the public FIB-25 image, Dataset A composite rendering, independent C0/C1 channel selection, LUT and contrast mutation, side-by-side and stacked panels, shared navigation, finite per-panel XY bounds, loaded layers, a healthy worker, and Python callback delivery. Deferred callbacks for channel visibility and other display-mode changes remain future work.

Follow-up smoke testing exposed a precise shader-control semantic error: the implementation changed invlerp `window`, but pinned Neuroglancer renders from invlerp `range`; `window` only controls the broader UI/histogram domain. That made every contrast edit visually inert and left low-valued rr30a pixels nearly black despite a healthy download, TIFF, datasource, and worker. The adapter now updates `range`. The Python dataset endpoint computes exact observed min/max for every materialized channel and returns those values as the UI domain. This avoids guessing camera bit depth from `uint16`.

That policy is now explicit: a fixed 65,536-bin uint16 histogram calculates each channel's 1st–99th percentile automatic range without sorting or copying the full channel. Exact observed min/max remain the slider and number-input domain; automatic min/max seed rendering and are restored by the per-channel Auto button. Current contrast is separate state. Focused tests cover domains, percentile windows, multiple channels, invalid dtype, and invalid percentile bounds.

The view-state contract now keeps index-space `position`/`xyBounds` and adds calibrated `physicalPosition`/`xyPhysicalBounds`. The example `log_view_state()` subscriber reports X, Y, and Z with units through a concise source-aware Python logger. Long datasets define source-Y as `0.002 s` and source-X as `0.25 um`; after the established transpose, those become displayed X and Y. Neuroglancer's coordinate scales provide the required non-square physical aspect, and the adapter fits the initial calibrated extent. Pinned upstream supports native coordinate names/units and labeled scale bars (including separate scales for differing units), but no conventional ticked text axes in the slice canvas; no CSS imitation was added.

## High-priority stabilization before ROI work

Before adding ROI CRUD chrome, perform a bounded architecture review around four contracts: dataset registration/metadata, channel display state, viewer-state callbacks, and resource lifecycle. Extract a small public Python server/application wrapper so external callers can register an AcqImage or NumPy dataset, subscribe to state, start/stop transport, and replace datasets without manipulating HTTP handler globals. Keep toolbar composition separate from adapter state, and keep all pinned unstable Neuroglancer access inside `NgImageViewer`. ROI model/store, adapter API, annotation rendering, and toolbar DOM should then be separate layers over one public contract.

## Clean-room install and run

From a fresh unzip, with Git, `uv`, compiler tools, and a suitable Node available:

```bash
cd ng-array-demo
uv sync --frozen
uv run python server.py
```

Visit `http://127.0.0.1:8000`, exercise all controls repeatedly, then use wheel and Ctrl+wheel inside the iframe while watching diagnostics.

For Phase A:

```bash
cd direct-js
npm ci
npm run dev
```

For the NumPy transport preset, also run from the project root:

```bash
uv sync --extra acqstore-demo
uv run --extra acqstore-demo python direct_numpy_server.py
```

Open the printed local URL and confirm diagnostics report `directMount: true`, `iframeCount: 0`, plus loaded channel layers and finite `xyBounds`. Select Dataset A and confirm C0 is the filled object and C1 is the square/diagonal pattern. Change each LUT and contrast range; confirm only its channel changes and diagnostics show the new invlerp `range`. Select rr30a; confirm two visible channels and observed control maxima near 3452 and 4500. Select side-by-side and stacked; confirm one channel appears in each panel and navigation stays linked. Select each long dataset; confirm the image fits the XY panel, its physical aspect is non-square, and scale bars identify seconds and micrometers. Return to composite XY, use wheel and the Z number control in both directions, and confirm the Python terminal reports calibrated X/Y/Z with units. Also toggle scale bar/axis lines and exercise the remaining layouts and chrome placements. Then run the production build check:

```bash
npm run build
```

If clean-room installation or runtime fails, preserve the complete terminal/browser-console error and the pinned commit. Do not silently substitute PyPI or patch Neuroglancer CSS.
