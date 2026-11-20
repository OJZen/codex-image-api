# Codex Image API

[简体中文](README.zh-CN.md)

Generate and edit images in Codex with GPT Image 2.6 through your own OpenAI-compatible Images API. The local MCP server saves each image to a new folder and returns a preview.

## Install

Requires Codex, Python 3.11+, and an Images API key. Run the following from the repository root.

```shell
python scripts/install.py --register
```

The installer sets up an isolated Python environment and registers the `image_api` MCP server and `$image-api` skill. Restart Codex to load them.

## Configure

The server reuses the API URL and key from your user-level Codex provider configuration when available. To use a separate key, set `IMAGEGEN_API_KEY` in the MCP server environment. If you change the endpoint with `IMAGEGEN_BASE_URL`, also supply the matching key.

- `IMAGEGEN_MODEL` sets the default for tool calls that omit `model`. It defaults to `gpt-image-2.6-flare`. To update an older installation, update or remove any old model override under `[mcp_servers.image_api.env]` and restart Codex.
- `IMAGEGEN_ALLOWED_ROOTS` limits where the server reads and writes images. It defaults to `~/Documents/Codex`. Set it to the absolute paths of your workspaces if they live elsewhere.

## Use

> $image-api Generate a square illustration of a ceramic cup on a cream background.

The skill picks Flare for general generation and Sunburst for precise edits. You can specify either model directly. For edits, attach an image or provide its path and say what to change and preserve.

`image_status` checks local configuration offline. Generation sends your prompt to the provider and may incur charges. Editing also uploads the selected images and any mask. If Codex requests explicit authorization, review the action and confirm it through the available approval flow. [Codex Auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review)
