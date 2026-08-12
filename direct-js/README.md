# Frontend development

`direct-js/` contains the editable JavaScript source for the Neuroglancer Array
Viewer. The production build is written to `src/ng_viewer/static/` and served
by the Python package; Node and Vite are not runtime requirements for Python
users.

## Development server

Start the development dataset server from the repository root:

```bash
uv run python direct_numpy_server.py
```

Then start Vite from this directory:

```bash
npm ci
NG_ARRAY_DEMO_NUMPY_SERVER=http://127.0.0.1:8001 npm run dev
```

The main Vite page is the production UI. JavaScript usage examples live in
`examples/` and share this project’s pinned dependencies, worker transform,
and adapter implementation.

## Build

```bash
npm run build
```

The generated HTML, JavaScript, CSS, WASM, and worker files are package data
under `src/ng_viewer/static/`. The custom worker entry is required because
Neuroglancer locates its backend worker relative to `import.meta.url`; the
verified Vite transform routes that worker through `src/ng-chunk-worker.js`.

## Source boundary

`src/NgImageViewer.js` is the only module that accesses pinned unstable
Neuroglancer APIs. It owns direct mounting, source replacement, layouts,
channel display controls, Z navigation, initial fitting, view-state snapshots,
and the documented scoped CSS compatibility toggles.

The page entry in `src/main.js` composes the packaged controls and applies
`NgConfig`. Dataset selection and diagnostics are hidden by default and are
intended for development configurations. Optional presentation chrome also
defaults hidden; Options and multi-plane Z navigation remain available.

The native display-dimensions widget and two related-layout buttons have no
granular upstream visibility flags at the pinned revision. Their selectors are
scoped to the viewer root and must be revalidated whenever the Neuroglancer
commit changes.

Every source is concealed until its intended layers are ready and a live XY
projection has been centered and fitted. There is no guessed delay.
Neuroglancer does not expose a rendered-pixel-completion event, so slow chunk
delivery can still populate progressively after the fitted canvas appears.
