"""Public Python application wrapper for the direct Neuroglancer viewer."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import neuroglancer
import numpy as np
from neuroglancer.json_utils import json_encoder_default

from acqimage_ng import NgVolumeData, acquisition_to_ng
from contrast import volume_channel_contrast


class ChromePlacement(StrEnum):
    """Supported positions for the project-owned layout chrome."""

    OVERLAY_TOP = "overlay_top"
    OVERLAY_LEFT = "overlay_left"
    OVERLAY_BOTTOM = "overlay_bottom"
    OUTSIDE = "outside"


class ViewerLayout(StrEnum):
    """Layouts emitted by the direct viewer's public state contract."""

    XY = "xy"
    CHANNELS_ROW = "channels-row"
    CHANNELS_COLUMN = "channels-column"
    XY_3D = "xy-3d"
    FOUR_PANEL_ALT = "4panel-alt"
    THREE_D = "3d"


@dataclass(frozen=True)
class NgConfig:
    """Initial presentation and navigation configuration.

    Attributes:
        chrome_placement: Position of the project-owned layout toolbar.
        show_options_control: Whether the Options button is available.
        show_z_control: Whether multi-plane datasets show the Z rail.
        show_scale_bar: Initial native scale-bar visibility.
        show_axis_lines: Initial native axis-line visibility.
        show_display_dimensions: Initial native X/Y/Z widget visibility.
        show_native_layout_buttons: Initial native layout-button visibility.
        show_channels_control: Initial project-owned Channels visibility.
        show_layout_control: Initial project-owned Layout visibility.
    """

    chrome_placement: ChromePlacement = ChromePlacement.OVERLAY_TOP
    show_options_control: bool = True
    show_z_control: bool = True
    show_scale_bar: bool = False
    show_axis_lines: bool = False
    show_display_dimensions: bool = False
    show_native_layout_buttons: bool = False
    show_channels_control: bool = False
    show_layout_control: bool = False

    def to_json(self) -> dict[str, object]:
        """Return the browser-facing camel-case configuration.

        Returns:
            JSON-compatible configuration dictionary.
        """
        return {
            "chromePlacement": self.chrome_placement.value,
            "showOptionsControl": self.show_options_control,
            "showZControl": self.show_z_control,
            "showScaleBar": self.show_scale_bar,
            "showAxisLines": self.show_axis_lines,
            "showDisplayDimensions": self.show_display_dimensions,
            "showNativeLayoutButtons": self.show_native_layout_buttons,
            "showChannelsControl": self.show_channels_control,
            "showLayoutControl": self.show_layout_control,
        }


@dataclass(frozen=True)
class AxisRange:
    """One calibrated visible-axis interval."""

    minimum: float
    maximum: float
    unit: str


@dataclass(frozen=True)
class ViewState:
    """Typed semantic state emitted when the browser view changes."""

    dataset_id: str
    layout: ViewerLayout
    x: AxisRange | None
    y: AxisRange | None
    z: float | None
    z_unit: str | None
    raw: dict[str, object]

    @classmethod
    def from_json(cls, value: dict[str, object]) -> ViewState:
        """Parse one browser snapshot.

        Args:
            value: Browser JSON view-state object.

        Returns:
            Validated typed state retaining the original JSON.

        Raises:
            ValueError: If required fields or a known layout are missing.
        """
        dataset_id = value.get("datasetId")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("View state requires a non-empty datasetId")
        try:
            layout = ViewerLayout(str(value["layout"]))
        except (KeyError, ValueError) as error:
            raise ValueError(f"Unsupported viewer layout: {value.get('layout')!r}") from error
        bounds = value.get("xyPhysicalBounds")
        panel = bounds[0] if isinstance(bounds, list) and bounds else None

        def axis(name: str) -> AxisRange | None:
            item = panel.get(name) if isinstance(panel, dict) else None
            if not isinstance(item, dict):
                return None
            return AxisRange(float(item["min"]), float(item["max"]), str(item.get("unit", "")))

        position = value.get("physicalPosition")
        z_value = position.get("z") if isinstance(position, dict) else None
        z = float(z_value["value"]) if isinstance(z_value, dict) and "value" in z_value else None
        z_unit = str(z_value.get("unit", "")) if isinstance(z_value, dict) else None
        return cls(dataset_id, layout, axis("x"), axis("y"), z, z_unit, dict(value))


