# Image API：本地 MCP + Skill

用自己的 OpenAI 兼容图片 API 为 Codex 提供图片生成能力。MCP 负责调用与文件处理，Skill 负责提示词、输入角色、选工具和结果检查。没有修改内置 imagegen，也不依赖其私有接口。

## 工具

| 工具 | 用途 |
| --- | --- |
| `image_status` | 本地配置检查，不联网、不计费 |
| `image_models` | 查询 provider 的模型列表；列表不可用不代表生成不可用 |
| `image_generate` | 一次生成一张图片，返回文件路径、元数据和预览 |
| `image_edit` | 改图、参考图、合成；接受 1–8 张图片和可选 PNG mask |

使用官方 Python MCP SDK 的 STDIO 协议，不启动监听端口。HTTP 层直接调用 `/images/generations` 和 `/images/edits`，减少兼容网关与 SDK 模型枚举之间的耦合。

## 安装

需要 Python 3.11+。在此目录执行（Windows 可把 `python` 替换为 Python 的完整路径）：

```powershell
python scripts/install.py --register
```

安装器把服务放到 `~/Documents/Codex/tools/image-api`，创建独立 `.venv`，安装固定版本的直接依赖，把 MCP 注册到 `~/.codex/config.toml`，并把 Skill 安装到 `~/.codex/skills/image-api`。支持 `CODEX_HOME`。现有配置先在同目录备份；不会修改 provider 或内置 Skill。与现有同名配置冲突时，在复制文件和安装依赖之前停止。同一安装的 Skill 可以随版本升级；独立修改过的 Skill 会保留并报告冲突。更新时保留已有 MCP 的模型及环境配置。

仅准备文件与环境：省略 `--register`。准备好后可用 `--register-only` 完成注册。注册后重启 MCP 或开启新会话，在对话里使用 `$image-api` 或请求通过自己的 API 生成图片。

`.codex-plugin/plugin.json` 提供后续插件打包的元数据；安装器会生成包含本机绝对路径的 `.mcp.json`。当前采用直接注册 MCP + Skill，不需要 marketplace。源码 ZIP 中的 `.mcp.json` 是空配置，接收方运行安装器后才生成自己的路径。使用 `python scripts/package.py` 打包会强制排除本机 MCP 配置、虚拟环境和字节码；不要直接压缩安装目录。

## Image 2.6

从 0.1.3 起，新安装默认使用 `gpt-image-2.6-flare`。Skill 为日常生成和草稿选择 Flare，为精细编辑、身份或版式保留、复杂成品细节选择 `gpt-image-2.6-sunburst`。明确指定的 `model` 优先，并可继续选择 2.5。服务商必须开放相应模型。

> 使用 $image-api，用 gpt-image-2.6-flare 生成一张低质量草稿。

