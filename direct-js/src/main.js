import "./style.css";
import { NgImageViewer } from "./NgImageViewer.js";

const diagnostics = document.querySelector("#diagnostics");
const status = document.querySelector("#status");
const render = (value) => { diagnostics.textContent = JSON.stringify(value, null, 2); status.textContent = "Mounted directly"; };
const adapter = new NgImageViewer(document.querySelector("#ng-viewer"), render);
adapter.setSource();
render(adapter.getDiagnostics());

document.querySelector("#scale-bar").addEventListener("change", (e) => adapter.setScaleBar(e.target.checked));
document.querySelector("#axis-lines").addEventListener("change", (e) => adapter.setAxisLines(e.target.checked));
document.querySelector("#layout").addEventListener("change", (e) => adapter.setLayout(e.target.value));
document.querySelector("#reset").addEventListener("click", () => adapter.setSource());
window.addEventListener("beforeunload", () => adapter.dispose());
