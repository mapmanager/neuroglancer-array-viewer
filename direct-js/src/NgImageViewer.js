import "neuroglancer";
import "neuroglancer/unstable/datasource/python/register_default.js";
import { setupDefaultViewer } from "neuroglancer/unstable/ui/default_viewer_setup.js";

export const PUBLIC_SOURCE = "precomputed://gs://neuroglancer-public-data/flyem_fib-25/image";
export const NUMPY_SOURCE_PREFIX = "python://volume/direct-demo-";
export const SUPPORTED_LAYOUTS = new Set([
  "xy", "xy-3d", "4panel-alt", "3d", "channels-row", "channels-column",
]);

const CHANNEL_SHADER = `#uicontrol invlerp contrast
#uicontrol vec3 color color
void main() {
  float value = contrast();
  if (VOLUME_RENDERING) {
    emitRGBA(vec4(color * value, value));
  } else {
    emitRGB(color * value);
  }
}`;

const DEFAULT_CHANNEL_COLORS = ["#00ff00", "#ff00ff", "#00aaff", "#ff7a00"];

function channels(count, windows, colors = DEFAULT_CHANNEL_COLORS) {
  return Array.from({length: count}, (_, index) => ({
    index,
    name: `C${index}`,
    color: colors[index % colors.length],
    domain: [0, 65535],
    contrast: windows[index] ?? windows[0] ?? [0, 65535],
  }));
}

const SOURCE_PRESETS = {
  public: {
    source: PUBLIC_SOURCE,
    name: "FIB-25 public image",
    dimensions: {x:[8e-9,"m"], y:[8e-9,"m"], z:[8e-9,"m"]},
    position: [2980.1868, 3153.9294, 4045],
    crossSectionScale: 2.886371,
    channels: [{index:0, name:"image", color:"#ffffff", domain:[0,255], contrast:[0,255]}],
  },
  "numpy-a": {
    source: `${NUMPY_SOURCE_PREFIX}a`,
    name: "Python NumPy · Dataset A",
    dataset: {key:"a", sourceAxes:"CZYX", sourceShape:[2,70,1024,1024], displayShapeXYZ:[1024,1024,70]},
    dimensions: {x:[0.25,"um"], y:[0.25,"um"], z:[1,"um"]},
    position: [512, 512, 35],
    crossSectionScale: 1,
    channels: channels(2, [[100,55000], [0,55000]]),
  },
  "numpy-b": {
    source: `${NUMPY_SOURCE_PREFIX}b`,
    name: "Python NumPy · Dataset B",
    dataset: {key:"b", sourceAxes:"CZYX", sourceShape:[1,31,512,768], displayShapeXYZ:[512,768,31]},
    dimensions: {x:[0.40,"um"], y:[0.65,"um"], z:[2.5,"um"]},
    position: [256, 384, 15],
    crossSectionScale: 1,
    channels: channels(1, [[0,55000]], ["#00bfff"]),
  },
  "numpy-c": {
    source: `${NUMPY_SOURCE_PREFIX}c`,
    name: "Python NumPy · Dataset C",
    dataset: {key:"c", sourceAxes:"CZYX", sourceShape:[3,18,640,384], displayShapeXYZ:[640,384,18]},
    dimensions: {x:[0.55,"um"], y:[0.18,"um"], z:[0.8,"um"]},
    position: [320, 192, 9],
    crossSectionScale: 1,
    channels: channels(3, [[0,55000], [0,55000], [0,55000]], ["#ff3b30", "#33c759", "#0a84ff"]),
  },
  "numpy-long-2c": {
    source: `${NUMPY_SOURCE_PREFIX}long-2c`,
    name: "AcqImage synthetic · 2C long Gaussian bands",
    dataset: {key:"long-2c", sourceAxes:"CYX", sourceShape:[2,50000,1024], displayShapeXYZ:[50000,1024,1]},
    dimensions: {x:[0.002,"s"], y:[0.25,"um"], z:[1,""]},
    position: [25000, 512, 0.5],
    crossSectionScale: 60,
    fitToView: true,
    channels: channels(2, [[700,52700], [700,48700]], ["#ff7a0d", "#00d9ff"]),
  },
  "numpy-long-1c": {
    source: `${NUMPY_SOURCE_PREFIX}long-1c`,
    name: "AcqImage synthetic · 1C long Gaussian bands",
    dataset: {key:"long-1c", sourceAxes:"CYX", sourceShape:[1,30000,100], displayShapeXYZ:[30000,100,1]},
    dimensions: {x:[0.002,"s"], y:[0.25,"um"], z:[1,""]},
    position: [15000, 50, 0.5],
    crossSectionScale: 38,
    fitToView: true,
    channels: channels(1, [[700,52700]], ["#ffc728"]),
  },
  "numpy-rr30a": {
    source: `${NUMPY_SOURCE_PREFIX}rr30a`,
    name: "AcqStore sample · rr30a two-channel",
    dataset: {key:"rr30a", sampleId:"rr30a-two-channel", sourceAxes:"ZCYX", sourceShape:[70,2,1024,1024], displayShapeXYZ:[1024,1024,70]},
    dimensions: {x:[1,""], y:[1,""], z:[1,""]},
    position: [512, 512, 35],
    crossSectionScale: 1,
    channels: channels(2, [[0,384], [0,296]]),
  },
};

