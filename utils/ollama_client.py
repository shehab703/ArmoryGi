from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1"
    temperature: float = 0.3
    num_ctx: int | None = None
    timeout_s: float = 60.0


def _join_url(base_url: str, path: str) -> str:
    base = (base_url or "").rstrip("/")
    p = (path or "").lstrip("/")
    return f"{base}/{p}"


class OllamaClient:
    """
    Ollama client wrapper.

    Preference order:
    1) Use the official Python client (`pip install ollama`) when available.
    2) Fallback to direct HTTP calls to the local Ollama server.

    HTTP API docs: https://github.com/ollama/ollama/blob/main/docs/api.md
    """

    def __init__(self, cfg: OllamaConfig):
        self.cfg = cfg
        self._py = None
        self._use_python_client = False
        self._py_client = None
        try:
            import ollama  # type: ignore

            self._py = ollama
            self._use_python_client = True
            try:
                # Prefer explicit host binding so app settings work.
                # (ollama.Client is available in ollama-python)
                self._py_client = getattr(ollama, "Client")(host=str(self.cfg.base_url))
            except Exception:
                self._py_client = None
        except Exception:
            self._py = None
            self._use_python_client = False
            self._py_client = None

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = _join_url(self.cfg.base_url, path)
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg.timeout_s)) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise OllamaError(f"Ollama HTTP {e.code}: {body or e.reason}") from e
        except (urllib.error.URLError, socket.timeout) as e:
            raise OllamaError(f"Failed to reach Ollama at {self.cfg.base_url}: {e}") from e
        try:
            return json.loads(raw) if raw else {}
        except Exception as e:
            raise OllamaError(f"Invalid JSON from Ollama: {raw[:300]}") from e

    def list_models(self) -> list[str]:
        if self._use_python_client and self._py is not None:
            try:
                # Python client returns dict with `models`
                if self._py_client is not None:
                    data = self._py_client.list()
                else:
                    data = self._py.list()
                models = []
                for m in (data.get("models") or []):
                    name = m.get("name")
                    if name:
                        models.append(str(name))
                return models
            except Exception:
                # fallback to HTTP
                pass
        data = self._request_json("GET", "/api/tags", None)
        models = []
        for m in (data.get("models") or []):
            name = m.get("name")
            if name:
                models.append(str(name))
        return models

    def chat(self, *, system: str, user: str) -> str:
        options: dict[str, Any] = {"temperature": float(self.cfg.temperature)}
        if self.cfg.num_ctx is not None:
            options["num_ctx"] = int(self.cfg.num_ctx)

        if self._use_python_client and self._py is not None:
            try:
                call = self._py_client.chat if self._py_client is not None else self._py.chat
                data = call(
                    model=self.cfg.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    options=options,
                )
                msg = (data.get("message") or {}).get("content")
                return str(msg or "").strip()
            except Exception as e:
                # fallback to HTTP
                try:
                    self._use_python_client = False
                except Exception:
                    pass
                # keep going to HTTP path

        payload = {
            "model": self.cfg.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": options,
        }
        data = self._request_json("POST", "/api/chat", payload)
        msg = (data.get("message") or {}).get("content")
        if not msg:
            # Fallback (older responses)
            msg = data.get("response")
        return str(msg or "").strip()

    def chat_stream(self, *, system: str, user: str) -> Iterable[str]:
        """
        Yields incremental text chunks.
        Prefer this for large models to avoid long blocking waits.
        """
        options: dict[str, Any] = {"temperature": float(self.cfg.temperature)}
        if self.cfg.num_ctx is not None:
            options["num_ctx"] = int(self.cfg.num_ctx)

        # Python client streaming (if available)
        if self._use_python_client and self._py is not None:
            try:
                call = self._py_client.chat if self._py_client is not None else self._py.chat
                it = call(
                    model=self.cfg.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    options=options,
                    stream=True,
                )
                for part in it:
                    msg = (part.get("message") or {}).get("content")
                    if msg:
                        yield str(msg)
                return
            except Exception:
                try:
                    self._use_python_client = False
                except Exception:
                    pass

        # HTTP streaming fallback: newline-delimited JSON objects
        url = _join_url(self.cfg.base_url, "/api/chat")
        payload = {
            "model": self.cfg.model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": options,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg.timeout_s)) as resp:
                # Stream is chunked; each line is a JSON object
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    try:
                        obj = json.loads(line.decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    msg = (obj.get("message") or {}).get("content")
                    if msg:
                        yield str(msg)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise OllamaError(f"Ollama HTTP {e.code}: {body or e.reason}") from e
        except (urllib.error.URLError, socket.timeout) as e:
            raise OllamaError(f"Failed to reach Ollama at {self.cfg.base_url}: {e}") from e

