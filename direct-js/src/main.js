import "./style.css";
import { NgImageViewer } from "./NgImageViewer.js";

const $ = (selector) => document.querySelector(selector);
const diagnostics = $("#diagnostics");
const status = $("#status");
let editingZ = false;
let lastDiagnostics = "";

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
  for (const button of document.querySelectorAll("[data-layout]")) {
    button.classList.toggle("active", button.dataset.layout === value.layout);
  }
}

const adapter = new NgImageViewer($("#ng-viewer"), render);
window.ngArrayDemo = {adapter};
adapter.setSource();
render(adapter.getDiagnostics());

$("#layout-chrome").addEventListener("click", (event) => {
  const layout = event.target.dataset.layout;
  if (layout) adapter.setLayout(layout);
});
$("#placement").addEventListener("change", (event) => {
  $("#viewer-stage").className = `viewer-stage placement-${event.target.value}`;
});
$("#z").addEventListener("focus", () => { editingZ = true; });
$("#z").addEventListener("blur", () => { editingZ = false; });
$("#z").addEventListener("input", (event) => adapter.setZ(event.target.value));
$("#scale-bar").addEventListener("change", (event) => adapter.setScaleBar(event.target.checked));
$("#axis-lines").addEventListener("change", (event) => adapter.setAxisLines(event.target.checked));
$("#reset").addEventListener("click", () => adapter.setSource());
window.addEventListener("beforeunload", () => adapter.dispose());
