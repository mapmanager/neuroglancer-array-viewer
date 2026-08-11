from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import neuroglancer
import numpy as np


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
Z_COUNT, C_COUNT, Y_COUNT, X_COUNT = 70, 2, 1024, 1024
X_UM, Y_UM, Z_UM = 0.25, 0.25, 1.0


def make_data() -> np.ndarray:
    """Return synthetic uint16 data in natural Z,C,Y,X order."""
    yy, xx = np.ogrid[:Y_COUNT, :X_COUNT]
    data = np.empty((Z_COUNT, C_COUNT, Y_COUNT, X_COUNT), dtype=np.uint16)
    for z in range(Z_COUNT):
        cx = 260 + z * 7
        cy = 390 + int(90 * np.sin(z / 8))
        circle = np.maximum(0, 1 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / 180)
        ramp = (xx / (X_COUNT - 1)) * 0.25
        data[z, 0] = np.clip((circle + ramp) * 52000, 0, 65535).astype(np.uint16)

        sx = 690 - z * 5
        sy = 610 + int(70 * np.cos(z / 7))
        outer = (np.abs(xx - sx) < 150) & (np.abs(yy - sy) < 150)
        inner = (np.abs(xx - sx) < 95) & (np.abs(yy - sy) < 95)
        ring = outer & ~inner
        diagonal = ((xx + yy + z * 11) % 190) < 24
        data[z, 1] = np.where(ring, 54000, np.where(diagonal, 15000, 500)).astype(
            np.uint16
        )
    return data


@dataclass
class RequestedState:
    z: int = Z_COUNT // 2
    mode: str = "composite"
    c0_min: int = 0
    c0_max: int = 55000
    c1_min: int = 0
    c1_max: int = 55000
    scale_bar: bool = True
    axis_lines: bool = False


