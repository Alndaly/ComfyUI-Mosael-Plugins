"""Minimal HTTP client for the ComfyUI API, used by integration tests."""

import base64
import json
import time
import urllib.error
import urllib.request
import uuid

# A valid 64x64 RGB PNG (small gradient), verified decodable by both PIL and
# PyAV, so tests can upload an image without requiring PIL on the client side.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAABO0lEQVR4nO3PhyonAADA4b+9"
    "9957772JiIiIXCciIiIichHRiYiIiIiIiIjIRUREdCIiIiIiIiIiwiN4gd/3Bp9AICIuJaug"
    "rKapo29kamFt5+ji7uUbEBQSFhEVE/crISklLSMrJ6+g6E9peWVVTV1DU0tbR1dP38DQyNjE1"
    "L/Z+cXl1fWNrZ29g6OTs4urm7uHp5e3jy9hMUkZeSVVDW09QxNzK1sHZzdPH//A4NDwyOjY+"
    "N+Jyanpmdm5+YXFJWUVf6tr6xubW9s7u3v7B4dHxyenZ+YWllbW/m9u7+4fHp+eX17f3j8+v7"
    "5/ColKSMspqqhr6RoYm1na2Du5enj7CQgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIE"
    "CAAAECBAgQIECAAAECBAgQIECAAAECPwW+AaPO+TwA3xa/AAAAAElFTkSuQmCC"
)

# A second valid 32x32 RGB PNG with different content, for replace-image tests.
TINY_PNG_ALT = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAZklEQVR4nLXBEQKAAAAAscMwDMMw"
    "DMMwDMMwDMMwDMMwDMMwDMMwDHvFbWALZIQyIhmxjERGKiOTkcsoZJQyKhm1jEZGK6OT0csYZIwy"
    "JhmzjEXGKmOTscs4ZJwyLhm3jEfGK+OT/W8P0EyYh42tAAAAAElFTkSuQmCC"
)


class ComfyClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def _request(self, path, data=None, method=None, headers=None):
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers=headers or {},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body else {}

    def reachable(self):
        try:
            self._request("/system_stats")
            return True
        except Exception:
            return False

    def object_info(self, node_class):
        return self._request("/object_info/" + urllib.request.quote(node_class))

    def first_checkpoint(self):
        info = self.object_info("CheckpointLoaderSimple")
        options = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        return options[0]

    def upload_image(self, content=None, name="oi_test_image.png", overwrite=True):
        content = TINY_PNG if content is None else content
        boundary = uuid.uuid4().hex
        parts = []
        parts.append(
            ('--{}\r\nContent-Disposition: form-data; name="image"; '
             'filename="{}"\r\nContent-Type: image/png\r\n\r\n').format(boundary, name).encode()
            + content + b"\r\n"
        )
        parts.append(
            '--{}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\n{}\r\n'.format(
                boundary, "true" if overwrite else "false"
            ).encode()
        )
        parts.append("--{}--\r\n".format(boundary).encode())
        body = b"".join(parts)
        result = self._request(
            "/upload/image",
            data=body,
            method="POST",
            headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        )
        return result["name"]

    def queue(self, workflow):
        """Submit an API-format workflow. Returns (prompt_id, error_dict).

        On success error_dict is None; on validation failure the parsed
        error body is returned and prompt_id is None.
        """
        body = json.dumps({"prompt": workflow, "client_id": "oi-tests"}).encode()
        try:
            result = self._request(
                "/prompt", data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            return result["prompt_id"], None
        except urllib.error.HTTPError as e:
            return None, json.loads(e.read())

    def wait(self, prompt_id, timeout=300.0, poll=1.0):
        """Wait for a prompt to finish. Returns its history entry."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self._request("/history/" + prompt_id)
            if prompt_id in history:
                return history[prompt_id]
            time.sleep(poll)
        raise TimeoutError("Prompt {} did not finish within {}s".format(prompt_id, timeout))

    @staticmethod
    def succeeded(history_entry):
        status = history_entry.get("status", {})
        if status.get("status_str") == "error":
            return False
        return bool(status.get("completed")) or status.get("status_str") == "success"

    @staticmethod
    def error_text(history_entry):
        for message in history_entry.get("status", {}).get("messages", []):
            if message[0] == "execution_error":
                return message[1].get("exception_message", "")
        return ""

    def run(self, workflow, timeout=300.0):
        """Submit and wait. Returns (succeeded, error_text_or_history)."""
        prompt_id, error = self.queue(workflow)
        if error is not None:
            return False, json.dumps(error)
        entry = self.wait(prompt_id, timeout=timeout)
        if self.succeeded(entry):
            return True, entry
        return False, self.error_text(entry)
