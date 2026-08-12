"""Embed an AcqImage-backed Neuroglancer viewer in a NiceGUI page.

NiceGUI is intentionally not a project dependency. From the repository root,
install the normal development environment and run this example with a
temporary NiceGUI dependency:

    uv sync
    uv run --with nicegui python examples/demo_nicegui.py

Open http://127.0.0.1:8080 if NiceGUI does not open it automatically. Stop the
application with Ctrl+C. NgArrayViewer serves its packaged frontend, NumPy
chunks, configuration, and callbacks from a separate local port; NiceGUI only
embeds that URL and remains free to compose other application widgets around
it.
"""

from __future__ import annotations

from acqstore.acq_image import AcqImage
from acqstore.sample_data import ensure_sample_file
from nicegui import app, html, ui

from ng_viewer import NgArrayViewer, NgConfig, ViewState


def report_view_state(state: ViewState) -> None:
    """Print calibrated view changes received from Neuroglancer.

    Args:
        state: Latest typed viewer-state snapshot.
    """
    print(
        f"dataset={state.dataset_id} layout={state.layout.value} "
        f"x={state.x} y={state.y} z={state.z} {state.z_unit or ''}"
    )


sample_path = ensure_sample_file("rr30a-two-channel")
acquisition = AcqImage(str(sample_path))

viewer = NgArrayViewer(config=NgConfig())
viewer.register_acqimage("rr30a", acquisition, name="RR30a two-channel")
unsubscribe = viewer.subscribe_view_state(report_view_state)
viewer.start()


@ui.page("/")
def index() -> None:
    """Compose the NiceGUI host page around the standalone viewer URL."""
    ui.label("NiceGUI · Neuroglancer Array Viewer").classes(
        "text-lg font-medium px-3 pt-2"
    )
    html.iframe(
        src=viewer.viewer_url,
        title="RR30a Neuroglancer viewer",
    ).classes("w-full").style("height: calc(100vh - 56px); border: 0")


def shutdown_viewer() -> None:
    """Release callback and transport resources with the NiceGUI app."""
    unsubscribe()
    viewer.stop()


app.on_shutdown(shutdown_viewer)

if __name__ in {"__main__", "__mp_main__"}:
    try:
        ui.run(title="NiceGUI Neuroglancer Demo", reload=False)
    except KeyboardInterrupt:
        # Some event-loop implementations re-raise Ctrl+C after NiceGUI has
        # already run its shutdown hooks. Keep this example's exit concise.
        pass
