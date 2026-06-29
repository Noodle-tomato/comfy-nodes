"""ComfyUI node wrappers for presigned URL file IO."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .core import (
    download_to_directory,
    resolve_file_path,
    upload_file_to_presigned_url,
)


Destination = Literal["input", "output", "temp"]


def get_comfy_directory(destination: Destination) -> Path:
    try:
        import folder_paths  # type: ignore

        if destination == "input":
            return Path(folder_paths.get_input_directory())
        if destination == "output":
            return Path(folder_paths.get_output_directory())
        return Path(folder_paths.get_temp_directory())
    except Exception:
        fallback_root = Path.cwd()
        return fallback_root / destination


def get_comfy_search_directories() -> list[Path]:
    return [get_comfy_directory("output"), get_comfy_directory("input"), get_comfy_directory("temp")]


class NTDownloadFileFromPresignedURL:
    CATEGORY = "NoodleTomato/S3"
    DESCRIPTION = "Download a file from a presigned HTTP(S) URL into a ComfyUI directory."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "url": ("STRING", {"multiline": False}),
                "filename": ("STRING", {"default": "input.bin", "multiline": False}),
                "destination": (["input", "output", "temp"], {"default": "input"}),
            },
            "optional": {
                "timeout_seconds": ("FLOAT", {"default": 60.0, "min": 1.0, "max": 3600.0, "step": 1.0}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("file_path", "filename", "content_type", "bytes")
    FUNCTION = "download"

    def download(
        self,
        url: str,
        filename: str,
        destination: Destination = "input",
        timeout_seconds: float = 60.0,
    ):
        result = download_to_directory(
            url,
            directory=get_comfy_directory(destination),
            filename=filename,
            timeout_seconds=float(timeout_seconds),
        )
        return (result.path, result.filename, result.content_type, result.byte_count)


class NTUploadFileToPresignedURL:
    CATEGORY = "NoodleTomato/S3"
    DESCRIPTION = "Upload a local ComfyUI file to a presigned HTTP PUT URL."
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file_path": ("STRING", {"multiline": False}),
                "put_url": ("STRING", {"multiline": False}),
            },
            "optional": {
                "content_type": ("STRING", {"default": "", "multiline": False}),
                "public_url": ("STRING", {"default": "", "multiline": False}),
                "timeout_seconds": ("FLOAT", {"default": 120.0, "min": 1.0, "max": 7200.0, "step": 1.0}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("manifest_json", "status", "bytes")
    FUNCTION = "upload"

    def upload(
        self,
        file_path: str,
        put_url: str,
        content_type: str = "",
        public_url: str = "",
        timeout_seconds: float = 120.0,
    ):
        resolved_path = resolve_file_path(file_path, get_comfy_search_directories())
        manifest_json = upload_file_to_presigned_url(
            resolved_path,
            put_url,
            content_type=content_type,
            public_url=public_url,
            timeout_seconds=float(timeout_seconds),
        )
        manifest = json.loads(manifest_json)
        return (manifest_json, str(manifest.get("status", "")), int(manifest.get("bytes", 0)))


NODE_CLASS_MAPPINGS = {
    "NTDownloadFileFromPresignedURL": NTDownloadFileFromPresignedURL,
    "NTUploadFileToPresignedURL": NTUploadFileToPresignedURL,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NTDownloadFileFromPresignedURL": "NT Download File From Presigned URL",
    "NTUploadFileToPresignedURL": "NT Upload File To Presigned URL",
}