@dataclass
class _Dataset:
    key: str
    name: str
    loader: Callable[[], NgVolumeData]
    volume: neuroglancer.LocalVolume | None = None
    metadata: dict[str, object] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class _ViewStateDispatcher:
    """Dispatch newest typed state without blocking an HTTP request."""

    def __init__(self) -> None:
        self.callbacks: set[Callable[[ViewState], None]] = set()
        self.lock = threading.Lock()
        self.pending: queue.Queue[ViewState | None] = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def subscribe(self, callback: Callable[[ViewState], None]) -> Callable[[], None]:
        """Register a callback and return its unsubscriber."""
        if not callable(callback):
            raise TypeError("View-state callback must be callable")
        with self.lock:
            self.callbacks.add(callback)
        return lambda: self._discard(callback)

    def _discard(self, callback: Callable[[ViewState], None]) -> None:
        with self.lock:
            self.callbacks.discard(callback)

    def publish(self, state: ViewState) -> None:
        try:
            self.pending.put_nowait(state)
        except queue.Full:
            self.pending.get_nowait()
            self.pending.put_nowait(state)

    def close(self) -> None:
        try:
            self.pending.put_nowait(None)
        except queue.Full:
            self.pending.get_nowait()
            self.pending.put_nowait(None)
        self.thread.join(timeout=1)

    def _run(self) -> None:
        while (state := self.pending.get()) is not None:
            with self.lock:
                callbacks = tuple(self.callbacks)
            for callback in callbacks:
                callback(state)


