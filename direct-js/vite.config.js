import {defineConfig} from "vite";

export default defineConfig({
  plugins: [{
    name: "neuroglancer-chunk-worker-entry",
    enforce: "pre",
    transform(code, id) {
      if (!id.split("?", 1)[0].endsWith("/neuroglancer/lib/data_management_context.js")) return;
      const upstreamWorker = `new Worker(
      /* webpackChunkName: "neuroglancer_chunk_worker" */
      new URL("./chunk_worker.bundle.js", import.meta.url),
      { type: "module" }
    )`;
      if (!code.includes(upstreamWorker)) {
        throw new Error("Pinned Neuroglancer chunk-worker expression changed");
      }
      return `import NgArrayDemoChunkWorker from "/src/ng-chunk-worker.js?worker";\n${code.replace(
        upstreamWorker,
        "new NgArrayDemoChunkWorker()",
      )}`;
    },
  }],
  // Neuroglancer resolves its worker bundles relative to import.meta.url.
  // Vite's dev dependency optimizer otherwise moves the importing module into
  // node_modules/.vite/deps without copying chunk_worker.bundle.js beside it.
  optimizeDeps: {
    exclude: ["neuroglancer"],
    // Neuroglancer imports this CommonJS package with a default import. Keep
    // that dependency optimized even though Neuroglancer itself is excluded.
    include: [
      "codemirror",
      "codemirror/addon/lint/lint.js",
      "codemirror/mode/javascript/javascript.js",
      "codemirror/addon/fold/foldcode.js",
      "codemirror/addon/fold/foldgutter.js",
      "codemirror/addon/fold/brace-fold.js",
      "crc-32",
      "crc-32/crc32c.js",
      "core-js/actual/symbol/dispose.js",
      "core-js/actual/symbol/async-dispose.js",
    ],
  },
});
