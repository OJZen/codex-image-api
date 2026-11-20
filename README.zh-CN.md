# Codex Image API

[English](README.md)

通过自己的 OpenAI 兼容 Images API，在 Codex 中使用 GPT Image 2.6 生成和编辑图片。本地 MCP 服务会把每张图保存到新目录，并返回预览。

## 安装

需要 Codex、Python 3.11+ 和 Images API 密钥。在仓库根目录运行以下命令。

```shell
python scripts/install.py --register
```

安装器会创建独立的 Python 环境，注册 `image_api` MCP 服务和 `$image-api` Skill。完成后重启 Codex。

## 配置

服务会尝试复用用户级 Codex 服务商配置中的 API 地址和密钥。也可以在 MCP 服务的环境变量中设置 `IMAGEGEN_API_KEY`。使用 `IMAGEGEN_BASE_URL` 更换服务地址时，请同时提供对应的密钥。

- `IMAGEGEN_MODEL` 设置调用未指定 `model` 时的默认模型，内置默认值为 `gpt-image-2.6-flare`。升级旧安装时，可在 `[mcp_servers.image_api.env]` 中更新或删除旧的模型设置，然后重启 Codex。
- `IMAGEGEN_ALLOWED_ROOTS` 限制图片读写目录，默认是 `~/Documents/Codex`。如果工作区在其他位置，请设置相应的绝对路径。

## 用法

> $image-api 生成一张正方形插画，画一个放在奶油色背景上的陶瓷杯。

Skill 一般用 Flare 生成图片，用 Sunburst 做精细编辑。也可以直接指定模型。修改图片时，附上原图或提供路径，并说明要改什么、保留什么。

`image_status` 可离线检查本机配置。生成会向服务商发送提示词，可能产生费用。编辑还会上传选定的原图和蒙版（如果提供）。若 Codex 要求明确授权，请核对操作后通过界面提供的流程确认。[Codex 自动审批说明](https://learn.chatgpt.com/docs/sandboxing/auto-review)
