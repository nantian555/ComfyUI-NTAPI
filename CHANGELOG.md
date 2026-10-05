# Changelog

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
