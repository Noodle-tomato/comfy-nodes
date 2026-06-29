"""Core presigned URL IO helpers used by the ComfyUI node wrappers."""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class PresignedIoError(RuntimeError):
    """Raised when presigned URL download/upload work fails."""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True)
class DownloadResult:
    path: str
    filename: str
    content_type: str
    byte_count: int


class Transport(Protocol):
    def get(self, url: str, timeout_seconds: float) -> HttpResponse:
        """Fetch a URL and return response bytes."""

    def put(
        self,
        url: str,
        data: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        """Upload bytes to a URL with PUT."""


class UrllibTransport:
    """Small stdlib HTTP transport to avoid AWS/S3 SDK dependencies."""

    def get(self, url: str, timeout_seconds: float) -> HttpResponse:
        request = Request(url, method="GET")
        return self._open(request, timeout_seconds)

    def put(
        self,
        url: str,
        data: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        request = Request(url, data=data, headers=dict(headers), method="PUT")
        return self._open(request, timeout_seconds)

    def _open(self, request: Request, timeout_seconds: float) -> HttpResponse:
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return HttpResponse(
                    status_code=int(response.status),
                    body=response.read(),
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except HTTPError as error:
            return HttpResponse(
                status_code=int(error.code),
                body=error.read(),
                headers={key.lower(): value for key, value in error.headers.items()},
            )
        except URLError as error:
            raise PresignedIoError(f"request failed: {error.reason}") from error


def download_to_directory(
    url: str,
    *,
    directory: Path,
    filename: str,
    transport: Transport | None = None,
    timeout_seconds: float = 60,
) -> DownloadResult:
    if not url:
        raise PresignedIoError("url is required")

    safe_filename = sanitize_filename(filename or _filename_from_url(url))
    if not safe_filename:
        raise PresignedIoError("filename is required")

    directory.mkdir(parents=True, exist_ok=True)
    target = (directory / safe_filename).resolve()
    if directory.resolve() not in [target.parent, *target.parents]:
        raise PresignedIoError("download target must stay inside destination directory")

    http = transport or UrllibTransport()
    response = http.get(url, timeout_seconds)
    if response.status_code < 200 or response.status_code >= 300:
        raise PresignedIoError(f"download failed with status {response.status_code}: {_body_preview(response.body)}")

    target.write_bytes(response.body)
    content_type = _header_value(response.headers, "content-type") or guess_content_type(target)
    return DownloadResult(
        path=str(target),
        filename=safe_filename,
        content_type=normalize_content_type(content_type),
        byte_count=len(response.body),
    )


def upload_file_to_presigned_url(
    file_path: str | Path,
    put_url: str,
    *,
    content_type: str = "",
    public_url: str = "",
    transport: Transport | None = None,
    timeout_seconds: float = 120,
) -> str:
    if not put_url:
        raise PresignedIoError("put_url is required")

    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise PresignedIoError(f"file not found: {path}")

    body = path.read_bytes()
    resolved_content_type = normalize_content_type(content_type or guess_content_type(path))
    headers = {"content-type": resolved_content_type} if resolved_content_type else {}
    http = transport or UrllibTransport()
    response = http.put(put_url, body, headers, timeout_seconds)
    if response.status_code < 200 or response.status_code >= 300:
        raise PresignedIoError(f"upload failed with status {response.status_code}: {_body_preview(response.body)}")

    manifest = {
        "status": "uploaded",
        "filename": path.name,
        "path": str(path),
        "bytes": len(body),
        "content_type": resolved_content_type,
        "public_url": public_url,
    }
    return json.dumps(manifest, sort_keys=True)


def resolve_file_path(value: str, search_directories: list[Path]) -> Path:
    if not value:
        raise PresignedIoError("file_path is required")

    raw_path = Path(value).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
        if resolved.is_file():
            return resolved
        raise PresignedIoError(f"file not found: {resolved}")

    safe_parts = [part for part in raw_path.parts if part not in {"", "."}]
    if any(part == ".." for part in safe_parts):
        raise PresignedIoError(f"could not resolve relative file path: {value}")

    for directory in search_directories:
        base = directory.resolve()
        candidate = (base / raw_path).resolve()
        if base in [candidate.parent, *candidate.parents] and candidate.is_file():
            return candidate

    raise PresignedIoError(f"could not resolve file path: {value}")


def sanitize_filename(filename: str) -> str:
    basename = Path(filename).name.strip()
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    sanitized = sanitized.strip("._")
    return sanitized or "downloaded_file"


def guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    return Path(parsed.path).name or "downloaded_file"


def _header_value(headers: Mapping[str, str], key: str) -> str:
    lowered = key.lower()
    for header_key, value in headers.items():
        if header_key.lower() == lowered:
            return value
    return ""


def _body_preview(body: bytes) -> str:
    return body[:200].decode("utf-8", errors="replace")

