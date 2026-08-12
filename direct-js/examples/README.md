# JavaScript examples

These examples reuse the pinned dependencies, worker transform, and
`NgImageViewer` adapter from `direct-js`; they are not standalone `file://`
pages.

Start a Python dataset server from the repository root:

```bash
uv run python examples/python/python_demo.py
```

For frontend development, point Vite at that printed transport port and run it
from `direct-js/`:

```bash
NG_ARRAY_DEMO_NUMPY_SERVER=http://127.0.0.1:<port> npm run dev
```

Then open `/examples/basic.html` on the Vite URL. The example mounts
`NgImageViewer` directly into a `<div>`, loads the Python-selected dataset, and
prints semantic view-state updates to the browser console.