两个 2.6 模型支持 `low`、`medium`、`high`、`xhigh`、`max`、`auto`。本服务支持 PNG、JPEG、WebP，PNG 和 WebP 可请求透明背景。Image 2、2.5 和 2.6 的尺寸要求为两边均为 16 的倍数、最长边不超过 3840、比例不超过 3:1、总像素在 655360–8294400 之间。[OpenAI 图片生成指南](https://developers.openai.com/api/docs/guides/image-generation)

升级会保留 `config.toml` 中已有的 `IMAGEGEN_MODEL`。若要更新直接调用时的默认值，在 `[mcp_servers.image_api.env]` 下删除旧的 `IMAGEGEN_MODEL` 以使用服务的内置默认值，或将它设为所需的 2.6 模型，然后重启 Codex。

## Codex 要求明确授权时

`image_status` 只检查本地配置。`image_models` 会向配置的服务商发出已认证的查询。`image_generate` 会发送提示词并保存新文件，`image_edit` 还会上传选定原图和蒙版。两项图片操作均可能计费。

若 Codex 提示 `Requires explicit authorization because this action is considered high risk`，确认服务商、操作及拟上传的文件后，在该会话使用 `/approve`；如果界面提供审批卡片，也可在那里确认。`/approve` 授权针对该被拒操作的一次重试，仍受审批策略约束。也可在发起新请求时明确写出授权范围，例如“我授权使用已配置的 API 服务商，用 Image 2.6 Flare 按下述提示生成一张图，并接受一次 API 调用的费用”。编辑时同时指明允许上传的文件。[Codex 自动审批](https://learn.chatgpt.com/docs/sandboxing/auto-review)

## 配置与凭据

服务在每次调用时读取配置，工具参数没有 API key 字段：

- 默认地址：用户级 Codex 配置所选 provider 的 `base_url`，包含所选 profile。
- 密钥优先级：`IMAGEGEN_API_KEY` → provider 的 `env_key`（未指定时为 `OPENAI_API_KEY`）→ `auth.json` 的 `OPENAI_API_KEY`。明确配置了 `env_key` 但缺少该变量时，不借用其他凭据。
- `IMAGEGEN_MODEL`：省略工具 `model` 参数时使用的默认值，未配置时用 `gpt-image-2.6-flare`。显式 `model` 优先。
- `IMAGEGEN_BASE_URL`：覆盖地址。地址与原 provider 不同时，必须同时设置独立的 `IMAGEGEN_API_KEY`，不转发旧 provider 的密钥或 headers。
- `IMAGEGEN_CODEX_PROFILE`：支持旧式用户配置中的 `[profiles.<name>]`。尚不合并新版 CLI 的 `<name>.config.toml` profile 文件、项目级配置或 CLI 临时覆盖。
- `IMAGEGEN_ALLOWED_ROOTS`：可读写的绝对路径根目录，Windows 用分号分隔，其他系统用冒号分隔；默认仅 `~/Documents/Codex`。此配置不是操作系统沙箱，建议只填写工作目录。

服务支持 provider 的固定及环境变量 HTTP headers；不会把 ChatGPT 登录会话 token 当作 API key。更换网关请显式配置地址和匹配密钥。

## 结果与错误

每次输出保存在唯一子目录，包含原始 `image.png/jpeg/webp` 和 `request.json`。后者记录提示词、请求模型、请求尺寸、实际尺寸与输入图片路径；不存密钥、headers 或完整响应。`model_requested` 和兼容字段 `model` 均表示发送的模型名，不是对网关上游路由的独立验证。MCP 内联返回最长边 768px 的 PNG 预览，磁盘保留原图。结果 `warnings` 会提示尺寸/格式不匹配或透明背景未生效；如果图片已保存而 sidecar 写入失败，仍会返回图片路径。

只接受 `b64_json` 图片响应，不下载 provider 返回的任意 URL。输入限 PNG/JPEG/WebP，每张最多 30 MiB，最多 4000 万像素；mask 必须有 alpha 并与第一张图同尺寸。每次生成一张，批量由调用方按明确请求逐次执行。

API 请求总时限 240 秒，MCP 超时 300 秒；无自动重试、无静默切换 endpoint/model。总时限也覆盖持续缓慢传输的响应。超时并不说明服务端没有处理或计费。HTTP 错误只返回状态码，不回显可能包含密钥的服务端正文。

## 验证

```powershell
python -m unittest discover -s tests -v
python scripts/smoke.py status
# 下面两项会访问配置中的 API；generate 可能计费。
python scripts/smoke.py models
python scripts/smoke.py generate --output-dir C:/absolute/workspace/outputs/images --model gpt-image-2.6-flare
```

2026-09-28 二次审查：17 项离线测试通过，覆盖真实 STDIO MCP 握手、两个 2.5 模型及日期快照的六档质量参数、改图请求、尺寸校验、总超时、凭据隔离、错误脱敏、sidecar 失败保留图片，以及安装冲突和升级。

通过已安装 MCP 的 `image_generate` 各调用一次：`gpt-image-2.5-flare` 29.61 秒、`gpt-image-2.5-sunburst` 29.31 秒，均成功返回 PNG、元数据与预览。测试参数 `quality=low`、`size=1024x1024`；第三方网关均返回 1254×1254，故不能认定尺寸参数被严格遵守，也不能独立证明网关实际路由到了相应上游模型。两张文件的 SHA-256 不同。此前 `gpt-image-2` 的真实生成也已成功。真实改图、透明背景和高质量档尚未在线验证。

2026-10-21 默认模型修正：20 项测试通过，包括省略模型时实际发送 Flare、显式 Sunburst/Image 2 优先、新安装注册 Flare，以及 Image 2 透明背景预览参数可传递（JPEG 仍拒绝透明）。本次未重复进行计费生成；上述真实生成结果属于 2026-09-28 的历史验证。

## 设计边界

这提供可调用的替代工具，不会给当前会话注入私有的 `image_gen` 名称，也不会完全复刻内置图片生成界面。是否暴露内置工具不能仅凭 API 模式判断。当前实现专注 Images API；如果其他网关仅支持 Responses API 的 image_generation，应新增独立适配器，而不是失败后自动发起另一笔生成请求。

撤销注册可运行 `codex mcp remove image_api`，并移除用户 Skill 目录中的 `image-api`。服务目录可以保留，不影响其他插件。

参考：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[OpenAI 图片生成 API](https://developers.openai.com/api/docs/guides/image-generation)。
