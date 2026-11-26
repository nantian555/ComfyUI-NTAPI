# 发布步骤

当前版本 `0.2.0a4`，GitHub 标签 `v0.2.0-alpha.4`，发布为 Pre-release。原仓库为 `nantian555/ComfyUI-NTAPI`；GitHub 发布不包括 ComfyUI Registry 注册。

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
git add nodes.py tests/test_nodes.py README.md CHANGELOG.md docs/VALIDATION.md docs/RELEASING.md pyproject.toml
git diff --cached
git commit -m "Update Nano Banana image API compatibility"
git push origin main
```

将版本对应的提交标记为 `v0.2.0-alpha.4`，打包该提交的文件并生成 SHA-256 校验文件；不要把未跟踪文件、日志或输出图片打包。提交者姓名和邮箱沿用本项目的 Git 配置。

## GitHub Release 文案

标题：`v0.2.0-alpha.4 — 修复三款香蕉模型生图接口`

内容：

> 三款香蕉模型改用 NTAPI 当前的 `/v1/chat/completions`。比例与分辨率通过请求顶层 `image_config` 传递，参考图放入 `messages` 的 `image_url`。
> 78 项 Python 回归和两个前端测试通过。验证使用模拟请求，本次实际付费出图未验证。
> 安装方法、参数限制和密钥分享注意事项见 README。

勾选 Pre-release，附上安装 ZIP 与 SHA-256 校验文件。推送后查看 Actions 的实际结果，未通过不要标注跨平台验证通过。生产请求的冒烟测试使用自己的密钥，明确计费范围后再执行，并据实更新验证记录。
