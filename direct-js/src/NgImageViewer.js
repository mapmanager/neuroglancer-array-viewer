import "neuroglancer";
import "neuroglancer/unstable/datasource/python/register_default.js";
import { setupDefaultViewer } from "neuroglancer/unstable/ui/default_viewer_setup.js";

export const PUBLIC_SOURCE = "precomputed://gs://neuroglancer-public-data/flyem_fib-25/image";
export const NUMPY_SOURCE = "python://volume/direct-demo";
export const SUPPORTED_LAYOUTS = new Set(["xy", "xy-3d", "4panel-alt", "3d"]);

const SOURCE_PRESETS = {
  public: {
    source: PUBLIC_SOURCE,
    name: "FIB-25 public image",
    dimensions: {x:[8e-9,"m"], y:[8e-9,"m"], z:[8e-9,"m"]},
    position: [2980.1868, 3153.9294, 4045],
    crossSectionScale: 2.886371,
  },
  numpy: {
    source: NUMPY_SOURCE,
    name: "Python NumPy · Dataset A",
    dimensions: {x:[0.25,"um"], y:[0.25,"um"], z:[1,"um"]},
    position: [512, 512, 35],
    crossSectionScale: 1,
    shader: `void main() {
  float c0 = toNormalized(getDataValue(0));
  float c1 = toNormalized(getDataValue(1));
  emitRGB(clamp(c0 * vec3(0.0, 1.0, 0.0) + c1 * vec3(1.0, 0.0, 1.0), 0.0, 1.0));
}`,
  },
};

/** Our narrow adapter: this is the only module that imports unstable NG internals. */
export class NgImageViewer {
  constructor(target, onChange = () => {}) {
    this.target = target;
    this.viewer = setupDefaultViewer({target});
    this.onChange = onChange;
    this.workerError = null;
    const worker = this.viewer.dataContext.worker;
    worker.addEventListener("error", (event) => {
      this.workerError = {
        message: event.message || "Neuroglancer chunk worker failed",
        filename: event.filename || undefined,
        line: event.lineno || undefined,
        column: event.colno || undefined,
        detail: event.error?.stack || String(event.error || "") || undefined,
      };
      this.onChange(this.getDiagnostics());
    });
    worker.addEventListener("messageerror", () => {
      this.workerError = "Neuroglancer chunk worker message could not be decoded";
      this.onChange(this.getDiagnostics());
    });
    this.changeScheduled = false;
    this.viewer.state.changed.add(() => {
      if (this.changeScheduled) return;
      this.changeScheduled = true;
      requestAnimationFrame(() => {
        this.changeScheduled = false;
        this.onChange(this.getDiagnostics());
      });
    });
  }

  setSource(presetName = "public") {
    const preset = SOURCE_PRESETS[presetName];
    if (!preset) throw new Error(`Unknown datasource preset: ${presetName}`);
    this.presetName = presetName;
    this.source = preset.source;
    this.currentLayout = "xy";
    // Configure supported UI visibility before restoring asynchronous layer
    // state. Changing it immediately after restore can leave the newly loaded
    // render source unattached until another viewer configuration change.
    this.hideSupportedChrome();
    this.viewer.state.restoreState({
      dimensions: preset.dimensions,
      // This position and scale are taken from upstream's published FIB-25
      // example rather than inferred from the volume bounds.
      position: preset.position,
      crossSectionScale: preset.crossSectionScale,
      layers: [{type:"image", source:preset.source, name:preset.name, shader:preset.shader}],
      layout: "xy",
      showScaleBar: true,
      showAxisLines: false,
    });
  }

  hideSupportedChrome() {
    const ui = this.viewer.uiConfiguration;
    ui.showUIControls.value = false;
    ui.showTopBar.value = false;
    ui.showLocation.value = false;
    ui.showLayerPanel.value = false;
  }

  setScaleBar(value) { this.viewer.showScaleBar.value = Boolean(value); }
  setAxisLines(value) { this.viewer.showAxisLines.value = Boolean(value); }

  setLayout(value) {
    if (!SUPPORTED_LAYOUTS.has(value)) throw new Error(`Unsupported layout: ${value}`);
    this.viewer.layout.restoreState(value);
    this.currentLayout = value;
  }

  getZAxisIndex() {
    return this.viewer.coordinateSpace.value.names.indexOf("z");
  }

  getZ() {
    const index = this.getZAxisIndex();
    return index < 0 ? undefined : this.viewer.position.value[index];
  }

  setZ(value) {
    const index = this.getZAxisIndex();
    if (index < 0) throw new Error("The current source has no z dimension");
    const position = Float32Array.from(this.viewer.position.value);
    position[index] = Number(value);
    this.viewer.position.value = position;
  }

  getLayerDiagnostics() {
    return this.viewer.layerManager.managedLayers.map((managedLayer) => {
      const layer = managedLayer.layer;
      return {
        name: managedLayer.name,
        visible: managedLayer.visible,
        ready: managedLayer.isReady(),
        renderLayerCount: layer?.renderLayers.length ?? 0,
        dataSources: (layer?.dataSources ?? []).map((dataSource) => {
          const {loadState} = dataSource;
          return {
            url: dataSource.spec.url,
            state: loadState === undefined
              ? "loading"
              : loadState.error === undefined ? "loaded" : "error",
            error: loadState?.error ? String(loadState.error) : undefined,
            subsourceCount: loadState?.error === undefined
              ? loadState?.subsources?.length ?? 0
              : 0,
          };
        }),
      };
    });
  }

  getDiagnostics() {
    let layout = this.currentLayout ?? "xy";
    try {
      layout = this.viewer.layout.toJSON();
      this.currentLayout = layout;
    } catch {
      // State changes are emitted during layout replacement. Keep the last stable value.
    }
    return {
      phase: this.presetName === "numpy" ? "Direct-JS NumPy transport milestone" : "Direct-JS Phase A",
      datasourcePreset: this.presetName ?? "public",
      source: this.source ?? PUBLIC_SOURCE,
      directMount: true,
      iframeCount: this.target.querySelectorAll("iframe").length,
      zAxisIndex: this.getZAxisIndex(),
      z: this.getZ(),
      layout,
      showScaleBar: this.viewer.showScaleBar.value,
      showAxisLines: this.viewer.showAxisLines.value,
      coordinateNames: [...this.viewer.coordinateSpace.value.names],
      position: [...this.viewer.position.value],
      layers: this.getLayerDiagnostics(),
      chunkWorkerError: this.workerError,
      limitations: [
        "The native per-panel related-layout buttons have no granular supported visibility flag at this pinned revision.",
        "The public preset uses an upstream-supported public datasource.",
        "The NumPy preset uses upstream's Python datasource protocol through a local same-origin proxy.",
        "Dataset replacement and NumPy-derived channel/contrast controls remain deferred until transport smoke testing passes."
      ]
    };
  }

  dispose() { this.viewer.dispose(); }
}
