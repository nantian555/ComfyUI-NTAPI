# Changelog

## Unreleased

- Gemini 生图模型菜单改为 NanobananaPro、Nanobanana2.1、Nanobanana2，增加 gemini-nano-banana-2.1 映射并迁移旧显示值。
- 简化 Seedance 2.5 模型菜单为 `seedance2.5t2v`、`seedance2.5i2v`、`seedance2.5multi`；兼容旧 standard/global 工作流值。

## 0.2.0a1 — 2026-10-06（本地预览）

- 修复 Seedance 请求路径：两套生成/查询均使用 NTAPI 实际开放的 `/v1/videos`，上传统一使用 `/v1/files`；移除返回网页/404 的参考供应商专用路径。
- Seedance 网络错误改为分别提示超时、代理、TLS、连接失败及非 JSON 接口错误，不显示密钥或原始响应正文。
- Seedance 2.0/2.5 参考模型按档位和模式映射为 NTAPI 的 `Svideo-*` 模型 ID；自定义模型保持原样。移除会因网络超时阻断生成的额外 `/v1/models` 预检。
- Svideo 请求改为 NTAPI 模型详情公开的 `model + messages` openai-video 结构，并保留 seconds/metadata 计费字段；连接中断错误增加安全的异常类型链与目标 host。
- Seedance/Svideo 的官方 ntapi.org 接口根地址自动规范到官网公布的 api.ntapi.org；自定义域名保持原样，提交仍不自动重试。

- Seedance 2.0/2.5 改为单节点提交、等待、下载并输出 VIDEO 与视频URL；旧任务ID输出连线需按新示例改接。
- 所有 NTAPI 动态参考接口的显示标签去除重复前缀并从1编号，内部连接名称保持不变。

- 新增 Seedance 2.0/2.5 兼容生成节点及 2.0 专用获取节点，分别处理两套协议，支持动态图片、视频和音频参考输入；NTAPI 生产兼容性未验证。

- Gemini 生图采用与 GPT 一致的控件布局和 1–14 自动参考图接口，移除质量、风格、数量、返回格式；保留原生接口，新增输出 MIME 格式和超时设置。

- GPT 参考图改为原生 Autogrow：初始 1 个空接口，连接后扩展，最多 14 个；支持零参考图及旧连线迁移。

- GPT 生图按指定顺序调整控件，新增比例/分辨率映射、输出编码格式、超时和原生种子运行后控制；旧布局自动迁移密钥位置。

- 新增视频生成、视频编辑、视频任务获取三个节点，覆盖文生、图生、首尾帧、多参考图和视频编辑。
- 采用 `/v1/videos` 兼容协议，支持任务 ID 续取；不自动重试付费提交。
- 下载结果输出原生 VIDEO，可接 Save Video；补充视频示例和协议说明。
- 视频协议尚未在 NTAPI 实测，不保证模型服务支持；本地修改尚未发布到 GitHub。

## 0.1.0a1 — 2026-10-05

首个公开预览版本，建议 GitHub Release 标签使用 `v0.1.0-alpha.1` 并勾选 Pre-release。

- 提供语言、GPT 生图和 Gemini 生图三个节点，支持自定义模型和接口地址。
- 支持节点密钥或 `NTAPI_API_KEY` 环境变量；参考图批次逐张上传。
- 失败明确报错；不返回占位图，不自动重试付费提交，不跟随重定向。
- 修复 ALL_PROXY 绕过、JSON 数量类型和图片下载鉴权的同源检查。
- GPT 可选参数默认由服务决定；显式选择的值原样传递。
- 包含离线回归测试、GitHub Actions 配置和无密钥示例工作流。

验证范围：本地 Python 3.13 / PyTorch 2.9.1、HTTP 模拟服务及 ComfyUI 加载验证。
真实 NTAPI 付费请求尚未验证；其他系统的测试状态以 GitHub Actions 运行结果为准。
不包含异步任务轮询、视频节点或 ComfyUI Registry / Manager 上架。
