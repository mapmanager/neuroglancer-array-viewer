import "neuroglancer";
import { setupDefaultViewer } from "neuroglancer/unstable/ui/default_viewer_setup.js";

export const PUBLIC_SOURCE = "precomputed://gs://neuroglancer-public-data/flyem_fib-25/image";

/** Our narrow adapter: this is the only module that imports unstable NG internals. */
export class NgImageViewer {
  constructor(target, onChange = () => {}) {
    this.viewer = setupDefaultViewer({target});
    this.onChange = onChange;
    this.viewer.state.changed.add(() => this.onChange(this.getDiagnostics()));
  }

  setSource(source = PUBLIC_SOURCE) {
    this.viewer.state.restoreState({
      dimensions: {x:[8e-9,"m"], y:[8e-9,"m"], z:[8e-9,"m"]},
      position: [3000, 3000, 3000],
      crossSectionScale: 1,
      layers: [{type:"image", source, name:"FIB-25 public image"}],
      layout: "xy",
      showScaleBar: true,
      showAxisLines: false,
    });
    this.hideSupportedChrome();
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
  setLayout(value) { this.viewer.layout.specification.restoreState(value); }

  getDiagnostics() {
    return {
      source: PUBLIC_SOURCE,
      directMountTarget: this.viewer.display.container?.id ?? "ng-viewer",
      state: this.viewer.state.toJSON(),
      limitations: [
        "The per-panel related-layout buttons have no granular supported visibility flag at this pinned revision.",
        "Phase A uses an upstream-supported public HTTP datasource; NumPy transport is deferred to v3."
      ]
    };
  }

  dispose() { this.viewer.dispose(); }
}
