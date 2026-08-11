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


SOURCE_PREFIX = "direct-demo-"


def source_key(dataset_key: str) -> str:
    return f"{SOURCE_PREFIX}{dataset_key}"


def make_volume(dataset_key: str) -> neuroglancer.LocalVolume:
    spec = DATASETS[dataset_key]
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
    volumes: dict[str, neuroglancer.LocalVolume]

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            if parts == ["api", "health"]:
                self._send_json(
                    {
                        "ok": True,
                        "sources": [
                            f"python://volume/{source_key(key)}" for key in DATASETS
                        ],
                    }
                )
                return
            if len(parts) == 3 and parts[:2] == ["neuroglancer", "info"]:
                volume = self.volumes.get(parts[2])
                if volume is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json(volume.info())
                return
            if (
                len(parts) == 6
                and parts[0] == "neuroglancer"
                and parts[1] in {"raw", "npz"}
            ):
                _, data_format, key, scale_key, start_text, end_text = parts
                volume = self.volumes.get(key)
                if volume is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                start = np.array(start_text.split(","), dtype=np.int64)
                end = np.array(end_text.split(","), dtype=np.int64)
                payload, content_type = volume.get_encoded_subvolume(
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
    Handler.volumes = {source_key(key): make_volume(key) for key in DATASETS}
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"NumPy datasource: http://127.0.0.1:{args.port}/")
    for key in DATASETS:
        print(f"Neuroglancer source: python://volume/{source_key(key)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
