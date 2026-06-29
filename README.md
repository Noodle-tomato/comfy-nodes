# NoodleTomato ComfyUI Nodes

Small ComfyUI custom nodes for workflow-embedded presigned URL file IO.

These nodes are intentionally dumb transport nodes:

- They do not use AWS credentials.
- They do not generate presigned URLs.
- They do not know bucket names, keys, tenants, or NoodleTomato project IDs.
- They only consume URLs and metadata already patched into the ComfyUI workflow.

This keeps a RunPod ComfyUI worker reusable: the worker receives a patched workflow, ComfyUI executes the workflow, and the worker returns ComfyUI's raw outputs.

## Nodes

### NT Download File From Presigned URL

Downloads bytes from an HTTP(S) presigned URL into one of ComfyUI's local directories.

Inputs:

| Name | Type | Description |
| --- | --- | --- |
| `url` | `STRING` | Presigned GET URL. |
| `filename` | `STRING` | Local filename to write. Path separators are stripped and unsafe characters become `_`. |
| `destination` | `input`, `output`, `temp` | ComfyUI directory to write into. Defaults to `input`. |
| `timeout_seconds` | `FLOAT` | Download timeout. Defaults to `60`. |

Outputs:

| Name | Type | Description |
| --- | --- | --- |
| `file_path` | `STRING` | Absolute path of the downloaded file. |
| `filename` | `STRING` | Sanitized local filename. |
| `content_type` | `STRING` | Response content type, or extension-based fallback. |
| `bytes` | `INT` | Downloaded byte count. |

### NT Upload File To Presigned URL

Uploads a local file to an HTTP `PUT` presigned URL.

Inputs:

| Name | Type | Description |
| --- | --- | --- |
| `file_path` | `STRING` | Absolute path, or a relative filename found in ComfyUI `output`, `input`, or `temp`. |
| `put_url` | `STRING` | Presigned PUT URL. |
| `content_type` | `STRING` | Optional content type. If empty, guessed from the filename. |
| `public_url` | `STRING` | Optional URL/key to include in the returned manifest. |
| `timeout_seconds` | `FLOAT` | Upload timeout. Defaults to `120`. |

Outputs:

| Name | Type | Description |
| --- | --- | --- |
| `manifest_json` | `STRING` | JSON upload manifest. |
| `status` | `STRING` | `uploaded` when the PUT succeeds. |
| `bytes` | `INT` | Uploaded byte count. |

The upload node is marked as an output node so its manifest can appear in ComfyUI history.

## Install

Clone this repository into ComfyUI's `custom_nodes` directory:

```bash
cd /comfyui/custom_nodes
git clone https://github.com/Noodle-tomato/comfy-nodes.git
```

Then restart ComfyUI.

No extra runtime dependencies are required beyond Python's standard library.

## Example API Workflow Shape

This is a reduced API-workflow sketch. Real node IDs and links depend on your generated workflow.

```json
{
  "1": {
    "class_type": "NTDownloadFileFromPresignedURL",
    "inputs": {
      "url": "https://s3.example.com/input.png?X-Amz-Signature=...",
      "filename": "reference.png",
      "destination": "input",
      "timeout_seconds": 60
    }
  },
  "99": {
    "class_type": "NTUploadFileToPresignedURL",
    "inputs": {
      "file_path": "generated.mp4",
      "put_url": "https://s3.example.com/output.mp4?X-Amz-Signature=...",
      "content_type": "video/mp4",
      "public_url": "https://cdn.example.com/output.mp4",
      "timeout_seconds": 300
    }
  }
}
```

## Tests

```bash
python -m unittest discover -s tests
python -m compileall nt_presigned_io tests
```

