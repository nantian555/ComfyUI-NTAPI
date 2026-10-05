# 发布步骤

当前版本 `0.1.0a1`，建议 GitHub 标签 `v0.1.0-alpha.1`。本地准备不包括 GitHub 建库、推送或 Registry 注册。

## 发布前

1. 在 ComfyUI Python 环境执行 `python -m unittest discover -s tests -v`。
2. 阅读 README 的已知限制。未做真实 NTAPI 验证时只能宣称模拟验证通过；发布为 Pre-release。
3. 检查 `git status --short`、`git diff --cached`；不要提交 `.env`、令牌、日志、输出图片或私人工作流。示例中的 API密钥必须为空。
4. 保留 LICENSE 与 NOTICE.md 的上游版权声明。

## 推送

在 GitHub 创建 Public 空仓库 `ComfyUI-NTAPI`，不要自动初始化文件。然后在本项目根目录执行：

```text
git init -b main
git add .
git diff --cached
git commit -m "Add NTAPI ComfyUI nodes"
git remote add origin https://github.com/YOUR_USERNAME/ComfyUI-NTAPI.git
git push -u origin main
```

将 YOUR_USERNAME 替换为实际账号。仓库已有 origin 时先检查 `git remote -v`，不要重复添加。提交者姓名和邮箱使用自己的 Git 配置。

## GitHub Release 文案

标题：`v0.1.0-alpha.1 — NTAPI 节点组预览版`

内容：

> 提供语言、GPT 生图和 Gemini 生图节点，支持自定义模型、接口地址、参考图及环境变量密钥。
> 已通过本地离线回归测试与 ComfyUI 加载检查。真实 NTAPI 生产调用尚未验证；不含异步任务轮询和视频支持。
> 安装方法、参数限制和密钥分享注意事项见 README。

勾选 Pre-release。首次推送后查看 Actions 的实际结果，未通过不要标注跨平台验证通过。生产请求的冒烟测试应使用自己的密钥、无隐私提示词，了解计费后分别验证聊天、GPT 文生图/编辑、Gemini 生图，再更新测试状态。
