# ComfyUI-NTAPI

在 ComfyUI 中调用 NTAPI 的语言、GPT 图片与 Gemini 图片接口。中文参数、参考图输入，可自定义模型与接入地址。

**状态：`0.1.0a1` 公开预览版。** 已通过本地模拟测试；尚未用真实 NTAPI 密钥验证生产调用。模型下拉框是公开模型目录的快照，不代表账户拥有权限或接口已可用。本插件并非 NTAPI 官方产品。

![节点连接示意（非运行截图）](docs/images/connections.svg)

## 节点与接口

| 节点 | 功能 | 路径 | 输出 |
| --- | --- | --- | --- |
| NTAPI-语言模型 | 文字与参考图理解 | `/v1/chat/completions` | STRING |
| NTAPI-GPT生图 | 文生图、参考图编辑 | `/v1/images/generations` / `/v1/images/edits` | IMAGE |
| NTAPI-Gemini生图 | Gemini 原生生图 | `/v1beta/models/{model}:generateContent` | IMAGE、结果格式 |

语言节点保留 4 个参考图插槽，图片节点保留 14 个插槽，以兼容早期本地工作流；每个插槽的 IMAGE 批次会逐张发送，不截断批次。参考图按原尺寸编码为 RGB JPEG（质量 100），透明通道不会传递。上游图片数量限制以服务为准。

## 安装

环境需要 ComfyUI、Python 3.10+ 和 ComfyUI 已安装的 PyTorch。本插件不更改 CUDA/PyTorch 环境。

1. 下载本仓库源码，将包含 `__init__.py` 的目录命名为 `ComfyUI-NTAPI`，放入 `ComfyUI/custom_nodes/`，避免多套一层目录。
2. 在本插件目录，使用 **ComfyUI 所使用的 Python 环境**执行 `python -m pip install -r requirements.txt`。
3. 重启 ComfyUI，双击画布搜索 `NTAPI`，节点分类为 `NTAPI中转`。

也可以在 `ComfyUI/custom_nodes/` 目录克隆安装：

```text
git clone https://github.com/nantian555/ComfyUI-NTAPI.git
```

Windows portable 用户也可以在便携版根目录执行：

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\ComfyUI-NTAPI\requirements.txt
```

## 密钥和地址

推荐在启动 ComfyUI 的进程环境中设置 `NTAPI_API_KEY`，并将节点的“API密钥”留空。也支持在节点内填写密钥；显式填写优先于环境变量。

**节点内填写的密钥可能保存在工作流 JSON、历史记录和输出图片的工作流元数据中。** 分享前请清空密钥；已经泄露的密钥应在服务控制台撤销。`.gitignore` 不能自动清除已写入工作流的密钥。本插件不自动读取 `.env` 文件。

语言/GPT 默认接入地址为 `https://ntapi.org/v1`；Gemini 的默认根地址为 `https://ntapi.org`。这是模型广场调用示例中的地址。首页另有 `https://api.ntapi.org/v1` 示例，请以账户控制台给出的有效地址为准，在节点中覆盖；插件不会自动切换域名。Gemini 根地址末尾的 `/v1` 或 `/v1beta` 会自动去除。

远程携带密钥的请求必须使用 HTTPS；允许 localhost HTTP 用于本地测试。图片下载只对同源地址（协议、主机、端口均相同）发送密钥。请求不跟随重定向；请填写最终接口或图片直链。

“绕过代理”为真时禁用 Requests 的环境代理与 `.netrc` 自动认证（`trust_env=False`）；也不使用 `REQUESTS_CA_BUNDLE` 等环境配置，使用默认 CA 校验。关闭该选项时遵循系统/环境代理设置。TLS 验证始终启用。

## 使用与示例

将 [GPT 文生图工作流](examples/gpt-image.workflow.json) 或 [Gemini 文生图工作流](examples/gemini-image.workflow.json) 拖入 ComfyUI，再设置密钥或启动环境变量。两个工作流均连接原生 `SaveImage`，不包含密钥或生成图片。

- 语言节点：填写用户提示词，可连接参考图，STRING 输出接文本显示或后续处理节点。
- GPT 生图：未连接参考图时文生图，连接参考图时使用 multipart 编辑接口。“服务默认”表示省略该字段；质量、风格、返回格式仅在显式选择时发送。
- GPT 各模型允许的质量/尺寸尚未实测。`standard`、`vivid`、`natural` 是兼容接口选项，不保证 GPT-image 模型支持；风格通常用于 DALL·E 3，自定义该模型时再按服务文档选择。旧工作流保存的显式选项会继续发送，可手动改成“服务默认”。
- Gemini “自动”比例表示交由服务决定。种子 0 不发送，正数发送；服务是否支持可复现以模型为准。
- 生图返回 URL、Base64 或 Gemini inlineData/fileData；图片批次尺寸不一致时，后续图片缩放至首张尺寸以组成 ComfyUI IMAGE 批次。输出为 RGB，无 MASK/透明通道。

## 错误与限制

- HTTP 错误、非 JSON、空图片、解码失败和超时会使节点明确报错，避免把失败当作有效图片/文本继续执行。
- 不输出密钥、提示词或上游原始错误正文；HTTP 状态保留在错误消息中，详细原因请在 NTAPI 控制台查看。
- 本版只处理同步结果。收到异步任务会提示查询服务控制台，不会猜测任务查询端点或自动重试。超时不表示服务端未受理，请检查任务后再决定重跑，以免重复计费。
- 不包含视频、后台任务队列、遥测或启动时联网检查。只有执行节点时才发送请求；参考图片会上传到配置的服务。
- 同一输入可能被 ComfyUI 缓存；需要新结果时修改实际参数/提示词，或按 ComfyUI 的缓存设置操作。

## 测试

在本目录使用 ComfyUI 的 Python 执行：

```text
python -m unittest discover -s tests -v
```

测试使用 mock 和本地 HTTP 服务，覆盖 JSON/multipart、批次、鉴权、代理、HTTP/超时/坏响应、图片下载和密钥隐藏，不需要真实密钥，不产生模型费用。GitHub Actions 提供 Linux Python 3.10/3.13 测试，云端结果见 [Actions](https://github.com/nantian555/ComfyUI-NTAPI/actions)。

## 发布

发布前查看 [发布说明与检查步骤](docs/RELEASING.md) 和 [更新记录](CHANGELOG.md)。当前建议作为 Pre-release 发布，并保留“生产接口尚未验证”的说明。GitHub 发布不等于 ComfyUI Registry/Manager 上架。

## 许可证

[MIT License](LICENSE)，版权和来源声明见 [NOTICE.md](NOTICE.md)。接口依据：[NTAPI 模型广场](https://ntapi.org/pricing)、[New API 图片接口](https://docs.newapi.pro/zh/docs/api/ai-model/images/openai/post-v1-images-generations)、[Gemini 原生图片接口](https://docs.newapi.pro/zh/docs/api/ai-model/images/gemini/geminirelayv1beta-383837589)（2026-10-05 查阅）。