class NgArrayViewer:
    """Own datasets, transport lifecycle, configuration, and callbacks."""

    def __init__(
        self,
        config: NgConfig = NgConfig(),
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        frontend_url: str = "http://127.0.0.1:5173/",
    ) -> None:
        """Create a stopped viewer application.

        Args:
            config: Initial browser presentation configuration.
            host: Transport bind address.
            port: Transport port, or zero for an available port.
            frontend_url: URL of the direct-JS client embedded by a host app.
        """
        self.config = config
        self.host = host
        self.port = port
        self.frontend_url = frontend_url
        self._datasets: dict[str, _Dataset] = {}
        self._selected: str | None = None
        self._revision = 0
        self._dispatcher = _ViewStateDispatcher()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def viewer_url(self) -> str:
        """Return the frontend URL suitable for an iframe or web component."""
        return self.frontend_url

    @property
    def transport_url(self) -> str:
        """Return the running Python transport URL.

        Raises:
            RuntimeError: If the application is not running.
        """
        if self._server is None:
            raise RuntimeError("NgArrayViewer is not running")
        return f"http://{self.host}:{self._server.server_port}"

    def register_acqimage(self, key: str, acquisition: Any, *, name: str | None = None) -> None:
        """Register an AcqImage for lazy complete-volume conversion.

        Args:
            key: Unique browser-safe dataset identifier.
            acquisition: AcqStore AcqImage instance.
            name: Optional display name.

        Raises:
            ValueError: If the key is invalid or already registered.
        """
        self._register(key, name or key, lambda: acquisition_to_ng(acquisition))

    def register_numpy(
        self,
        key: str,
        array: np.ndarray,
        *,
        axes: tuple[str, ...],
        axis_spacing: dict[str, float] | None = None,
        axis_units: dict[str, str] | None = None,
        name: str | None = None,
    ) -> None:
        """Register a NumPy array using AcqImage's public metadata contract."""
        from acqstore.acq_image import AcqImage

        acquisition = AcqImage.from_array(
            array,
            axes=axes,
            source_id=key,
            axis_spacing=axis_spacing,
            axis_units=axis_units,
        )
        self.register_acqimage(key, acquisition, name=name)

    def register_volume_data(
        self,
        key: str,
        loader: Callable[[], NgVolumeData],
        *,
        name: str | None = None,
    ) -> None:
        """Register a lazy display-oriented volume provider.

        This lower-level entry point is useful for applications that already
        own their AcqImage loading policy. Most clients should prefer
        :meth:`register_acqimage` or :meth:`register_numpy`.

        Args:
            key: Unique browser-safe dataset identifier.
            loader: Callable returning one complete ``NgVolumeData``.
            name: Optional display name.
        """
        if not callable(loader):
            raise TypeError("Volume-data loader must be callable")
        self._register(key, name or key, loader)

    def _register(self, key: str, name: str, loader: Callable[[], NgVolumeData]) -> None:
        if not key or not all(character.isalnum() or character in "-_" for character in key):
            raise ValueError("Dataset key must contain only letters, digits, '-' or '_'")
        if key in self._datasets:
            raise ValueError(f"Dataset already registered: {key}")
        self._datasets[key] = _Dataset(key, name, loader, lock=threading.Lock())
        if self._selected is None:
            self.select_dataset(key)

    def select_dataset(self, key: str) -> None:
        """Select a registered dataset for startup or live replacement."""
        if key not in self._datasets:
            raise KeyError(f"Unknown dataset: {key}")
        self._selected = key
        self._revision += 1

    def subscribe_view_state(self, callback: Callable[[ViewState], None]) -> Callable[[], None]:
        """Subscribe to non-blocking typed browser-state updates."""
        return self._dispatcher.subscribe(callback)

    def start(self) -> NgArrayViewer:
        """Start the local transport server and return this wrapper."""
        if self._server is not None:
            return self
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler_factory())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop transport and callback resources; repeated calls are safe."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        self._dispatcher.close()

    def __enter__(self) -> NgArrayViewer:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    def _materialize(self, key: str) -> _Dataset:
        dataset = self._datasets[key]
        with dataset.lock:
            if dataset.volume is None:
                data = dataset.loader()
                ranges, automatic = volume_channel_contrast(data.data_cxyz)
                dataset.volume = neuroglancer.LocalVolume(
                    data=data.data_cxyz,
                    dimensions=neuroglancer.CoordinateSpace(
                        names=["c^", "x", "y", "z"], units=list(data.units), scales=list(data.scales)
                    ),
                    volume_type="image", encoding="npz", downsampling=None,
                )
                dataset.metadata = {
                    "key": key, "name": dataset.name, "dtype": str(data.data_cxyz.dtype),
                    "shapeCXYZ": list(data.data_cxyz.shape), "channelRanges": ranges,
                    "channelAutoRanges": automatic, "scales": list(data.scales), "units": list(data.units),
                }
        return dataset

    def _application_state(self) -> dict[str, object]:
        return {
            "revision": self._revision,
            "selectedDataset": self._selected,
            "config": self.config.to_json(),
            "datasets": [{"key": item.key, "name": item.name} for item in self._datasets.values()],
        }

    def _handler_factory(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class Handler(BaseHTTPRequestHandler):
            def end_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parts = urlparse(self.path).path.strip("/").split("/")
                try:
                    if parts == ["api", "app-state"]:
                        return self._json(application._application_state())
                    if len(parts) == 3 and parts[:2] == ["api", "dataset"]:
                        dataset = application._materialize(parts[2])
                        return self._json(dataset.metadata)
                    if len(parts) == 3 and parts[:2] == ["neuroglancer", "info"]:
                        dataset = application._materialize(parts[2])
                        return self._json(dataset.volume.info())
                    if len(parts) == 6 and parts[:2] in (["neuroglancer", "raw"], ["neuroglancer", "npz"]):
                        _, data_format, key, scale_key, start_text, end_text = parts
                        dataset = application._materialize(key)
                        payload, content_type = dataset.volume.get_encoded_subvolume(
                            data_format=data_format,
                            start=np.array(start_text.split(","), dtype=np.int64),
                            end=np.array(end_text.split(","), dtype=np.int64), scale_key=scale_key,
                        )
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers(); self.wfile.write(payload); return
                except KeyError:
                    self.send_error(HTTPStatus.NOT_FOUND); return
                except Exception as error:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(error)); return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:  # noqa: N802
                if urlparse(self.path).path != "/api/view-state":
                    self.send_error(HTTPStatus.NOT_FOUND); return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 1_000_000:
                        raise ValueError("Expected a non-empty view-state JSON payload")
                    value = json.loads(self.rfile.read(length))
                    application._dispatcher.publish(ViewState.from_json(value))
                    self._json({"ok": True})
                except (ValueError, TypeError, json.JSONDecodeError) as error:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(error))

            def _json(self, value: object) -> None:
                payload = json.dumps(value, default=json_encoder_default, separators=(",", ":")).encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers(); self.wfile.write(payload)

            def log_message(self, *_: object) -> None:
                return

        return Handler
