"""Image API adapter. Credentials stay in process; no API calls at import time."""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import os
import re
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_RESPONSE_BYTES = 48 * 1024 * 1024
DEFAULT_MODEL = "gpt-image-2.6-flare"


class ImageError(Exception):
    """Only deliberately sanitized messages may cross the tool boundary."""


@dataclass(repr=False)
class Settings:
    base_url: str
    key: str = field(repr=False)
    headers: dict = field(default_factory=dict, repr=False)
    model: str = DEFAULT_MODEL
    roots: tuple[Path, ...] = ()
    credential_source: str = "unavailable"

    @classmethod
    def load(cls, env=None, home=None):
        env = os.environ if env is None else env
        home = Path.home() if home is None else Path(home)
        codex = Path(env.get("CODEX_HOME", home / ".codex"))
        try:
            config_path = codex / "config.toml"
            config = tomllib.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
            profile_name = env.get("IMAGEGEN_CODEX_PROFILE", config.get("profile"))
            profile = config.get("profiles", {}).get(profile_name, {})
            provider_name = profile.get("model_provider", config.get("model_provider", "openai"))
            provider = config.get("model_providers", {}).get(provider_name, {})
            configured_base = provider.get("base_url", "https://api.openai.com/v1").rstrip("/")
            override = env.get("IMAGEGEN_BASE_URL")
            base = (override or configured_base).rstrip("/")
            u = urlsplit(base)
            if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ImageError("API base URL must be HTTPS without credentials, query or fragment.")
            key = env.get("IMAGEGEN_API_KEY", "")
            source = "IMAGEGEN_API_KEY" if key else "unavailable"
            headers = {}
            # Never reuse a Codex credential or secret header for a different endpoint.
            if base != configured_base:
                if not key:
                    raise ImageError("A different IMAGEGEN_BASE_URL requires IMAGEGEN_API_KEY.")
            else:
                headers = dict(provider.get("http_headers", {}))
                for header, variable in provider.get("env_http_headers", {}).items():
                    if env.get(variable):
                        headers[header] = env[variable]
                if not key:
                    variable = provider.get("env_key") or "OPENAI_API_KEY"
                    key = env.get(variable, "")
                    if key:
                        source = "provider environment"
                    elif not provider.get("env_key"):
                        auth_path = codex / "auth.json"
                        auth = json.loads(auth_path.read_text(encoding="utf-8-sig")) if auth_path.exists() else {}
                        key = auth.get("OPENAI_API_KEY") or ""
                        if key:
                            source = "Codex auth.json API key"
            # Provider Authorization is replaced by the selected key. Do not support session tokens.
            headers = {k: v for k, v in headers.items() if k.lower() not in {"authorization", "host", "content-length", "content-type"}}
            roots = tuple(Path(p).expanduser().resolve() for p in env.get(
                "IMAGEGEN_ALLOWED_ROOTS", str(home / "Documents" / "Codex")
            ).split(os.pathsep) if p)
            return cls(base, key, headers, env.get("IMAGEGEN_MODEL", DEFAULT_MODEL), roots, source)
        except ImageError:
            raise
        except Exception:
            raise ImageError("Cannot parse local Codex configuration or credentials.") from None


