# NTAPI ComfyUI 节点组设计

## 背景与目标

在 `custom_nodes` 下新增独立的 `ComfyUI-NTAPI` 节点组，提供中文工作流界面，调用 NTAPI 的 OpenAI 兼容接口和 Gemini 原生图片接口。成功标准是插件能被 ComfyUI 注册，语言节点能解析聊天文本，两个生图节点能把 URL 或 Base64 图片返回为 `IMAGE`。

## 现状与约束

- 插件在独立目录中实现，不更改其他节点组。
- NTAPI 文档公开了 `/v1/chat/completions`、`/v1/images/generations` 和 `/v1beta/models/{model}:generateContent`。
- NTAPI 首页与模型示例使用了不同的域名形式，因此节点提供可编辑的接口地址，默认使用官网模型示例中的 `https://ntapi.org/v1`。
- NTAPI 尚未公开稳定的视频提交/查询协议，本次不实现视频节点。

## 方案对比

### 方案一：实现完整多模型节点组

- 优点：覆盖文本、图片和视频工作流。
- 缺点：需要尚未公开的异步任务与视频接口协议。

### 方案二：按 NTAPI 公开协议实现三类同步节点（推荐）

- 优点：改动小，协议边界清楚，能覆盖语言、GPT 生图和 Gemini 生图。
- 缺点：视频和未公开的高级异步能力暂不包含。

## 推荐方案

新增 `NTAPI语言模型`、`NTAPI GPT生图`、`NTAPI Gemini生图` 三个节点。三个节点共享 API Key、Base URL、错误格式化和图片转换逻辑，但不引入跨插件依赖。

## 详细设计

### 架构

`__init__.py` 只暴露节点映射；`nodes.py` 包含三个节点和本插件私有的 HTTP/编码辅助函数。默认请求使用 Bearer Token，提供“绕过代理”开关以适配不同本地网络环境。

### 数据流 / 接口

- 语言：`POST {base_url}/chat/completions`，发送 `messages`，支持最多 4 个可选参考图的 OpenAI 多模态内容。
- GPT 生图：无参考图时发送 JSON 到 `{base_url}/images/generations`；有参考图时发送 multipart 到 `{base_url}/images/edits`。解析 `data[].url`、`data[].b64_json`，不扫描无关元数据 URL。
- Gemini 生图：从 Base URL 推导站点根地址，发送 `POST {origin}/v1beta/models/{model}:generateContent`，使用 `contents.parts` 和 `generationConfig.imageConfig`；解析 `inlineData`、`fileData` 和文本中的 Markdown 图片链接。

### 异常与边界处理

发布整理后：API Key 缺失、HTTP 非 2xx、非 JSON、图片下载/解码失败和无法识别的响应都使节点明确报错，不输出占位图或原始上游错误正文。支持环境变量密钥；仅同源图片请求发送密钥，不自动重试或跟随重定向。参考图只在执行节点时编码，每个批次逐帧处理。

### 测试策略

使用本地 `http.server` 模拟三个端点，验证请求路径、鉴权头、请求体、URL 图片和 Base64 图片解析；再用 ComfyUI 内置 Python 检查依赖、节点注册和语法。

## 风险与待确认项

NTAPI 的生产域名和部分图片字段仍可能变化；用户可通过 Base URL 覆盖默认地址。视频模型只有模型目录信息，没有稳定任务协议，待 NTAPI 公布接口后另行增加。
