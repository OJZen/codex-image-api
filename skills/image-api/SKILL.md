---
name: image-api
description: Generate or edit raster images with GPT Image 2.6 through the local image-api MCP service. Use for Flare or Sunburst requests, the user's configured Image API workflow, or when image_gen is unavailable. Supports reference images and PNG masks.
---

# Image API

Use the `image-api` MCP tools for this user's API-based image workflow. Select the image model through the MCP `model` argument. Use the MCP when the user requests an exact model that the built-in tool cannot select.

- Discover `image_status`, `image_generate`, `image_edit`, and optionally `image_models` in the available tool namespace. Tool prefixes can differ by host. If unavailable, report that the MCP must be enabled/restarted; do not invent a successful call.
- `image_status` checks local configuration without network activity. `image_models` is a read-only provider request, but a missing model list does not establish that generation is unavailable.
- Preserve the user's explicit model or model preference. Otherwise choose `gpt-image-2.6-flare` for general generation and drafts, or `gpt-image-2.6-sunburst` for precision edits, identity/layout preservation, or demanding final detail. Pass the exact ID in `model`. If the user asks for the server's configured default, read it from `image_status`.
- Both 2.6 models support `low`, `medium`, `high`, `xhigh`, `max`, and `auto`. Omit `input_fidelity`. If the configured provider rejects a model, report the rejection and keep the user's model choice.
- Use `image_generate` for text-only creation. For reference images, edits, compositing or masks use `image_edit`; its Images API route accepts local files. Inspect inputs first, identify their roles and state invariants in the prompt.
- Pass absolute image paths and an absolute output directory within the current workspace (normally `outputs/images`). Input files must be inside the server's allowed roots; copy user-provided assets into the workspace when needed. The server creates a unique subdirectory and preserves originals.
- Keep prompts faithful: subject, style, composition, exact quoted text, and constraints. Avoid adding unrequested branding or scene elements. Make one image by default; additional variants should follow the user's request.
- The configured provider receives the prompt and, for edits, the selected input images or mask. Each generation/edit may be billed. If Codex says explicit authorization is required, identify the provider, intended operation, and files to upload, then wait for authorization via the host's approval flow. Never work around a denial with shell commands or a different tool. After a timeout or transport error, report the uncertain result and seek authorization before repeating a potentially billed call.
- Inspect the returned preview for prompt compliance. Display the saved image using Markdown with its absolute path. State that the configured Image API was used and link the result. The sidecar records the actual prompt and requested parameters.
- Read result `warnings`: the provider may return a different size/format or ignore transparency. Report any material mismatch; do not silently resize or regenerate. `model_requested` identifies what was sent to the provider, not independent proof of the gateway's upstream model.
- Credentials are resolved inside the service from local environment/Codex configuration. Never paste keys into tool arguments, prompts, configuration examples or logs.

For transparent output use a compatible model with PNG or WebP, then check `has_transparency` and `warnings`. Generative editing can change pixels outside the requested area.
