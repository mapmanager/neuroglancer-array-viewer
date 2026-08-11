/** @file Demo-page composition around the public NgImageViewer adapter. */

import "./style.css";
import { NgImageViewer } from "./NgImageViewer.js";

const $ = (selector) => document.querySelector(selector);
const diagnostics = $("#diagnostics");
const status = $("#status");
let editingZ = false;
let lastDiagnostics = "";
let channelSignature = "";

function renderChannelControls(channels) {
  const signature = JSON.stringify(
    channels.map(({index, name, domain, autoContrast}) => ({
      index, name, domain, autoContrast,
    })),
  );
  if (signature !== channelSignature) {
    channelSignature = signature;
    $("#channel-controls").replaceChildren(...channels.map((channel) => {
      const row = document.createElement("div");
      row.className = "channel-row";
      row.dataset.channel = String(channel.index);
      row.innerHTML = `
      <strong>${channel.name}</strong>
      <input class="channel-color" type="color" value="${channel.color}" aria-label="${channel.name} color" />
      <div class="channel-range" style="--low:${100 * (channel.contrast[0] - channel.domain[0]) / (channel.domain[1] - channel.domain[0])}%; --high:${100 * (channel.contrast[1] - channel.domain[0]) / (channel.domain[1] - channel.domain[0])}%">
        <input class="channel-low" type="range" min="${channel.domain[0]}" max="${channel.domain[1]}" value="${channel.contrast[0]}" step="1" aria-label="${channel.name} contrast minimum" />
        <input class="channel-high" type="range" min="${channel.domain[0]}" max="${channel.domain[1]}" value="${channel.contrast[1]}" step="1" aria-label="${channel.name} contrast maximum" />
      </div>
      <input class="channel-low-number" type="number" min="${channel.domain[0]}" max="${channel.domain[1]}" value="${channel.contrast[0]}" step="1" aria-label="${channel.name} exact contrast minimum" />
      <input class="channel-high-number" type="number" min="${channel.domain[0]}" max="${channel.domain[1]}" value="${channel.contrast[1]}" step="1" aria-label="${channel.name} exact contrast maximum" />
      <button class="channel-auto" type="button" title="Restore ${channel.name} 1–99% contrast">Auto</button>`;
      return row;
    }));
  }
  for (const channel of channels) {
    const row = $(`.channel-row[data-channel="${channel.index}"]`);
    const [low, high] = channel.contrast;
    row.querySelector(".channel-color").value = channel.color;
    row.querySelector(".channel-low").value = String(low);
    row.querySelector(".channel-high").value = String(high);
    row.querySelector(".channel-low-number").value = String(low);
    row.querySelector(".channel-high-number").value = String(high);
    const span = channel.domain[1] - channel.domain[0];
    row.querySelector(".channel-range").style.cssText =
      `--low:${100 * (low - channel.domain[0]) / span}%; --high:${100 * (high - channel.domain[0]) / span}%`;
  }
}

function render(value) {
  const serialized = JSON.stringify(value, null, 2);
  if (serialized !== lastDiagnostics) {
    diagnostics.textContent = serialized;
    lastDiagnostics = serialized;
  }
  status.textContent = `Direct mount · ${value.layout}`;
  if (!editingZ && Number.isFinite(value.z)) $("#z").value = String(Math.floor(value.z));
  $("#scale-bar").checked = value.showScaleBar;
  $("#axis-lines").checked = value.showAxisLines;
  renderChannelControls(value.channels ?? []);
  for (const button of document.querySelectorAll("[data-layout]")) {
    button.classList.toggle("active", button.dataset.layout === value.layout);
  }
}

const adapter = new NgImageViewer($("#ng-viewer"), render);
window.ngArrayDemo = {adapter};
let bridgeTimer;
let pendingViewState;
const unsubscribeBridge = adapter.subscribeViewState((viewState) => {
  pendingViewState = viewState;
  if (bridgeTimer !== undefined) return;
  bridgeTimer = window.setTimeout(async () => {
    bridgeTimer = undefined;
    const payload = pendingViewState;
    try {
      await fetch("/api/view-state", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
    } catch {
      // Public-only Phase A can run without the optional Python server.
    }
  }, 100);
});
await adapter.setSource("public");
render(adapter.getDiagnostics());

$("#layout-chrome").addEventListener("click", (event) => {
  const layout = event.target.dataset.layout;
  if (layout) adapter.setLayout(layout);
});
$("#placement").addEventListener("change", (event) => {
  $("#viewer-stage").className = `viewer-stage placement-${event.target.value}`;
});
$("#datasource").addEventListener("change", async (event) => {
  status.textContent = "Loading dataset…";
  try {
    await adapter.setSource(event.target.value);
  } catch (error) {
    status.textContent = `Dataset failed: ${error.message}`;
    console.error(error);
  }
});
$("#z").addEventListener("focus", () => { editingZ = true; });
$("#z").addEventListener("blur", () => { editingZ = false; });
$("#z").addEventListener("input", (event) => adapter.setZ(event.target.value));
$("#scale-bar").addEventListener("change", (event) => adapter.setScaleBar(event.target.checked));
$("#axis-lines").addEventListener("change", (event) => adapter.setAxisLines(event.target.checked));
$("#reset").addEventListener("click", async () => {
  status.textContent = "Resetting dataset…";
  try {
    await adapter.setSource($("#datasource").value);
  } catch (error) {
    status.textContent = "Dataset failed: " + error.message;
    console.error(error);
  }
});
$("#channel-toggle").addEventListener("click", (event) => {
  const collapsed = $("#channel-chrome").classList.toggle("collapsed");
  event.currentTarget.setAttribute("aria-expanded", String(!collapsed));
});
$("#channel-controls").addEventListener("input", (event) => {
  const row = event.target.closest(".channel-row");
  if (!row) return;
  const index = Number(row.dataset.channel);
  if (event.target.matches(".channel-color")) {
    adapter.setChannelColor(index, event.target.value);
    return;
  }
  const lowRange = row.querySelector(".channel-low");
  const highRange = row.querySelector(".channel-high");
  const lowNumber = row.querySelector(".channel-low-number");
  const highNumber = row.querySelector(".channel-high-number");
  if (event.target === lowNumber) lowRange.value = lowNumber.value;
  if (event.target === highNumber) highRange.value = highNumber.value;
  let low = Number(lowRange.value);
  let high = Number(highRange.value);
  if (low >= high) {
    if (event.target === lowRange || event.target === lowNumber) low = high - 1;
    else high = low + 1;
  }
  adapter.setChannelWindow(index, low, high);
  lowRange.value = String(low);
  highRange.value = String(high);
  lowNumber.value = String(low);
  highNumber.value = String(high);
  const rangeLow = Number(lowRange.min);
  const rangeHigh = Number(lowRange.max);
  row.querySelector(".channel-range").style.cssText = `--low:${100 * (low - rangeLow) / (rangeHigh - rangeLow)}%; --high:${100 * (high - rangeLow) / (rangeHigh - rangeLow)}%`;
});
$("#channel-controls").addEventListener("click", (event) => {
  const button = event.target.closest(".channel-auto");
  if (!button) return;
  const row = button.closest(".channel-row");
  adapter.resetChannelContrast(Number(row.dataset.channel));
});
window.addEventListener("beforeunload", () => {
  unsubscribeBridge();
  if (bridgeTimer !== undefined) clearTimeout(bridgeTimer);
  adapter.dispose();
});
