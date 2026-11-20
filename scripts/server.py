"""STDIO MCP entrypoint; protocol is implemented by the official Python SDK."""
import asyncio
import json

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from image_service import DEFAULT_MODEL, ImageError, ImageService, Settings, preview

mcp = FastMCP("image-api", instructions=(
    "Generate and edit raster images with the configured Image API. Prompts and selected edit images "
    "are sent to that provider. The API key is used for provider authentication and never enters tool arguments or results. "
    f"Default: {DEFAULT_MODEL}. Select gpt-image-2.6-sunburst for precision edits. "
    "Pass the chosen model explicitly and preserve the user's model choice. "
    "Pass an absolute output_dir in the current workspace and absolute input paths for edits. "
    "Each generation/edit can incur a charge. Respect Codex approval decisions and never automatically retry. "
    "Inspect the returned image and display its saved local path. Never silently change models."
), log_level="ERROR")


def text_result(data, error=False):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
                          isError=error, structuredContent=data)


async def invoke(action, **kwargs):
    try:
        service = ImageService(Settings.load())
        if action == "status":
            return text_result(service.status())
        if action == "models":
            return text_result(await service.models())
        result = await service.create(**kwargs)
        response = text_result(result)
        try:
            thumbnail = await asyncio.to_thread(preview, result["path"])
            response.content.append(ImageContent(type="image", data=thumbnail, mimeType="image/png"))
        except Exception:
            response.content.append(TextContent(type="text", text="Image saved; inline preview unavailable. Open the returned path."))
        return response
    except ImageError as e:
        return text_result({"error": str(e)}, error=True)
    except Exception:
        return text_result({"error": "Local image operation failed. Inspect local paths/dependencies; details withheld to protect credentials. No automatic retry."}, error=True)


READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


@mcp.tool(annotations=READ)
async def image_status() -> CallToolResult:
    """Check local credential availability, model and allowed paths. No network or billed request."""
    return await invoke("status")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def image_models() -> CallToolResult:
    """Send an authenticated GET to the configured provider's /models endpoint. Does not send prompts or images."""
    return await invoke("models")


@mcp.tool(annotations=WRITE)
async def image_generate(prompt: str, output_dir: str, model: str | None = None,
                         size: str = "1024x1024", quality: str = "auto",
                         background: str | None = None, output_format: str = "png") -> CallToolResult:
    """Generate one raster image; return a saved absolute path, request sidecar and inline preview.

    output_dir must be in the current workspace's outputs directory and allowed by server configuration.
    Pass gpt-image-2.6-flare for general work or gpt-image-2.6-sunburst for demanding detail.
    If omitted, IMAGEGEN_MODEL applies. User choice takes priority.
    Sends the prompt to the configured provider in one potentially billed request and saves a new local file.
    """
    return await invoke("create", prompt=prompt, output_dir=output_dir, model=model, size=size,
                        quality=quality, background=background, output_format=output_format)


@mcp.tool(annotations=WRITE)
async def image_edit(prompt: str, images: list[str], output_dir: str, mask: str | None = None,
                     model: str | None = None, size: str = "1024x1024", quality: str = "auto",
                     background: str | None = None, output_format: str = "png") -> CallToolResult:
    """Edit/composite using 1-8 absolute local image paths, or generate with reference images.

    Describe each image's role and what must stay unchanged. Optional transparent PNG mask applies
    to the first image and must have matching dimensions. Always saves a new file, preserving inputs.
    Prefer gpt-image-2.6-sunburst for precision edits unless the user chose another.
    Sends the prompt and selected input images or mask to the configured provider in one potentially billed request.
    """
    if not images:
        return text_result({"error": "image_edit requires at least one input image."}, error=True)
    return await invoke("create", prompt=prompt, images=images, output_dir=output_dir, mask=mask,
                        model=model, size=size, quality=quality, background=background, output_format=output_format)


if __name__ == "__main__":
    mcp.run(transport="stdio")
