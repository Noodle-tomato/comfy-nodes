from __future__ import annotations

import json
import importlib.util
from base64 import b64encode
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nt_presigned_io
from nt_presigned_io.core import DownloadBytesResult, DownloadResult
from nt_presigned_io.nodes import (
    NTDownloadFileFromPresignedURL,
    NTEncodeAndUploadVideoToPresignedURL,
    NTLoadImageFromBase64,
    NTLoadImageFromPresignedURL,
    NTUploadFileToPresignedURL,
)


class NodeRegistrationTest(unittest.TestCase):
    def test_repository_root_init_exports_comfyui_mappings(self) -> None:
        root_init = Path(__file__).resolve().parents[1] / "__init__.py"
        spec = importlib.util.spec_from_file_location("comfy_nodes_root", root_init)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        self.assertIn("NTDownloadFileFromPresignedURL", module.NODE_CLASS_MAPPINGS)
        self.assertIn("NTLoadImageFromPresignedURL", module.NODE_CLASS_MAPPINGS)
        self.assertIn("NTLoadImageFromBase64", module.NODE_CLASS_MAPPINGS)
        self.assertIn("NTUploadFileToPresignedURL", module.NODE_CLASS_MAPPINGS)
        self.assertIn("NTEncodeAndUploadVideoToPresignedURL", module.NODE_CLASS_MAPPINGS)

    def test_package_exports_comfyui_node_mappings(self) -> None:
        self.assertIn("NTDownloadFileFromPresignedURL", nt_presigned_io.NODE_CLASS_MAPPINGS)
        self.assertIn("NTLoadImageFromPresignedURL", nt_presigned_io.NODE_CLASS_MAPPINGS)
        self.assertIn("NTLoadImageFromBase64", nt_presigned_io.NODE_CLASS_MAPPINGS)
        self.assertIn("NTUploadFileToPresignedURL", nt_presigned_io.NODE_CLASS_MAPPINGS)
        self.assertIn("NTEncodeAndUploadVideoToPresignedURL", nt_presigned_io.NODE_CLASS_MAPPINGS)
        self.assertEqual(
            nt_presigned_io.NODE_DISPLAY_NAME_MAPPINGS["NTDownloadFileFromPresignedURL"],
            "NT Download File From Presigned URL",
        )
        self.assertEqual(
            nt_presigned_io.NODE_DISPLAY_NAME_MAPPINGS["NTLoadImageFromPresignedURL"],
            "NT Load Image From Presigned URL",
        )
        self.assertEqual(
            nt_presigned_io.NODE_DISPLAY_NAME_MAPPINGS["NTLoadImageFromBase64"],
            "NT Load Image From Base64",
        )
        self.assertEqual(
            nt_presigned_io.NODE_DISPLAY_NAME_MAPPINGS["NTUploadFileToPresignedURL"],
            "NT Upload File To Presigned URL",
        )
        self.assertEqual(
            nt_presigned_io.NODE_DISPLAY_NAME_MAPPINGS["NTEncodeAndUploadVideoToPresignedURL"],
            "NT Encode And Upload Video To Presigned URL",
        )

    def test_download_node_exposes_path_filename_content_type_and_byte_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("nt_presigned_io.nodes.get_comfy_directory", return_value=Path(tmp)), patch(
                "nt_presigned_io.nodes.download_to_directory",
                return_value=DownloadResult(
                    path=str(Path(tmp, "input.png")),
                    filename="input.png",
                    content_type="image/png",
                    byte_count=12,
                ),
            ) as download:
                result = NTDownloadFileFromPresignedURL().download(
                    url="https://signed.example.com/input.png",
                    filename="input.png",
                    destination="input",
                    timeout_seconds=30,
                )

            self.assertEqual(result, (str(Path(tmp, "input.png")), "input.png", "image/png", 12))
            download.assert_called_once()

    def test_upload_node_returns_manifest_status_and_byte_count(self) -> None:
        manifest = json.dumps({"status": "uploaded", "bytes": 4})
        with patch("nt_presigned_io.nodes.get_comfy_search_directories", return_value=[]), patch(
            "nt_presigned_io.nodes.resolve_file_path",
            return_value=Path("/tmp/output.mp4"),
        ), patch(
            "nt_presigned_io.nodes.upload_file_to_presigned_url",
            return_value=manifest,
        ) as upload:
            result = NTUploadFileToPresignedURL().upload(
                file_path="/tmp/output.mp4",
                put_url="https://signed.example.com/output.mp4",
                content_type="video/mp4",
                public_url="https://cdn.example.com/output.mp4",
                timeout_seconds=120,
            )

        self.assertEqual(result, (manifest, "uploaded", 4))
        upload.assert_called_once()

    def test_load_presigned_image_node_returns_tensors_from_downloaded_bytes(self) -> None:
        with patch(
            "nt_presigned_io.nodes.download_bytes_from_presigned_url",
            return_value=DownloadBytesResult(
                body=b"png-bytes",
                filename="input.png",
                content_type="image/png",
                byte_count=9,
            ),
        ) as download, patch(
            "nt_presigned_io.nodes.image_bytes_to_tensors",
            return_value=("image_tensor", "mask_tensor"),
        ) as convert:
            result = NTLoadImageFromPresignedURL().load_image(
                url="https://signed.example.com/input.png",
                filename="input.png",
                timeout_seconds=30,
            )

        self.assertEqual(result, ("image_tensor", "mask_tensor", "image/png", 9))
        download.assert_called_once_with(
            "https://signed.example.com/input.png",
            filename="input.png",
            timeout_seconds=30.0,
        )
        convert.assert_called_once_with(b"png-bytes")

    def test_load_base64_image_node_decodes_data_uri_before_tensor_conversion(self) -> None:
        encoded = b64encode(b"png-bytes").decode("ascii")
        with patch(
            "nt_presigned_io.nodes.image_bytes_to_tensors",
            return_value=("image_tensor", "mask_tensor"),
        ) as convert:
            result = NTLoadImageFromBase64().load_image(
                image=f"data:image/png;base64,{encoded}",
                content_type="",
            )

        self.assertEqual(result, ("image_tensor", "mask_tensor", "image/png", 9))
        convert.assert_called_once_with(b"png-bytes")

    def test_encode_and_upload_video_node_streams_video_bytes_to_presigned_url(self) -> None:
        class FakeVideo:
            def save_to(self, target):
                target.write(b"mp4-bytes")

        manifest = json.dumps({"status": "uploaded", "bytes": 9})
        with patch(
            "nt_presigned_io.nodes.upload_bytes_to_presigned_url",
            return_value=manifest,
        ) as upload:
            result = NTEncodeAndUploadVideoToPresignedURL().encode_and_upload(
                video=FakeVideo(),
                put_url="https://signed.example.com/output.mp4",
                filename="clip.mp4",
                content_type="video/mp4",
                public_url="https://cdn.example.com/output.mp4",
                timeout_seconds=600,
            )

        self.assertEqual(result, (manifest, "uploaded", 9))
        upload.assert_called_once_with(
            b"mp4-bytes",
            "https://signed.example.com/output.mp4",
            filename="clip.mp4",
            content_type="video/mp4",
            public_url="https://cdn.example.com/output.mp4",
            timeout_seconds=600.0,
        )


if __name__ == "__main__":
    unittest.main()
