"""ComfyUI extension entrypoint for NoodleTomato presigned URL nodes."""

from pathlib import Path
import sys

_NODE_DIR = str(Path(__file__).resolve().parent)
if _NODE_DIR not in sys.path:
    sys.path.insert(0, _NODE_DIR)

from nt_presigned_io import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
