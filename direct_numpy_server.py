from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import neuroglancer
import numpy as np
from neuroglancer.json_utils import json_encoder_default

from server import DATASETS, make_dataset


SOURCE_KEY = "direct-demo"


def make_volume() -> neuroglancer.LocalVolume:
    spec = DATASETS["a"]
    data_cxyz = make_dataset(spec).transpose(1, 3, 2, 0)
    x_um, y_um, z_um = spec.scales_um
    return neuroglancer.LocalVolume(
        data=data_cxyz,
        dimensions=neuroglancer.CoordinateSpace(
            names=["c^", "x", "y", "z"],
            units=["", "um", "um", "um"],
            scales=[1, x_um, y_um, z_um],
        ),
        volume_type="image",
        encoding="npz",
        downsampling=None,
    )


class Handler(BaseHTTPRequestHandler):
    volume: neuroglancer.LocalVolume

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            if parts == ["api", "health"]:
                self._send_json({"ok": True, "source": f"python://volume/{SOURCE_KEY}"})
                return
            if parts == ["neuroglancer", "info", SOURCE_KEY]:
                self._send_json(self.volume.info())
                return
            if (
                len(parts) == 6
                and parts[0] == "neuroglancer"
                and parts[1] in {"raw", "npz"}
                and parts[2] == SOURCE_KEY
            ):
                _, data_format, _, scale_key, start_text, end_text = parts
                start = np.array(start_text.split(","), dtype=np.int64)
                end = np.array(end_text.split(","), dtype=np.int64)
                payload, content_type = self.volume.get_encoded_subvolume(
                    data_format=data_format, start=start, end=end, scale_key=scale_key
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
        except (ValueError, IndexError) as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _send_json(self, value: object) -> None:
        payload = json.dumps(
            value, default=json_encoder_default, separators=(",", ":")
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f'numpy-http: {fmt % args}')


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the direct-JS NumPy milestone")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    Handler.volume = make_volume()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"NumPy datasource: http://127.0.0.1:{args.port}/")
    print(f"Neuroglancer source: python://volume/{SOURCE_KEY}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
