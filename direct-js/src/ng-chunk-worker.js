// Project-owned bundler entry for Neuroglancer's backend worker. Keeping this
// entry under src lets Vite analyze and bundle the pinned upstream worker.
import "neuroglancer/unstable/chunk_worker.bundle.js";
import "neuroglancer/unstable/datasource/python/backend.js";
