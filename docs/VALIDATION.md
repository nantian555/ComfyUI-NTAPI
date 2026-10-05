# 本地发布检查记录

日期：2026-10-05。版本：0.1.0a1。

- 环境：Windows、ComfyUI 所用 Python 3.13、PyTorch 2.9.1+cu130；测试不执行 GPU 模型推理。
- `python -m unittest discover -s tests -v`：19 项通过。
- ComfyUI `load_custom_node`：三个节点加载成功。
- ComfyUI `validate_prompt`：GPT 与 Gemini 示例工作流均通过，未执行生成。
- ComfyUI pyproject 解析成功；语法和示例 JSON 检查通过。
- 示例中的 API密钥为空，使用环境变量或由安装者自行填写。
- 发布文件扫描范围：Git 未忽略的源码、文档、配置与示例；检查常见令牌/私钥格式、示例密钥值及本机绝对路径。未发现实际密钥或私有路径。该扫描不等于完整安全审计。
- 发布 ZIP 排除 `.git`、缓存、日志与 `dist`；校验文件内容和 ZIP CRC。

尚未验证：真实 NTAPI 生产请求、NTAPI 异步协议、Linux/macOS 运行及 GitHub Actions 实际执行。因此本版是公开预览版，不宣称生产兼容性已验证。
