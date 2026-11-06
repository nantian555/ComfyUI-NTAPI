# 发布步骤

当前版本 `0.2.0a3`，GitHub 标签 `v0.2.0-alpha.3`，发布为 Pre-release。原仓库为 `nantian555/ComfyUI-NTAPI`；GitHub 发布不包括 ComfyUI Registry 注册。

## 发布前

1. 在 ComfyUI Python 环境执行 `python -m unittest discover -s tests -v`。
2. 执行 `node tests/test_gpt_image_ui.mjs` 和 `node tests/test_reference_labels.mjs`，阅读 README 与验证记录，明确离线回放和真实远程生成的验证范围。
3. 检查 `git status --short`、`git diff --cached`；不要提交 `.env`、令牌、日志、输出图片或私人工作流。示例中的 API密钥必须为空。
4. 保留 LICENSE 与 NOTICE.md 的上游版权声明。

## 推送

在本项目根目录确认远端与待发布文件，再提交本次改动；只暂存经过检查的文件，保留无关本地工作。

```text
git remote -v
git status --short
git diff --check
git add nodes.py README.md CHANGELOG.md docs/VALIDATION.md docs/RELEASING.md pyproject.toml
git diff --cached
git commit -m "Add GPT-image 2.6 model options"
git push origin main
```

将版本对应的提交标记为 `v0.2.0-alpha.3`，打包该提交的文件并生成 SHA-256 校验文件；不要把未跟踪文件、日志或输出图片打包。提交者姓名和邮箱沿用本项目的 Git 配置。

## GitHub Release 文案

标题：`v0.2.0-alpha.3 — 新增 GPT-image2.6 两款模型`

内容：

> GPT 生图菜单新增 gpt-image-2.6-flare、gpt-image-2.6-sunburst，通过 NTAPI 调用对应的 SUBAPI 资源，支持现有文生图与参考图编辑请求。
> 已通过 75 项 Python 测试、两个前端脚本及两款模型的四种请求模拟。本次未新增付费生成，GPT-image2.6 实际出图仍待验证。
> 安装方法、参数限制和密钥分享注意事项见 README。

勾选 Pre-release，附上安装 ZIP 与 SHA-256 校验文件。推送后查看 Actions 的实际结果，未通过不要标注跨平台验证通过。生产请求的冒烟测试使用自己的密钥，明确计费范围后再执行，并据实更新验证记录。
