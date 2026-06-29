from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

from nt_presigned_io.core import (
    DownloadResult,
    HttpResponse,
    PresignedIoError,
    download_to_directory,
    resolve_file_path,
    upload_file_to_presigned_url,
)


class FakeTransport:
    def __init__(self) -> None:
        self.get_responses: dict[str, HttpResponse] = {}
        self.put_calls: list[dict[str, object]] = []

    def get(self, url: str, timeout_seconds: float) -> HttpResponse:
        del timeout_seconds
        response = self.get_responses.get(url)
        if response is None:
            raise AssertionError(f"unexpected GET {url}")
        return response

    def put(
        self,
        url: str,
        data: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        del timeout_seconds
        self.put_calls.append({"url": url, "data": data, "headers": dict(headers)})
        return HttpResponse(status_code=200, body=b"", headers={})


class PresignedIoCoreTest(unittest.TestCase):
    def test_download_writes_bytes_to_safe_filename_and_returns_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transport = FakeTransport()
            transport.get_responses["https://signed.example.com/input.png?token=secret"] = HttpResponse(
                status_code=200,
                body=b"png-bytes",
                headers={"content-type": "image/png"},
            )

            result = download_to_directory(
                "https://signed.example.com/input.png?token=secret",
                directory=Path(tmp),
                filename="../unsafe name.png",
                transport=transport,
                timeout_seconds=5,
            )

            self.assertIsInstance(result, DownloadResult)
            self.assertEqual(result.filename, "unsafe_name.png")
            self.assertEqual(result.content_type, "image/png")
            self.assertEqual(result.byte_count, 9)
            self.assertEqual(Path(result.path).read_bytes(), b"png-bytes")
            self.assertEqual(Path(result.path).parent, Path(tmp).resolve())

    def test_download_rejects_failed_status_without_writing_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transport = FakeTransport()
            transport.get_responses["https://signed.example.com/missing"] = HttpResponse(
                status_code=403,
                body=b"expired",
                headers={},
            )

            with self.assertRaisesRegex(PresignedIoError, "download failed with status 403"):
                download_to_directory(
                    "https://signed.example.com/missing",
                    directory=Path(tmp),
                    filename="missing.bin",
                    transport=transport,
                    timeout_seconds=5,
                )

            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_upload_file_puts_bytes_and_returns_json_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "clip.mp4")
            path.write_bytes(b"video-bytes")
            transport = FakeTransport()

            manifest = upload_file_to_presigned_url(
                path,
                "https://signed.example.com/output.mp4?token=secret",
                content_type="video/mp4",
                public_url="https://cdn.example.com/output.mp4",
                transport=transport,
                timeout_seconds=5,
            )

            self.assertEqual(
                transport.put_calls,
                [
                    {
                        "url": "https://signed.example.com/output.mp4?token=secret",
                        "data": b"video-bytes",
                        "headers": {"content-type": "video/mp4"},
                    }
                ],
            )
            decoded = json.loads(manifest)
            self.assertEqual(decoded["filename"], "clip.mp4")
            self.assertEqual(decoded["bytes"], 11)
            self.assertEqual(decoded["content_type"], "video/mp4")
            self.assertEqual(decoded["public_url"], "https://cdn.example.com/output.mp4")
            self.assertEqual(decoded["status"], "uploaded")

    def test_upload_rejects_non_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PresignedIoError, "file not found"):
                upload_file_to_presigned_url(
                    Path(tmp, "missing.mp4"),
                    "https://signed.example.com/output.mp4",
                    transport=FakeTransport(),
                    timeout_seconds=5,
                )

    def test_resolve_file_path_limits_relative_paths_to_known_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir()
            expected = output_dir / "clip.mp4"
            expected.write_bytes(b"clip")

            self.assertEqual(resolve_file_path("clip.mp4", [output_dir]), expected.resolve())

            with self.assertRaisesRegex(PresignedIoError, "could not resolve"):
                resolve_file_path("../secret.txt", [output_dir])


if __name__ == "__main__":
    unittest.main()
