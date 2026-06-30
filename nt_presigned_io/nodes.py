"""ComfyUI node wrappers for presigned URL file IO."""

from __future__ import annotations

import base64
import binascii
import json
from io import BytesIO
from pathlib import Path
from typing import Literal

from .core import (
    PresignedIoError,
    download_bytes_from_presigned_url,
    download_to_directory,
    normalize_content_type,
    resolve_file_path,
    upload_bytes_to_presigned_url,
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


def image_bytes_to_tensors(body: bytes):
    try:
        import numpy as np  # type: ignore
        import torch  # type: ignore
        from PIL import Image, ImageOps, ImageSequence  # type: ignore
    except Exception as error:
        raise PresignedIoError("Pillow, NumPy, and PyTorch are required to decode image bytes") from error

    try:
        image = Image.open(BytesIO(body))
    except Exception as error:
        raise PresignedIoError(f"could not decode image bytes: {error}") from error

    output_images = []
    output_masks = []
    width = None
    height = None
    excluded_frames = 0

    for frame in ImageSequence.Iterator(image):
        frame = ImageOps.exif_transpose(frame)
        if frame.mode == "I":
            frame = frame.point(lambda value: value * (1 / 255))

        rgb_image = frame.convert("RGB")
        if width is None:
            width, height = rgb_image.size
        if rgb_image.size != (width, height):
            excluded_frames += 1
            continue

        image_array = np.array(rgb_image).astype(np.float32) / 255.0
        output_images.append(torch.from_numpy(image_array)[None,])

        if "A" in frame.getbands():
            mask_array = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
            output_masks.append(1.0 - torch.from_numpy(mask_array))
        else:
            output_masks.append(torch.zeros((height, width), dtype=torch.float32))

    if not output_images:
        raise PresignedIoError("image did not contain any decodable frames")

    if excluded_frames:
        print(f"NTLoadImage: excluded {excluded_frames} frames with mismatched dimensions")

    return (torch.cat(output_images, dim=0), torch.stack(output_masks, dim=0))


def decode_base64_image_data(value: str, content_type: str = "") -> tuple[bytes, str]:
    raw_value = value.strip()
    resolved_content_type = normalize_content_type(content_type)
    encoded = raw_value

    if raw_value.startswith("data:"):
        metadata, separator, payload = raw_value.partition(",")
        if not separator:
            raise PresignedIoError("image data URI is missing a base64 payload")
        if ";base64" not in metadata:
            raise PresignedIoError("image data URI must use base64 encoding")
        encoded = payload
        if not resolved_content_type:
            media_type = metadata[5:].split(";", 1)[0]
            resolved_content_type = normalize_content_type(media_type)

    try:
        body = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise PresignedIoError("image must be valid base64") from error

    return (body, resolved_content_type or "application/octet-stream")


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


class NTLoadImageFromPresignedURL:
    CATEGORY = "NoodleTomato/S3"
    DESCRIPTION = "Download an image from a presigned HTTP(S) URL and decode it directly into ComfyUI tensors."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "url": ("STRING", {"multiline": False}),
            },
            "optional": {
                "filename": ("STRING", {"default": "input.png", "multiline": False}),
                "timeout_seconds": ("FLOAT", {"default": 60.0, "min": 1.0, "max": 3600.0, "step": 1.0}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "INT")
    RETURN_NAMES = ("image", "mask", "content_type", "bytes")
    FUNCTION = "load_image"

    def load_image(
        self,
        url: str,
        filename: str = "input.png",
        timeout_seconds: float = 60.0,
    ):
        result = download_bytes_from_presigned_url(
            url,
            filename=filename,
            timeout_seconds=float(timeout_seconds),
        )
        image, mask = image_bytes_to_tensors(result.body)
        return (image, mask, result.content_type, result.byte_count)


class NTLoadImageFromBase64:
    CATEGORY = "NoodleTomato/S3"
    DESCRIPTION = "Decode a base64 image payload directly into ComfyUI tensors."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("STRING", {"multiline": True}),
            },
            "optional": {
                "content_type": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "INT")
    RETURN_NAMES = ("image", "mask", "content_type", "bytes")
    FUNCTION = "load_image"

    def load_image(
        self,
        image: str,
        content_type: str = "",
    ):
        body, resolved_content_type = decode_base64_image_data(image, content_type)
        tensor_image, mask = image_bytes_to_tensors(body)
        return (tensor_image, mask, resolved_content_type, len(body))


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


class NTEncodeAndUploadVideoToPresignedURL:
    CATEGORY = "NoodleTomato/S3"
    DESCRIPTION = "Encode a ComfyUI VIDEO object in memory and upload the bytes to a presigned HTTP PUT URL."
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "put_url": ("STRING", {"multiline": False}),
            },
            "optional": {
                "filename": ("STRING", {"default": "output.mp4", "multiline": False}),
                "content_type": ("STRING", {"default": "video/mp4", "multiline": False}),
                "public_url": ("STRING", {"default": "", "multiline": False}),
                "timeout_seconds": ("FLOAT", {"default": 120.0, "min": 1.0, "max": 7200.0, "step": 1.0}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("manifest_json", "status", "bytes")
    FUNCTION = "encode_and_upload"

    def encode_and_upload(
        self,
        video,
        put_url: str,
        filename: str = "output.mp4",
        content_type: str = "video/mp4",
        public_url: str = "",
        timeout_seconds: float = 120.0,
    ):
        buffer = BytesIO()
        video.save_to(buffer)
        body = buffer.getvalue()
        manifest_json = upload_bytes_to_presigned_url(
            body,
            put_url,
            filename=filename,
            content_type=content_type,
            public_url=public_url,
            timeout_seconds=float(timeout_seconds),
        )
        manifest = json.loads(manifest_json)
        return (manifest_json, str(manifest.get("status", "")), int(manifest.get("bytes", 0)))


NODE_CLASS_MAPPINGS = {
    "NTDownloadFileFromPresignedURL": NTDownloadFileFromPresignedURL,
    "NTLoadImageFromPresignedURL": NTLoadImageFromPresignedURL,
    "NTLoadImageFromBase64": NTLoadImageFromBase64,
    "NTUploadFileToPresignedURL": NTUploadFileToPresignedURL,
    "NTEncodeAndUploadVideoToPresignedURL": NTEncodeAndUploadVideoToPresignedURL,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NTDownloadFileFromPresignedURL": "NT Download File From Presigned URL",
    "NTLoadImageFromPresignedURL": "NT Load Image From Presigned URL",
    "NTLoadImageFromBase64": "NT Load Image From Base64",
    "NTUploadFileToPresignedURL": "NT Upload File To Presigned URL",
    "NTEncodeAndUploadVideoToPresignedURL": "NT Encode And Upload Video To Presigned URL",
}
