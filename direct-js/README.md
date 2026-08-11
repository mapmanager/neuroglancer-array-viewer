# Direct-JS Phase A

This experiment imports the exact same pinned Neuroglancer GitHub commit as the Python project and mounts it into our `#ng-viewer` div through an `NgImageViewer` adapter. It uses no iframe.

It deliberately uses the official public FIB-25 precomputed datasource through Neuroglancer's canonical Google Cloud Storage URL. This isolates direct embedding and viewer control from the future custom NumPy transport. The latter is deferred to v3.

```bash
npm ci
npm run dev
```

Node.js 22.18 or newer is required by this Neuroglancer revision. The public source requires network access and WebGL2. Its metadata describes a single-channel `uint8` electron-microscopy image with X/Y/Z dimensions, 8 nm isotropic voxels at full resolution, and a full-resolution shape of 6446 × 6643 × 8090. It has no C or T dimension.

`vite.config.js` deliberately excludes Neuroglancer from Vite's development dependency optimizer and routes its pinned backend worker through `src/ng-chunk-worker.js`. Neuroglancer locates that worker beside an upstream module with `import.meta.url`; without the explicit project entry Vite does not bundle the dependency-owned worker correctly, metadata loads but pixel chunks are never requested, and the viewer remains gray. The configuration also prebundles the specific CommonJS modules imported by the frontend and worker graphs.

`src/NgImageViewer.js` is the sole unstable-API boundary. It demonstrates direct mounting, source initialization, programmatic layout, scale-bar and axis-line toggles, bidirectional Z state, datasource diagnostics, and supported global chrome suppression. At the pinned revision, the per-panel related-layout buttons are constructed by the data-panel layout and have no granular public visibility option; this demo does not hide them with guessed CSS.

The custom layout chrome is our own DOM and can be placed over the top, left, or bottom of the viewer, or outside it. `XY` restores the initial single-plane view; the other buttons select `XY + 3D`, `4 panel`, or `3D` through Neuroglancer layout state. The Z number control and native wheel navigation observe the same viewer position.

Neuroglancer's default-viewer stylesheet assumes it owns the full page and sets document overflow to hidden. This wrapper overrides that rule only on `.ng-array-demo-page`, so the embedded viewer retains its layout while the surrounding page and diagnostics remain scrollable.

Expected Phase A diagnostics are `directMount: true`, `iframeCount: 0`, and a layer whose datasource state changes from `loading` to `loaded` with at least one render layer. The initial position and zoom come from upstream's published FIB-25 example. If the public source cannot be reached, the concrete datasource error is shown there.

Phase A intentionally has no channel, color, contrast, or dataset controls: those would be misleading for this single-channel public source. They return only after the custom Python/NumPy datasource is designed and direct embedding is stable.
