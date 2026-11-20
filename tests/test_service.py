import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from image_service import ImageError, ImageService, Settings


def png():
    b = io.BytesIO()
    Image.new("RGBA", (32, 32), (0, 128, 128, 255)).save(b, "PNG")
    return b.getvalue()


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.settings = Settings("https://example.test/v1", "secret-for-test", roots=(self.root,))

    def tearDown(self):
        self.tmp.cleanup()

    async def test_generate_and_unique_outputs(self):
        seen = []
        def handler(request):
            seen.append(request)
            self.assertEqual(request.headers["authorization"], "Bearer secret-for-test")
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        service = ImageService(self.settings, httpx.MockTransport(handler))
        a = await service.create("tea", str(self.root))
        b = await service.create("tea", str(self.root))
        self.assertNotEqual(a["path"], b["path"])
        self.assertEqual(Path(a["path"]).read_bytes(), png())
        self.assertNotIn("secret-for-test", Path(a["manifest"]).read_text())
        self.assertEqual(seen[0].url.path, "/v1/images/generations")
        self.assertEqual(json.loads(seen[0].content)["n"], 1)

    async def test_default_flare_and_explicit_model_override_reach_provider(self):
        observed = []
        def handler(request):
            observed.append(json.loads(request.content)["model"])
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        self.assertEqual(Settings.load({}, self.root).model, "gpt-image-2.6-flare")
        self.assertEqual(Settings.load({"IMAGEGEN_MODEL": "gpt-image-2.5-sunburst"}, self.root).model,
                         "gpt-image-2.5-sunburst")
        service = ImageService(self.settings, httpx.MockTransport(handler))
        await service.create("tea", str(self.root))
        await service.create("tea", str(self.root), model="gpt-image-2.6-sunburst")
        await service.create("tea", str(self.root), model="gpt-image-2")
        self.assertEqual(observed, ["gpt-image-2.6-flare", "gpt-image-2.6-sunburst", "gpt-image-2"])

    async def test_image2_transparency_preview_is_forwarded(self):
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-image-2")
            self.assertEqual(payload["background"], "transparent")
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        service = ImageService(self.settings, httpx.MockTransport(handler))
        result = await service.create("tea", str(self.root), model="gpt-image-2", background="transparent")
        self.assertFalse(result["has_transparency"])
        self.assertTrue(any("transparent" in message for message in result["warnings"]))

    async def test_edit_uploads_input_and_mask_without_changing_original(self):
        source, mask = self.root / "source.png", self.root / "mask.png"
        source.write_bytes(png()); mask.write_bytes(png())
        def handler(request):
            self.assertEqual(request.url.path, "/v1/images/edits")
            self.assertIn(b'name="image[]"', request.content)
            self.assertIn(b'name="mask"', request.content)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        service = ImageService(self.settings, httpx.MockTransport(handler))
        await service.create("change background", str(self.root), images=[str(source)], mask=str(mask))
        self.assertEqual(source.read_bytes(), png())

    async def test_errors_do_not_echo_provider_secrets_or_retry(self):
        count = 0
        def handler(request):
            nonlocal count
            count += 1
            return httpx.Response(403, text="credential secret-for-test; echoed prompt")
        service = ImageService(self.settings, httpx.MockTransport(handler))
        with self.assertRaises(ImageError) as cm:
            await service.create("tea", str(self.root))
        self.assertNotIn("secret-for-test", str(cm.exception))
        self.assertIn("403", str(cm.exception))
        self.assertEqual(count, 1)

    async def test_timeout_not_retried(self):
        count = 0
        def handler(request):
            nonlocal count
            count += 1
            raise httpx.ReadTimeout("secret-for-test", request=request)
        service = ImageService(self.settings, httpx.MockTransport(handler))
        with self.assertRaisesRegex(ImageError, "may have been billed"):
            await service.create("tea", str(self.root))
        self.assertEqual(count, 1)

    async def test_total_deadline_bounds_slow_stream(self):
        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(100):
                    await asyncio.sleep(0.01)
                    yield b" "
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, stream=SlowStream())
        service = ImageService(self.settings, httpx.MockTransport(handler), request_timeout=0.04)
        async with asyncio.timeout(1):
            with self.assertRaisesRegex(ImageError, "may have been billed"):
                await service.create("tea", str(self.root))
        self.assertEqual(len(seen), 1)

    async def test_flare_and_sunburst_quality_and_model_are_preserved(self):
        observed = []
        def handler(request):
            observed.append(json.loads(request.content))
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        service = ImageService(self.settings, httpx.MockTransport(handler))
        for model in ["gpt-image-2.6-flare", "gpt-image-2.6-sunburst", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
                      "gpt-image-2.5-flare-2026-09-08", "gpt-image-2.5-sunburst-2026-09-08"]:
            for quality in ["low", "medium", "high", "xhigh", "max", "auto"]:
                with self.subTest(model=model, quality=quality):
                    result = await service.create("tea", str(self.root), model=model, quality=quality,
                                                  background="transparent")
                    self.assertEqual(observed[-1]["model"], model)
                    self.assertEqual(observed[-1]["quality"], quality)
                    self.assertNotIn("input_fidelity", observed[-1])
                    self.assertEqual(result["model_requested"], model)
                    self.assertTrue(any("transparent" in warning for warning in result["warnings"]))

    async def test_flare_and_sunburst_edit_model_parameters(self):
        source = self.root / "source.png"
        source.write_bytes(png())
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        service = ImageService(self.settings, httpx.MockTransport(handler))
        for model in ["gpt-image-2.6-flare", "gpt-image-2.6-sunburst", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]:
            await service.create("tea", str(self.root), model=model, quality="xhigh", images=[str(source)])
            self.assertEqual(seen[-1].url.path, "/v1/images/edits")
            self.assertIn(model.encode(), seen[-1].content)
            self.assertIn(b'xhigh', seen[-1].content)
            self.assertNotIn(b'input_fidelity', seen[-1].content)

    async def test_known_model_invalid_dimensions_rejected_without_network(self):
        def handler(request):
            self.fail("Invalid parameters must not reach the provider")
        service = ImageService(self.settings, httpx.MockTransport(handler))
        for model in ["gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2.6-flare", "gpt-image-2.6-sunburst"]:
            for size in ["1025x1024", "4096x2048", "512x512", "3840x512", "3840x3840"]:
                with self.subTest(model=model, size=size), self.assertRaises(ImageError):
                    await service.create("tea", str(self.root), model=model, size=size)
        with self.assertRaises(ImageError):
            await service.create("tea", str(self.root), model="gpt-image-2", quality="max")

    async def test_format_size_mismatch_and_sidecar_failure_keep_saved_image(self):
        service = ImageService(self.settings, httpx.MockTransport(lambda r: httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})))
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = await service.create("tea", str(self.root), output_format="jpeg")
        self.assertIsNone(result["manifest"])
        self.assertEqual(Path(result["path"]).read_bytes(), png())
        self.assertTrue(any("32x32" in x for x in result["warnings"]))
        self.assertTrue(any("jpeg" in x for x in result["warnings"]))
        self.assertTrue(any("sidecar" in x for x in result["warnings"]))

    async def test_path_escape_and_relative_paths_rejected_before_request(self):
        service = ImageService(self.settings)
        for path in ["relative", str(self.root / ".." / "escape")]:
            with self.assertRaises(ImageError):
                await service.create("tea", path)

    async def test_url_output_not_fetched(self):
        service = ImageService(self.settings, httpx.MockTransport(lambda r: httpx.Response(
            200, json={"data": [{"url": "http://127.0.0.1/private"}]})))
        with self.assertRaisesRegex(ImageError, "URL-only"):
            await service.create("tea", str(self.root))

    async def test_invalid_image_and_transparency_rejected(self):
        service = ImageService(self.settings, httpx.MockTransport(lambda r: httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]})))
        with self.assertRaises(ImageError):
            await service.create("tea", str(self.root))
        with self.assertRaisesRegex(ImageError, "transparency"):
            await service.create("tea", str(self.root), background="transparent", output_format="jpeg")

    def test_configuration_profile_and_no_credential_reuse_for_override(self):
        codex = self.root / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text('model_provider="a"\nprofile="selected"\n'
            '[profiles.selected]\nmodel_provider="b"\n[model_providers.b]\n'
            'base_url="https://provider.test/v1"\nenv_key="PROVIDER_KEY"\n')
        (codex / "auth.json").write_text('{"OPENAI_API_KEY":"not-selected"}')
        s = Settings.load({"PROVIDER_KEY": "selected"}, self.root)
        self.assertEqual(s.key, "selected")
        self.assertEqual(s.base_url, "https://provider.test/v1")
        self.assertFalse(Settings.load({}, self.root).key)
        with self.assertRaises(ImageError):
            Settings.load({"IMAGEGEN_BASE_URL": "https://elsewhere.test/v1"}, self.root)
        s = Settings.load({"IMAGEGEN_BASE_URL": "https://elsewhere.test/v1", "IMAGEGEN_API_KEY": "new"}, self.root)
        self.assertEqual(s.key, "new")
        self.assertEqual(s.headers, {})

    async def test_stdio_handshake_and_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        server_path = Path(__file__).resolve().parents[1] / "scripts" / "server.py"
        env = {**os.environ, "CODEX_HOME": str(self.root / "empty-codex"),
               "IMAGEGEN_ALLOWED_ROOTS": str(self.root)}
        env.pop("IMAGEGEN_MODEL", None)
        params = StdioServerParameters(command=sys.executable, args=[str(server_path)], env=env)
        async with asyncio.timeout(30):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    annotations = {t.name: t.annotations for t in tools.tools}
                    self.assertEqual(set(annotations), {"image_status", "image_models", "image_generate", "image_edit"})
                    self.assertFalse(annotations["image_status"].openWorldHint)
                    self.assertTrue(annotations["image_status"].readOnlyHint)
                    for name in ("image_generate", "image_edit"):
                        self.assertTrue(annotations[name].openWorldHint)
                        self.assertFalse(annotations[name].readOnlyHint)
                    result = await session.call_tool("image_status", {})
                    self.assertFalse(result.isError)
                    self.assertFalse(result.structuredContent["online_verified"])
                    self.assertEqual(result.structuredContent["model"], "gpt-image-2.6-flare")


if __name__ == "__main__":
    unittest.main()
