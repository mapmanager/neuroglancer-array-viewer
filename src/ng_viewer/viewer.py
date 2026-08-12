"""Public Python application wrapper for the direct Neuroglancer viewer."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import neuroglancer
import numpy as np
from neuroglancer.json_utils import json_encoder_default

from .acqimage import NgVolumeData, acquisition_to_ng
from .config import NgConfig
from .contrast import volume_channel_contrast
from .models import ViewState
from .transport import ViewStateDispatcher


@dataclass
class _Dataset:
    key: str
    name: str
    loader: Callable[[], NgVolumeData]
    volume: neuroglancer.LocalVolume | None = None
    metadata: dict[str, object] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class NgArrayViewer:
    """Own datasets, transport lifecycle, configuration, and callbacks."""

    def __init__(
        self,
        config: NgConfig = NgConfig(),
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        frontend_url: str | None = None,
    ) -> None:
        """Create a stopped viewer application.

        Args:
            config: Initial browser presentation configuration.
            host: Transport bind address.
            port: Transport port, or zero for an available port.
            frontend_url: Optional development-client URL. By default this
                wrapper serves its packaged production frontend.
        """
        self.config = config
        self.host = host
        self.port = port
        self.frontend_url = frontend_url
        self._datasets: dict[str, _Dataset] = {}
        self._selected: str | None = None
        self._revision = 0
        self._dispatcher = ViewStateDispatcher()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def viewer_url(self) -> str:
        """Return the frontend URL suitable for an iframe or web component."""
        return self.frontend_url or f"{self.transport_url}/"

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
        """Register a NumPy array without requiring AcqStore.

        Args:
            key: Unique browser-safe dataset identifier.
            array: uint16 pixels with axes described by ``axes``.
            axes: Unique C/Z/Y/X axis names; Y and X are required.
            axis_spacing: Optional physical step size by source axis.
            axis_units: Optional physical unit by source axis.
            name: Optional display name.

        Raises:
            TypeError: If pixels are not uint16.
            ValueError: If axes are invalid or unsupported.
        """
        source = np.asarray(array)
        source_axes = tuple(axis.upper() for axis in axes)
        if source.dtype != np.uint16:
            raise TypeError(f"Expected uint16 pixels; got {source.dtype}")
        if len(source_axes) != source.ndim or len(source_axes) != len(set(source_axes)):
            raise ValueError("Axes must be unique and match the array rank")
        if not {"Y", "X"}.issubset(source_axes) or set(source_axes) - {"C", "Z", "Y", "X"}:
            raise ValueError(f"Expected C/Z/Y/X axes containing Y and X; got {source_axes!r}")
        present = tuple(axis for axis in ("C", "Z", "Y", "X") if axis in source_axes)
        czyx = source.transpose(tuple(source_axes.index(axis) for axis in present))
        if "C" not in source_axes:
            czyx = czyx[np.newaxis, ...]
        if "Z" not in source_axes:
            czyx = czyx[:, np.newaxis, ...]
        data_cxyz = np.ascontiguousarray(np.flip(czyx.swapaxes(-2, -1), axis=-2).transpose(0, 3, 2, 1))
        spacing = axis_spacing or {}
        units = axis_units or {}
        volume_data = NgVolumeData(
            data_cxyz=data_cxyz,
            scales=(1.0, float(spacing.get("Y", 1)), float(spacing.get("X", 1)), float(spacing.get("Z", 1))),
            units=("", str(units.get("Y", "")), str(units.get("X", "")), str(units.get("Z", ""))),
            source_axes=source_axes,
            source_shape=tuple(source.shape),
        )
        self.register_volume_data(key, lambda: volume_data, name=name)

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

    def wait(self) -> None:
        """Block until Ctrl+C, then stop cleanly.

        Raises:
            RuntimeError: If the viewer has not been started.
        """
        if self._server is None:
            raise RuntimeError("Call start() before wait()")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            self.stop()

    def run(self) -> None:
        """Start, print the viewer URL, and block until Ctrl+C."""
        self.start()
        print(f"Neuroglancer viewer: {self.viewer_url}")
        self.wait()

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
                    request_path = urlparse(self.path).path
                    if request_path == "/":
                        return self._static("index.html")
                    if request_path.startswith("/assets/"):
                        return self._static(request_path.removeprefix("/"))
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

            def _static(self, relative_path: str) -> None:
                """Serve one packaged frontend asset."""
                if ".." in relative_path.split("/"):
                    self.send_error(HTTPStatus.BAD_REQUEST); return
                resource = files("ng_viewer").joinpath("static", *relative_path.split("/"))
                if not resource.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND); return
                payload = resource.read_bytes()
                content_type = mimetypes.guess_type(relative_path)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers(); self.wfile.write(payload)

            def log_message(self, *_: object) -> None:
                return

        return Handler
