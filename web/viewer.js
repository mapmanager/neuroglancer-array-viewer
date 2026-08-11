const $ = (selector) => document.querySelector(selector);
const status = $("#status");
const diagnostics = $("#diagnostics");
let sending = false;
let draggingZ = false;
let pending = {};
let lastDiagnostics = "";
let renderedDataset = "";

function selectionIsInside(element) {
  const selection = window.getSelection();
  return selection && !selection.isCollapsed && element.contains(selection.anchorNode);
}

function rebuildDatasetControls(state) {
  const channelCount = state.data.naturalShapeZCYX[1];
  const identity = `${state.data.dataset}:${channelCount}`;
  if (identity === renderedDataset) return;
  renderedDataset = identity;

  $("#display-modes").innerHTML = [
    ...Array.from({length: channelCount}, (_, i) =>
      `<label><input type="radio" name="mode" value="c${i}" /> C${i}</label>`),
    `<label><input type="radio" name="mode" value="composite" /> Composite</label>`,
  ].join("");

  $("#channel-controls").innerHTML = Array.from({length: channelCount}, (_, i) => `
    <span class="channel-control">
      <label>C${i} color <input data-channel="${i}" data-field="color" type="color" /></label>
      <label>C${i} min <input data-channel="${i}" data-field="min" type="number" min="0" max="65535" /></label>
      <label>C${i} max <input data-channel="${i}" data-field="max" type="number" min="0" max="65535" /></label>
    </span>`).join("");
}

function render(state) {
  rebuildDatasetControls(state);
  const serialized = JSON.stringify(state, null, 2);
  if (serialized !== lastDiagnostics && !selectionIsInside(diagnostics)) {
    diagnostics.textContent = serialized;
    lastDiagnostics = serialized;
  }

  const zMax = state.data.naturalShapeZCYX[0] - 1;
  $("#z").max = String(zMax);
  if (!draggingZ && Number.isFinite(state.actual?.z)) {
    const z = Math.max(0, Math.min(zMax, Math.floor(state.actual.z)));
    $("#z").value = String(z);
    $("#z-value").value = String(z);
  }
  $("#dataset").value = state.data.dataset;
  if (typeof state.actual?.showScaleBar === "boolean") $("#scale-bar").checked = state.actual.showScaleBar;
  if (typeof state.actual?.showAxisLines === "boolean") $("#axis-lines").checked = state.actual.showAxisLines;

  const mode = document.querySelector(`input[name="mode"][value="${state.requested.mode}"]`);
  if (mode) mode.checked = true;
  for (const input of document.querySelectorAll("#channel-controls input")) {
    if (document.activeElement === input) continue;
    const channel = Number(input.dataset.channel);
    const field = input.dataset.field;
    if (field === "color") input.value = state.requested.channel_colors[channel];
    if (field === "min") input.value = String(state.requested.channel_mins[channel]);
    if (field === "max") input.value = String(state.requested.channel_maxs[channel]);
  }
  status.textContent = `Connected · Dataset ${state.data.dataset.toUpperCase()}`;
}

async function send(change) {
  Object.assign(pending, change);
  if (sending) return;
  sending = true;
  while (Object.keys(pending).length) {
    const outgoing = pending;
    pending = {};
    status.textContent = "Updating…";
    try {
      const response = await fetch("/api/state", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(outgoing),
      });
      if (!response.ok) throw new Error(await response.text());
      render(await response.json());
    } catch (error) {
      status.textContent = "Update failed";
      diagnostics.textContent = String(error);
      lastDiagnostics = diagnostics.textContent;
    }
  }
  sending = false;
}

const bootstrap = await fetch("/api/bootstrap").then((response) => response.json());
for (const dataset of bootstrap.datasets) {
  const option = document.createElement("option");
  option.value = dataset.key;
  option.textContent = dataset.label;
  $("#dataset").append(option);
}
$("#viewer").src = bootstrap.viewerUrl;
render(bootstrap);

$("#dataset").addEventListener("change", () => send({dataset: $("#dataset").value}));
$("#z").addEventListener("pointerdown", () => { draggingZ = true; });
window.addEventListener("pointerup", () => { draggingZ = false; });
$("#z").addEventListener("input", () => {
  $("#z-value").value = $("#z").value;
  send({z: Number($("#z").value)});
});
$("#display-modes").addEventListener("change", (event) => {
  if (event.target.name === "mode") send({mode: event.target.value});
});
$("#channel-controls").addEventListener("input", (event) => {
  const input = event.target;
  if (!input.dataset.channel) return;
  const change = {channel: Number(input.dataset.channel)};
  change[input.dataset.field] = input.dataset.field === "color" ? input.value : Number(input.value);
  send(change);
});
$("#scale-bar").addEventListener("change", () => send({scale_bar: $("#scale-bar").checked}));
$("#axis-lines").addEventListener("change", () => send({axis_lines: $("#axis-lines").checked}));

setInterval(async () => {
  if (sending) return;
  try { render(await fetch("/api/state", {cache: "no-store"}).then((response) => response.json())); }
  catch { status.textContent = "Disconnected"; }
}, 1000);