class Demo:
    def __init__(self) -> None:
        self.data_zcyx = make_data()
        # LocalVolume follows the dimension sequence. This transpose is a view, not a copy.
        self.data_cxyz = self.data_zcyx.transpose(1, 3, 2, 0)
        self.viewer = neuroglancer.Viewer()
        self.requested = RequestedState()
        self.requested_lock = threading.Lock()
        self.update_lock = threading.Lock()
        self.last_viewer_change = time.time()
        self._configure_once()
        self.viewer.shared_state.add_changed_callback(self._viewer_changed)

    def _viewer_changed(self) -> None:
        self.last_viewer_change = time.time()

    @staticmethod
    def _dimension_names(state: Any) -> list[str]:
        return [str(name) for name in state.dimensions.names]

    @classmethod
    def _spatial_axis_index(cls, state: Any, name: str) -> int:
        names = cls._dimension_names(state)
        try:
            return names.index(name)
        except ValueError as exc:
            raise RuntimeError(
                f"Viewer position has dimensions {names!r}; expected spatial axis {name!r}"
            ) from exc

    @staticmethod
    def _shader(r: RequestedState) -> str:
        c0 = f"clamp((float(getDataValue(0)) - {r.c0_min}.0) / {max(1, r.c0_max-r.c0_min)}.0, 0.0, 1.0)"
        c1 = f"clamp((float(getDataValue(1)) - {r.c1_min}.0) / {max(1, r.c1_max-r.c1_min)}.0, 0.0, 1.0)"
        if r.mode == "c0":
            rgb = f"vec3(0.0, {c0}, 0.0)"
        elif r.mode == "c1":
            rgb = f"vec3({c1}, 0.0, {c1})"
        else:
            rgb = f"vec3({c1}, {c0}, {c1})"
        return f"void main() {{ emitRGB({rgb}); }}"

    def _configure_once(self) -> None:
        volume_dimensions = neuroglancer.CoordinateSpace(
            names=["c^", "x", "y", "z"],
            units=["", "um", "um", "um"],
            scales=[1, X_UM, Y_UM, Z_UM],
        )
        navigation_dimensions = neuroglancer.CoordinateSpace(
            names=["x", "y", "z"],
            units=["um", "um", "um"],
            scales=[X_UM, Y_UM, Z_UM],
        )
        with self.viewer.txn() as state:
            state.dimensions = navigation_dimensions
            state.layers["synthetic ZCYX"] = neuroglancer.ImageLayer(
                source=neuroglancer.LocalVolume(
                    data=self.data_cxyz,
                    dimensions=volume_dimensions,
                    volume_type="image",
                ),
                shader=self._shader(self.requested),
            )
            state.layout = "xy"
            # c^ is a local image-channel dimension, not a global navigation dimension.
            state.position = [X_COUNT / 2, Y_COUNT / 2, self.requested.z]
            state.show_scale_bar = self.requested.scale_bar
            state.show_axis_lines = self.requested.axis_lines
            state.show_default_annotations = False
        with self.viewer.config_state.txn() as config:
            config.show_ui_controls = False
            config.show_top_bar = False
            config.show_location = False
            config.show_layer_panel = False
            config.show_help_button = False
            config.show_settings_button = False
            config.show_panel_borders = False

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Snapshot requested state, then perform exactly one viewer transaction.

        No helper called inside viewer.txn acquires requested_lock. This structural rule fixes
        the v1 nested non-reentrant-lock deadlock without substituting an RLock.
        """
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object")

        # Serialize HTTP mutations. Build a prospective snapshot without changing the
        # reported requested state; publish it only after the NG transaction succeeds.
        with self.update_lock:
            with self.requested_lock:
                snapshot = RequestedState(**vars(self.requested))
            if "z" in payload:
                snapshot.z = max(0, min(Z_COUNT - 1, int(payload["z"])))
            if "mode" in payload:
                if payload["mode"] not in {"c0", "c1", "composite"}:
                    raise ValueError(f"Invalid display mode: {payload['mode']!r}")
                snapshot.mode = payload["mode"]
            for key in ("c0_min", "c0_max", "c1_min", "c1_max"):
                if key in payload:
                    setattr(snapshot, key, max(0, min(65535, int(payload[key]))))
            if "scale_bar" in payload:
                snapshot.scale_bar = bool(payload["scale_bar"])
            if "axis_lines" in payload:
                snapshot.axis_lines = bool(payload["axis_lines"])

            with self.viewer.txn() as state:
                if "z" in payload:
                    position = list(state.position)
                    position[self._spatial_axis_index(state, "z")] = snapshot.z
                    state.position = position
                if any(
                    key in payload
                    for key in ("mode", "c0_min", "c0_max", "c1_min", "c1_max")
                ):
                    state.layers["synthetic ZCYX"].shader = self._shader(snapshot)
                if "scale_bar" in payload:
                    state.show_scale_bar = snapshot.scale_bar
                if "axis_lines" in payload:
                    state.show_axis_lines = snapshot.axis_lines

            with self.requested_lock:
                self.requested = snapshot
        return self.diagnostics()

    def diagnostics(self) -> dict[str, Any]:
        with self.requested_lock:
            requested = vars(RequestedState(**vars(self.requested)))
        state = self.viewer.state
        position = [float(x) for x in state.position]
        dimension_names = self._dimension_names(state)
        z_index = self._spatial_axis_index(state, "z")
        return {
            "requested": requested,
            "actual": {
                "position": position,
                "dimensionNames": dimension_names,
                "z": position[z_index],
                "layout": state.layout.to_json(),
                "showScaleBar": state.show_scale_bar,
                "showAxisLines": state.show_axis_lines,
                "viewerChangedAt": self.last_viewer_change,
            },
            "data": {
                "naturalShapeZCYX": list(self.data_zcyx.shape),
                "dtype": str(self.data_zcyx.dtype),
                "coordinateNames": ["c^", "x", "y", "z"],
                "units": ["", "um", "um", "um"],
                "scales": [1, X_UM, Y_UM, Z_UM],
                "transposeSharesMemory": bool(
                    np.shares_memory(self.data_zcyx, self.data_cxyz)
                ),
            },
        }


def make_handler(demo: Demo):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

        def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(value, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/bootstrap":
                self._json({"viewerUrl": demo.viewer.get_viewer_url(), **demo.diagnostics()})
                return
            if path == "/api/state":
                self._json(demo.diagnostics())
                return
            super().do_GET()

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/state":
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._json(demo.update(payload))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                print(f"control-http update failed: {type(exc).__name__}: {exc}")
                self._json(
                    {"error": type(exc).__name__, "detail": str(exc)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, fmt: str, *args: Any) -> None:
            if self.command == "GET" and urlparse(self.path).path == "/api/state":
                return
            print(f"control-http: {fmt % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    neuroglancer.set_server_bind_address(bind_address=args.host, bind_port=0)
    demo = Demo()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(demo))
    url = f"http://{args.host}:{server.server_port}/"
    print(f"ng-array-demo v2: {url}")
    print(f"Neuroglancer iframe endpoint: {demo.viewer.get_viewer_url()}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open_new(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
