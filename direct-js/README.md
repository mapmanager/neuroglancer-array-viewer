# Direct-JS Phase A

This experiment imports the exact same pinned Neuroglancer GitHub commit as the Python project and mounts it into our `#ng-viewer` div through an `NgImageViewer` adapter. It uses no iframe.

It deliberately uses the official public FIB-25 precomputed HTTP datasource. This isolates direct embedding and viewer control from the future custom NumPy transport. The latter is deferred to v3.

```bash
npm install
npm run dev
```

Node.js 22.18 or newer is required by this Neuroglancer revision. The public source requires network access and WebGL2.

`src/NgImageViewer.js` is the sole unstable-API boundary. It demonstrates direct mounting, source initialization, programmatic layout, scale-bar and axis-line toggles, state reads, and supported global chrome suppression. At the pinned revision, the per-panel related-layout buttons are constructed by the data-panel layout and have no granular public visibility option; this demo does not hide them with guessed CSS.
