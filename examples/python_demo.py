"""
Python demo for the ng-array-viewer.

Requires the optional AcqStore extra (editable sibling at ../acqstore).
Python >= 3.12 for acqstore. From the ng-array-demo root:

    uv sync --extra acqstore-demo
    uv run --extra acqstore-demo python examples/python_demo.py

``[project.optional-dependencies]``: acqstore-demo = ["acqstore; python_version >= '3.12'"]
``[tool.uv.sources]``: acqstore = { path = "../acqstore", editable = true }
"""

from acqstore.acq_image import AcqImage
from acqstore.sample_data import ensure_sample_file

from ng_array_viewer import NgArrayViewer, NgConfig, ViewState


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

print("Transport:", viewer.transport_url)
print("Embed this frontend URL:", viewer.viewer_url)

# Later, after registering another dataset:
# viewer.select_dataset("another-dataset")

# On application shutdown:
unsubscribe()
viewer.stop()