function colorToFloat32(color) {
  const value = color.startsWith("#") ? color.slice(1) : color;
  if (!/^[0-9a-f]{6}$/i.test(value)) throw new Error(`Invalid channel color: ${color}`);
  return new Float32Array([0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16) / 255));
}

function normalizedScale([scale, unit]) {
  const multipliers = {m: 1, um: 1e-6, s: 1, "": 1};
  const multiplier = multipliers[unit];
  if (multiplier === undefined) throw new Error("Unsupported fit unit: " + unit);
  return scale * multiplier;
}

function channelLayerSpec(preset, channel) {
  return {
    type: "image",
    source: preset.source,
    name: `${preset.name} · ${channel.name}`,
    shader: CHANNEL_SHADER,
    shaderControls: {
      contrast: {range: channel.contrast, window: channel.domain, channel: [channel.index]},
      color: channel.color,
    },
    opacity: 1,
    blend: "additive",
  };
}

/** Our narrow adapter: this is the only module that imports unstable NG internals. */
export class NgImageViewer {
  constructor(target, onChange = () => {}) {
    this.target = target;
    this.viewer = setupDefaultViewer({target});
    this.onChange = onChange;
    this.subscribers = new Set();
    this.viewRevision = 0;
    this.lastViewStateSignature = "";
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
      this.emitChange();
    });
    worker.addEventListener("messageerror", () => {
      this.workerError = "Neuroglancer chunk worker message could not be decoded";
      this.emitChange();
    });
    this.changeScheduled = false;
    const scheduleChange = () => {
      if (this.changeScheduled) return;
      this.changeScheduled = true;
      requestAnimationFrame(() => {
        this.changeScheduled = false;
        this.emitChange();
      });
    };
    this.viewer.state.changed.add(scheduleChange);
    this.viewer.display.changed.add(scheduleChange);
    this.viewer.coordinateSpace.changed.add(() => {
      if (!this.fitConfiguration || this.fitScheduled) return;
      this.fitScheduled = true;
      requestAnimationFrame(() => {
        this.fitScheduled = false;
        this.applyFitConfiguration();
      });
    });
  }

  async setSource(presetName = "public") {
    const preset = SOURCE_PRESETS[presetName];
    if (!preset) throw new Error(`Unknown datasource preset: ${presetName}`);
    const generation = (this.sourceGeneration ?? 0) + 1;
    this.sourceGeneration = generation;
    let channels = preset.channels;
    if (preset.dataset) {
      const response = await fetch(`/api/dataset/${preset.dataset.key}`);
      if (!response.ok) throw new Error(`Dataset metadata failed: ${response.status} ${response.statusText}`);
      const metadata = await response.json();
      channels = preset.channels.map((channel, index) => {
        const domain = metadata.channelRanges?.[index];
        if (!domain || domain.length !== 2 || domain[0] >= domain[1]) return channel;
        return {...channel, domain, contrast: domain};
      });
    }
    if (generation !== this.sourceGeneration) return false;
    this.presetName = presetName;
    this.source = preset.source;
    this.currentLayout = "xy";
    this.channels = channels.map((channel) => ({
      ...channel,
      domain: [...channel.domain],
      contrast: [...channel.contrast],
    }));
    // Configure supported UI visibility before restoring asynchronous layer
    // state. Changing it immediately after restore can leave the newly loaded
    // render source unattached until another viewer configuration change.
    this.hideSupportedChrome();
    const fit = preset.fitToView ? this.getFitConfiguration(preset) : null;
    this.fitConfiguration = fit;
    this.viewer.state.restoreState({
      dimensions: preset.dimensions,
      // This position and scale are taken from upstream's published FIB-25
      // example rather than inferred from the volume bounds.
      position: preset.position,
      relativeDisplayScales: fit?.relativeDisplayScales,
      crossSectionScale: fit?.crossSectionScale ?? preset.crossSectionScale,
      layers: this.channels.map((channel) => channelLayerSpec(preset, channel)),
      layout: "xy",
      showScaleBar: true,
      showAxisLines: false,
    });
    this.applyFitConfiguration();
    return true;
  }

  applyFitConfiguration() {
    const fit = this.fitConfiguration;
    if (!fit) return;
    const factors = new Float64Array(
      this.viewer.relativeDisplayScales.value.factors,
    );
    const yIndex = this.viewer.coordinateSpace.value.names.indexOf("y");
    if (yIndex < 0) return;
    factors[yIndex] = fit.relativeDisplayScales.y;
    this.viewer.relativeDisplayScales.setFactors(factors);
    this.viewer.crossSectionScale.value = fit.crossSectionScale;
  }

  getFitConfiguration(preset = SOURCE_PRESETS[this.presetName]) {
    const shape = preset?.dataset?.displayShapeXYZ;
    if (!shape) return null;
    const width = Math.max(1, this.target.clientWidth * 0.92);
    const height = Math.max(1, this.target.clientHeight * 0.88);
    const targetAspect = width / height;
    const yVoxelFactor = shape[0] / (shape[1] * targetAspect);
    // Seconds and metres are not dimensionally comparable. Relative display
    // scales are the supported NG state for choosing their visual ratio while
    // CoordinateSpace continues to retain the calibrated values and units.
    return {
      relativeDisplayScales: {
        y: yVoxelFactor
          * normalizedScale(preset.dimensions.x)
          / normalizedScale(preset.dimensions.y),
      },
      crossSectionScale: Math.max(
        shape[0] / width,
        shape[1] * yVoxelFactor / height,
      ),
    };
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
    if (value === "channels-row" || value === "channels-column") {
      if (this.channels.length < 2) {
        this.viewer.layout.restoreState("xy");
        value = "xy";
      } else {
        const type = value === "channels-row" ? "row" : "column";
        this.viewer.layout.restoreState({
          type,
          children: this.channels.map((channel) => ({
            type: "viewer",
            layers: [this.getChannelLayerName(channel.index)],
            layout: "xy",
          })),
        });
      }
    } else {
      this.viewer.layout.restoreState(value);
    }
    this.currentLayout = value;
  }

  getChannelLayerName(index) {
    return `${SOURCE_PRESETS[this.presetName].name} · ${this.channels[index].name}`;
  }

  getChannelLayer(index) {
    const name = this.getChannelLayerName(index);
    return this.viewer.layerManager.managedLayers.find((layer) => layer.name === name)?.layer;
  }

  getChannels() {
    return (this.channels ?? []).map((channel) => ({
      ...channel, domain: [...channel.domain], contrast: [...channel.contrast],
    }));
  }

  setChannelColor(index, color) {
    const channel = this.channels?.[index];
    if (!channel) throw new Error(`Invalid channel index: ${index}`);
    const layer = this.getChannelLayer(index);
    const control = layer?.shaderControlState.value.get("color");
    if (!control) throw new Error(`Color control for channel ${index} is not ready`);
    control.trackable.value = colorToFloat32(color);
    channel.color = color.toLowerCase();
    this.emitChange();
  }

  setChannelWindow(index, low, high) {
    const channel = this.channels?.[index];
    if (!channel) throw new Error(`Invalid channel index: ${index}`);
    low = Number(low);
    high = Number(high);
    if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) {
      throw new Error(`Expected finite channel bounds with min < max; received ${low}, ${high}`);
    }
    const [rangeLow, rangeHigh] = channel.domain;
    low = Math.max(rangeLow, Math.min(low, rangeHigh - 1));
    high = Math.max(low + 1, Math.min(high, rangeHigh));
    const layer = this.getChannelLayer(index);
    const control = layer?.shaderControlState.value.get("contrast");
    if (!control) throw new Error(`Contrast control for channel ${index} is not ready`);
    control.trackable.value = {
      ...control.trackable.value,
      range: [low, high],
      window: [...channel.domain],
      channel: [index],
    };
    channel.contrast = [low, high];
    this.emitChange();
  }

  subscribeViewState(callback) {
    if (typeof callback !== "function") throw new TypeError("Expected a view-state callback");
    this.subscribers.add(callback);
    callback(this.getViewState());
    return () => this.subscribers.delete(callback);
  }

  emitChange() {
    const diagnostics = this.getDiagnostics();
    this.onChange(diagnostics);
    if (this.subscribers.size === 0) return;
    const viewState = this.getViewState();
    const signature = JSON.stringify({...viewState, revision: undefined});
    if (signature === this.lastViewStateSignature) return;
    this.lastViewStateSignature = signature;
    viewState.revision = ++this.viewRevision;
    for (const callback of [...this.subscribers]) callback(viewState);
  }

  getXYBounds() {
    const xIndex = this.viewer.coordinateSpace.value.names.indexOf("x");
    const yIndex = this.viewer.coordinateSpace.value.names.indexOf("y");
    if (xIndex < 0 || yIndex < 0) return null;
    const bounds = [];
    for (const panel of this.viewer.display.panels) {
      const parameters = panel.sliceView?.projectionParameters?.value;
      if (!parameters || !panel.visible) continue;
      const {width, height, invViewMatrix, displayDimensionRenderInfo} = parameters;
      if (width <= 0 || height <= 0) continue;
      const indices = [...displayDimensionRenderInfo.displayDimensionIndices];
      const xSlot = indices.indexOf(xIndex);
      const ySlot = indices.indexOf(yIndex);
      if (xSlot < 0 || ySlot < 0) continue;
      const points = [[-width/2,-height/2], [width/2,-height/2], [-width/2,height/2], [width/2,height/2]];
      const values = points.map(([px, py]) => ({
        x: invViewMatrix[xSlot] * px + invViewMatrix[4 + xSlot] * py + invViewMatrix[12 + xSlot],
        y: invViewMatrix[ySlot] * px + invViewMatrix[4 + ySlot] * py + invViewMatrix[12 + ySlot],
      }));
      bounds.push({
        xMin: Math.min(...values.map((value) => value.x)),
        xMax: Math.max(...values.map((value) => value.x)),
        yMin: Math.min(...values.map((value) => value.y)),
        yMax: Math.max(...values.map((value) => value.y)),
      });
    }
    return bounds.length === 0 ? null : bounds;
  }

  getViewState() {
    const coordinateSpace = this.viewer.coordinateSpace.value;
    const presetDimensions = SOURCE_PRESETS[this.presetName]?.dimensions;
    const position = Object.fromEntries(coordinateSpace.names.map((name, index) => [name, this.viewer.position.value[index]]));
    const physicalPosition = Object.fromEntries(
      coordinateSpace.names.map((name, index) => {
        const dimension = presetDimensions?.[name];
        return [name, {
          value: this.viewer.position.value[index]
            * (dimension?.[0] ?? coordinateSpace.scales[index]),
          unit: dimension?.[1] ?? coordinateSpace.units[index],
        }];
      }),
    );
    const xyBounds = this.getXYBounds();
    const xIndex = coordinateSpace.names.indexOf("x");
    const yIndex = coordinateSpace.names.indexOf("y");
    const xDimension = presetDimensions?.x ?? [
      coordinateSpace.scales[xIndex], coordinateSpace.units[xIndex],
    ];
    const yDimension = presetDimensions?.y ?? [
      coordinateSpace.scales[yIndex], coordinateSpace.units[yIndex],
    ];
    const xyPhysicalBounds = xyBounds?.map((bounds) => ({
      x: {min: bounds.xMin * xDimension[0], max: bounds.xMax * xDimension[0], unit: xDimension[1]},
      y: {min: bounds.yMin * yDimension[0], max: bounds.yMax * yDimension[0], unit: yDimension[1]},
    })) ?? null;
    return {
      datasetId: this.presetName ?? "public",
      source: this.source ?? PUBLIC_SOURCE,
      layout: this.currentLayout ?? "xy",
      position,
      physicalPosition,
      xyBounds,
      xyPhysicalBounds,
      coordinateNames: [...coordinateSpace.names],
      units: [...coordinateSpace.units],
      scales: [...coordinateSpace.scales],
      revision: this.viewRevision,
    };
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
      const shaderControls = {};
      for (const [name, control] of layer?.shaderControlState?.value ?? []) {
        const value = control.trackable.value;
        shaderControls[name] = ArrayBuffer.isView(value)
          ? [...value]
          : JSON.parse(JSON.stringify(value));
      }
      return {
        name: managedLayer.name,
        localPosition: [...managedLayer.localPosition.value],
        visible: managedLayer.visible,
        ready: managedLayer.isReady(),
        shaderErrors: layer?.shaderControlState?.parseErrors?.value ?? [],
        shaderControls,
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
      const neuroglancerLayout = this.viewer.layout.toJSON();
      if (layout !== "channels-row" && layout !== "channels-column") {
        layout = neuroglancerLayout;
        this.currentLayout = layout;
      }
    } catch {
      // State changes are emitted during layout replacement. Keep the last stable value.
    }
    const viewState = this.getViewState();
    return {
      phase: this.presetName?.startsWith("numpy-")
        ? "Direct-JS multi-NumPy replacement milestone"
        : "Direct-JS Phase A",
      datasourcePreset: this.presetName ?? "public",
      source: this.source ?? PUBLIC_SOURCE,
      dataset: SOURCE_PRESETS[this.presetName]?.dataset ?? null,
      directMount: true,
      iframeCount: this.target.querySelectorAll("iframe").length,
      zAxisIndex: this.getZAxisIndex(),
      z: this.getZ(),
      layout,
      showScaleBar: this.viewer.showScaleBar.value,
      showAxisLines: this.viewer.showAxisLines.value,
      coordinateNames: [...this.viewer.coordinateSpace.value.names],
      position: [...this.viewer.position.value],
      xyBounds: viewState.xyBounds,
      xyPhysicalBounds: viewState.xyPhysicalBounds,
      physicalPosition: viewState.physicalPosition,
      relativeDisplayScales: [...this.viewer.relativeDisplayScales.value.factors],
      channels: this.getChannels(),
      layers: this.getLayerDiagnostics(),
      chunkWorkerError: this.workerError,
      limitations: [
        "The native per-panel related-layout buttons have no granular supported visibility flag at this pinned revision.",
        "The public preset uses an upstream-supported public datasource.",
        "The NumPy preset uses upstream's Python datasource protocol through a local same-origin proxy.",
        "Synthetic NumPy datasets are replaced as complete viewer states; rendered-pixel completion has no supported ready event.",
        "Selecting rr30a may wait while AcqStore downloads and caches the sample locally.",
        "The demo server lazily creates volumes but retains selected volumes for the process lifetime.",
        "Native scale bars and the coordinate widget expose names and units; the pinned slice canvas has no supported conventional ticked-axis-label API.",
        "XY bounds are derived from the pinned slice-panel projection API inside the adapter's unstable boundary."
      ]
    };
  }

  dispose() { this.subscribers.clear(); this.viewer.dispose(); }
}
