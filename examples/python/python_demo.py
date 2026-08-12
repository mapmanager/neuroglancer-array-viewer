"""
Python demo for the ng-array-viewer.

AcqStore is installed from the editable sibling at ../acqstore by the default
development dependency group. Python >= 3.12 is required for this example.
From the repository root:

    uv sync
    uv run python examples/python_demo.py
"""

import webbrowser

from acqstore.acq_image import AcqImage
from acqstore.sample_data import ensure_sample_file

from ng_viewer import NgArrayViewer, NgConfig, ViewState


path = ensure_sample_file("rr30a-two-channel")
acq = AcqImage(str(path))

viewer = NgArrayViewer(config=NgConfig())
viewer.register_acqimage(
    "rr30a",
    acq,
    name="RR30a two-channel",
)


def on_view_state(state: ViewState) -> None:
    print(state.layout, state.x, state.y, state.z, state.z_unit)


unsubscribe = viewer.subscribe_view_state(on_view_state)
viewer.start()

print("Viewer:", viewer.viewer_url)

# Optional: open the system browser automatically.
webbrowser.open(viewer.viewer_url)

# Later, after registering another dataset:
# viewer.select_dataset("another-dataset")

try:
    viewer.wait()
finally:
    unsubscribe()
    viewer.stop()
