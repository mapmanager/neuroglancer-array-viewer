const $ = (selector) => document.querySelector(selector);
const status = $("#status");
const diagnostics = $("#diagnostics");
let sending = false;
let draggingZ = false;
let pending = {};
let lastDiagnostics = "";

function selectionIsInside(element) {
  const selection = window.getSelection();
  return selection && !selection.isCollapsed && element.contains(selection.anchorNode);
}

function render(state) {
  const serialized = JSON.stringify(state, null, 2);
  if (serialized !== lastDiagnostics && !selectionIsInside(diagnostics)) {
    diagnostics.textContent = serialized;
    lastDiagnostics = serialized;
  }
  if (!draggingZ && Number.isFinite(state.actual?.z)) {
    // NG may report voxel-center coordinates such as 35.5; slider values are slice indices.
    const z = Math.max(0, Math.min(69, Math.floor(state.actual.z)));
    $("#z").value = String(z);
    $("#z-value").value = String(z);
  }
  if (typeof state.actual?.showScaleBar === "boolean") {
    $("#scale-bar").checked = state.actual.showScaleBar;
  }
  if (typeof state.actual?.showAxisLines === "boolean") {
    $("#axis-lines").checked = state.actual.showAxisLines;
  }
  if (state.requested?.mode) {
    const mode = document.querySelector(`input[name="mode"][value="${state.requested.mode}"]`);
    if (mode) mode.checked = true;
  }
  status.textContent = "Connected";
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

const bootstrap = await fetch("/api/bootstrap").then((r) => r.json());
$("#viewer").src = bootstrap.viewerUrl;
render(bootstrap);
$("#z").addEventListener("pointerdown", () => { draggingZ = true; });
window.addEventListener("pointerup", () => { draggingZ = false; });
$("#z").addEventListener("input", () => {
  $("#z-value").value = $("#z").value;
  send({z: Number($("#z").value)});
});
for (const element of document.querySelectorAll('input[name="mode"]')) {
  element.addEventListener("change", () => send({mode: element.value}));
}
$("#scale-bar").addEventListener("change", () => send({scale_bar: $("#scale-bar").checked}));
$("#axis-lines").addEventListener("change", () => send({axis_lines: $("#axis-lines").checked}));
for (const [selector, key] of [["#c0-min", "c0_min"], ["#c0-max", "c0_max"], ["#c1-min", "c1_min"], ["#c1-max", "c1_max"]]) {
  $(selector).addEventListener("change", () => send({[key]: Number($(selector).value)}));
}
setInterval(async () => {
  if (sending) return;
  try { render(await fetch("/api/state", {cache: "no-store"}).then((r) => r.json())); }
  catch (error) { status.textContent = "Disconnected"; }
}, 1000);