def image_info(data: bytes):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageError("Image is empty or exceeds the 30 MiB limit.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in {"PNG", "JPEG", "WEBP"} or im.width * im.height > 40_000_000:
                raise ImageError("Only PNG, JPEG and WebP images up to 40 megapixels are supported.")
            result = (im.format.lower(), im.width, im.height)
            im.verify()
            return result
    except ImageError:
        raise
    except Exception:
        raise ImageError("Provider or input did not contain a valid supported image.") from None


class ImageService:
    def __init__(self, settings: Settings, transport=None, request_timeout=240):
        self.settings = settings
        self.transport = transport
        self.request_timeout = request_timeout

    def status(self):
        return {"configured": bool(self.settings.key), "endpoint_host": urlsplit(self.settings.base_url).hostname,
                "model": self.settings.model, "credential_source": self.settings.credential_source,
                "allowed_roots": [str(p) for p in self.settings.roots],
                "online_verified": False, "response_format": "b64_json", "automatic_retries": 0}

    def path(self, value: str, *, must_exist=False):
        p = Path(value).expanduser()
        if not p.is_absolute():
            raise ImageError("Use an absolute local path.")
        p = p.resolve()
        if not any(p == root or p.is_relative_to(root) for root in self.settings.roots):
            raise ImageError("Path is outside IMAGEGEN_ALLOWED_ROOTS.")
        if must_exist and not p.is_file():
            raise ImageError("Input image does not exist or is not a file.")
        return p

    async def request(self, route, *, method="POST", **kwargs):
        if not self.settings.key:
            raise ImageError("No API key found. Configure IMAGEGEN_API_KEY or the Codex provider API key locally.")
        headers = {**self.settings.headers, "Authorization": f"Bearer {self.settings.key}"}
        try:
            async with asyncio.timeout(self.request_timeout), httpx.AsyncClient(timeout=httpx.Timeout(240, connect=20),
                                         follow_redirects=False, transport=self.transport) as client:
                async with client.stream(method, self.settings.base_url + route, headers=headers, **kwargs) as response:
                    if not 200 <= response.status_code < 300:
                        raise ImageError(f"Provider HTTP {response.status_code}. Check endpoint, model access and authentication. "
                                         "Response body withheld; request was not retried.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ImageError("Provider response exceeded 48 MiB; request was not retried.")
                    result = json.loads(body)
                    if not isinstance(result, dict):
                        raise ImageError("Provider returned an unexpected response structure.")
                    return result
        except ImageError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise ImageError("Provider timed out. The request may have been billed; no automatic retry was made.") from None
        except httpx.RequestError:
            raise ImageError("Provider connection failed; no automatic retry was made.") from None
        except (ValueError, TypeError):
            raise ImageError("Provider returned invalid JSON; no automatic retry was made.") from None

    async def models(self):
        result = await self.request("/models", method="GET")
        return {"advertised_image_models": [m["id"] for m in result.get("data", [])
                if isinstance(m, dict) and isinstance(m.get("id"), str) and "image" in m["id"].lower()],
                "note": "Listing does not prove generation access; some gateways do not expose image models here."}

    async def create(self, prompt: str, output_dir: str, *, model=None, size="1024x1024",
                     quality="auto", background=None, output_format="png", images=None, mask=None):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
            raise ImageError("Prompt must contain 1 to 32000 characters.")
        model = model or self.settings.model
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", model):
            raise ImageError("Invalid model identifier.")
        if quality not in {"auto", "low", "medium", "high", "xhigh", "max"}:
            raise ImageError("Unsupported quality.")
        image2 = bool(re.fullmatch(r"gpt-image-2(?:-\d{4}-\d{2}-\d{2})?", model))
        sunburst_or_flare = bool(re.fullmatch(r"gpt-image-2\.[56]-(?:flare|sunburst)(?:-\d{4}-\d{2}-\d{2})?", model))
        if image2 and quality in {"xhigh", "max"}:
            raise ImageError("gpt-image-2 supports quality up to high. Select a 2.5 or 2.6 model for xhigh/max.")
        if output_format not in {"png", "jpeg", "webp"}:
            raise ImageError("Unsupported output format.")
        if background not in {None, "auto", "opaque", "transparent"}:
            raise ImageError("Unsupported background.")
        if background == "transparent" and output_format == "jpeg":
            raise ImageError("This model/format combination cannot preserve transparency. Choose a supported model/format explicitly.")
        if size != "auto":
            match = re.fullmatch(r"([1-9][0-9]{1,4})x([1-9][0-9]{1,4})", size)
            if not match or any(int(v) > 8192 for v in match.groups()):
                raise ImageError("Size must be auto or WIDTHxHEIGHT (up to 8192 per edge); provider enforces model-specific limits.")
            w, h = map(int, match.groups())
            if (image2 or sunburst_or_flare) and (w % 16 or h % 16 or max(w, h) > 3840 or
                                       max(w, h) > 3 * min(w, h) or not 655360 <= w * h <= 8294400):
                raise ImageError("GPT Image 2/2.5/2.6 dimensions must be multiples of 16, max edge 3840, "
                                 "aspect ratio at most 3:1, and total pixels 655360 to 8294400.")
        directory = self.path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        # Check local write access before making a potentially billed request.
        probe = directory / (".write-check-" + uuid.uuid4().hex)
        try:
            with probe.open("xb"):
                pass
            probe.unlink()
        except OSError:
            raise ImageError("Output directory is not writable.") from None
        payload = {"model": model, "prompt": prompt, "size": size, "quality": quality,
                   "output_format": output_format, "n": 1}
        if background:
            payload["background"] = background
        source_paths = []
        if images:
            if not 1 <= len(images) <= 8:
                raise ImageError("Use 1 to 8 reference/edit images.")
            files = []
            first_dimensions = None
            for i, image_path in enumerate(images):
                p = self.path(image_path, must_exist=True)
                if p.stat().st_size > MAX_IMAGE_BYTES:
                    raise ImageError("Input image exceeds 30 MiB.")
                data = p.read_bytes()
                fmt, w, h = image_info(data)
                first_dimensions = first_dimensions or (w, h)
                files.append(("image[]", (f"input-{i}.{fmt}", data, "image/" + fmt)))
                source_paths.append(str(p))
            if mask:
                p = self.path(mask, must_exist=True)
                if p.stat().st_size > MAX_IMAGE_BYTES:
                    raise ImageError("Mask exceeds 30 MiB.")
                data = p.read_bytes()
                fmt, w, h = image_info(data)
                with Image.open(io.BytesIO(data)) as im:
                    has_alpha = "A" in im.getbands() or "transparency" in im.info
                if fmt != "png" or (w, h) != first_dimensions or not has_alpha:
                    raise ImageError("Mask must be a PNG with alpha and the same dimensions as the first input.")
                files.append(("mask", ("mask.png", data, "image/png")))
            result = await self.request("/images/edits", data={k: str(v) for k, v in payload.items()}, files=files)
        else:
            if mask:
                raise ImageError("A mask requires an input image.")
            result = await self.request("/images/generations", json=payload)
        items = result.get("data")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ImageError("Expected exactly one image in provider data; request was not retried.")
        encoded = items[0].get("b64_json")
        if not isinstance(encoded, str):
            raise ImageError("Provider did not return b64_json. URL-only outputs are not downloaded; configure a base64-capable image endpoint.")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ImageError("Provider returned invalid base64 image data.") from None
        fmt, w, h = image_info(image_bytes)
        run = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
        run.mkdir(exist_ok=False)
        output = run / ("image." + fmt)
        with output.open("xb") as f:
            f.write(image_bytes)
        warnings = []
        if size != "auto" and size != f"{w}x{h}":
            warnings.append(f"Provider returned {w}x{h}, different from the requested {size}.")
        if fmt != output_format:
            warnings.append(f"Provider returned {fmt}, different from the requested {output_format}.")
        with Image.open(io.BytesIO(image_bytes)) as im:
            has_transparency = im.convert("RGBA").getchannel("A").getextrema()[0] < 255
        if background == "transparent" and not has_transparency:
            warnings.append("Transparent background was requested, but the saved image has no transparent pixels.")
        metadata = {"path": str(output), "model": model, "model_requested": model,
                    "prompt": prompt, "size_requested": size, "output_format_requested": output_format,
                    "quality_requested": quality, "background_requested": background,
                    "width": w, "height": h, "mime_type": "image/" + fmt, "input_images": source_paths,
                    "has_transparency": has_transparency, "warnings": warnings}
        # No raw response, headers, key, endpoint URL or base64 is written to the sidecar.
        manifest = run / "request.json"
        try:
            manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_path = str(manifest)
        except OSError:
            manifest_path = None
            warnings.append("Image was saved, but writing its request sidecar failed. Do not regenerate it.")
        return {**metadata, "manifest": manifest_path}


def preview(path: str):
    with Image.open(path) as im:
        im.thumbnail((768, 768))
        out = io.BytesIO()
        im.save(out, format="PNG")
        return base64.b64encode(out.getvalue()).decode("ascii")
