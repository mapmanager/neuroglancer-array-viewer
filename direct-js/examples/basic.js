/** @file Minimal direct-JavaScript use of the project adapter. */

import {NgImageViewer, registerPythonDataset} from "../src/NgImageViewer.js";

const response = await fetch("/api/app-state");
if (!response.ok) throw new Error(`Application state failed: ${response.status}`);
const application = await response.json();
for (const dataset of application.datasets) registerPythonDataset(dataset);

const viewer = new NgImageViewer(document.querySelector("#viewer"));
await viewer.setSource(`python-${application.selectedDataset}`);
viewer.setScaleBar(application.config.showScaleBar);
viewer.setAxisLines(application.config.showAxisLines);
viewer.setDisplayDimensions(application.config.showDisplayDimensions);
viewer.setNativeLayoutButtons(application.config.showNativeLayoutButtons);

const unsubscribe = viewer.subscribeViewState((state) => console.log(state));
window.addEventListener("beforeunload", () => {
  unsubscribe();
  viewer.dispose();
});
