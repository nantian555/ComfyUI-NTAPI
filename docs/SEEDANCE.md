# Seedance 2.0 / 2.5 视频节点

新增 `NTAPI-Seedance 2.0生成（兼容模式）`、`NTAPI-Seedance 2.5生成（兼容模式）` 和 `NTAPI-Seedance 2.0任务获取`。

NTAPI 将 Seedance 以 `Svideo` 名称对外展示。节点界面保留 Seedance 参考名称，实际提交使用下表对应的 Svideo ID。可填写“自定义模型”覆盖映射；自定义值原样发送。

| Seedance 节点选择 | 文生视频 | 首尾帧/图生视频 | 多模态参考 |
| --- | --- | --- | --- |
| 2.0 Standard | `Svideo-2.0-standard-t2v` | `Svideo-2.0-standard-i2v` | `Svideo-2.0-standard-multi` |
| 2.0 Fast | `Svideo-2.0-fast-t2v` | `Svideo-2.0-fast-i2v` | `Svideo-2.0-fast-multi` |
| 2.0 Mini | `Svideo-2.0-mini-t2v` | `Svideo-2.0-mini-i2v` | `Svideo-2.0-mini-multi` |
| 2.5 Standard / Global Standard | `Svideo-2.5-standard-t2v` | `Svideo-2.5-standard-i2v` | `Svideo-2.5-standard-multi` |

截至 2026-10-06，NTAPI 模型广场列出以上 12 个 Svideo 模型。搜索 `seedance` 为 0 是因为供应商采用 Svideo 品牌，并非模型缺失。节点直接使用经核对的映射提交，不再额外读取 `/v1/models`，避免模型列表接口的网络超时阻断生成。

## 接线与用法

- 2.0 和 2.5 生成节点均自动完成提交、轮询与下载，直接输出 **VIDEO、视频URL**；视频输出直接接 Save Video，无需额外获取节点。
- 生成节点填接口根地址。内置的 `https://ntapi.org`、`https://www.ntapi.org` 和带 `/v1` 形式会自动规范到官网公布的 API 专用域名 `https://api.ntapi.org`；其他自定义域名只去除末尾 `/v1`，不会被替换。
- 最大等待秒数控制轮询总等待，轮询间隔秒数控制查询频率。任务失败/超时不会自动重新提交；网络中断或等待超时可用原任务 ID 恢复查询。已失败的任务没有视频可续取，需先查看原因。上游 1501 会显示“内容未通过合规审核，可能涉及版权限制”。
- Windows 上若错误包含 `ProtocolError+TimeoutError`，表示连接可能已发送后才中断。先在 NTAPI 控制台检查任务，再决定是否重新运行；节点不会自动补发。
- 生成成功后的下载 GET 遇到连接中断、超时或分块中断时最多尝试三次；不会重新提交生成。持续失败可用原任务 ID 恢复；HTTP、目录权限或视频格式错误会单独提示。
- 旧版“生成→获取”工作流需移除中间获取节点并将生成的 VIDEO 输出接到 Save Video；新的示例已更新。输出类型从 STRING 改为 VIDEO，旧任务ID连线不能继续使用。
- 密钥留空使用 `NTAPI_API_KEY`。所有节点的密钥输入、工作流与生成结果元数据都可能包含明文密钥，分享时应清空。
- 2.5“模型”下拉项只显示 `seedance2.5t2v`、`seedance2.5i2v`、`seedance2.5multi`，分别映射为 NTAPI 的 `Svideo-2.5-standard-t2v/i2v/multi`；旧工作流中的 standard/global 值仍可兼容读取。需要覆盖时，将准确 ID 填入“自定义模型”。
- 文生视频：只读取提示词和参数，不上传连接的参考素材。
- 首尾帧：首帧必需，尾帧可选。不连接尾帧即图生视频；两帧分别使用首帧和尾帧语义。
- 多模态参考：按图片、视频、音频的顺序发送素材；每组接口初始一个，连接后自动增加。显示为参考图1、参考视频1、参考音频1，内部名称仍保留分组以保证执行与保存。
- 2.0 输入组上限为图片 9、视频 3、音频 3；2.5 为图片 30、视频 10、音频 10。它们是参考节点的界面容量，服务限制可能不同。图片与音频批次会完整发送，不自动截断。
- 2.5 预设 t2v/i2v/multi 必须分别配合文生/首尾帧/多模态模式；首尾帧模式的比例按参考协议发送 `adaptive`。自定义模型原样发送。
- 2.0/2.5 参考视频按输入状态导出MP4并上传，保留输入时长及上游节点已做的裁剪。节点不按生成秒数自动截取、补帧或补静音；需要裁剪素材时，请在输入端自行处理。
- 2.5多模态模式接入参考视频时，时长控件自动设为-1并锁定；断开参考视频或切换模式后恢复可编辑。后端也强制发送 `metadata.duration=-1`、`ratio=adaptive` 并省略顶层 `seconds`，旧工作流或API输入中的正数不会覆盖该规则。参考视频保持输入时长，由上游按参考视频模式处理输出时长，不在生成后裁剪。
- 2.5不含参考视频的用法及2.0继续按控件提交：设置4秒发送 `seconds="4"`；选择-1时发送 `metadata.duration=-1` 并省略 `seconds`。
- 自动时长需要配套 Svideo 服务端插件1.1.4或更新版本（官方站已部署）。内部将自动时长意图与正数计费预估分开处理，最终上游请求发送 `metadata.duration=-1` 并省略顶层 `seconds`，价格和结算规则不变。1.1.3 虽通过宿主校验，最终字段位置仍不符合此上游协议。
- 建议2.0使用4–15秒、2.5无参考视频时使用4–30秒；尺寸、时长和素材限制最终由服务决定。服务端自动时长的预扣仍使用保守上限，最终按上游实际用量结算；参考素材也可能计入用量，不能将5秒输出理解为仅收5秒单项费用。
- 种子 -1 不发送，非负值发送；运行后控制是 ComfyUI 原生控件。

## 协议对应

| 项目 | 2.0 | 2.5 |
| --- | --- | --- |
| 图片/视频/音频 | 上传后 HTTP(S) URL，不接受 Data URL | 相同 |
| 素材上传 | `/v1/svideo/files`，表单附带 model，返回 HTTP(S) url | 相同 |
| 创建任务 | `/v1/videos` | `/v1/videos` |
| 查询 | `/v1/videos/{id}` | `/v1/videos/{id}` |
| 提示词 | `prompt` | `prompt` |
| 首尾帧 | `images` URL 数组，首帧在前 | 相同 |
| 多模态参考 | `metadata.content`，包含 image_url/video_url/audio_url | 相同 |
| 参数 | seconds 与 metadata | seconds 与 metadata |
| 视频地址 | `metadata.url` | `metadata.url` |

2026-10-06 已读取 NTAPI 后台启用的 `ntapi-seedancenz@1.1.0` 插件源码，并在插件沙盒干跑验证两版本的文生、首尾帧、多模态请求。插件顶层只接受 `model/prompt/image/images/seconds/metadata`，明确拒绝 `messages`；模型广场的通用 openai-video 示例不能代表此插件的请求契约。Svideo 别名在服务端转换为对应的 `seedance-*-global-*` 上游模型。

干跑只验证请求转换，不提交上游任务，不证明网络、密钥、余额或生成成功。经用户授权的一次合成小图上传返回 HTTP 400（缺少 model），没有返回文件 URL；本机 NTAPI 服务端源码中 `POST /v1/files` 注册到 `RelayNotImplemented`。此前把无密钥 401 当作上传端点可用的依据不成立。

配套服务端新增 `/v1/svideo/files`：使用 NTAPI 令牌与所选模型选择 Svideo 渠道，再经该渠道上传素材。限制为单个非空 PNG/JPEG/WebP/MP4/WAV、50 MiB、每用户每分钟 30 次；上传不创建视频任务。2026-10-06 已部署 `v1.0.0-rc.41-ntapi-svideo-upload1`；2026-10-07 用户实际任务证实素材上传和生成提交走通，其中一次任务因上游审核失败并退款。重启 ComfyUI 才能载入新的上传路径。旧服务器返回 404/501 时会明确提示先部署；节点不会改投其他站点。文生视频不经过上传路径。

后续 2.0 多模态任务已成功生成，并通过原任务 ID 下载、完整解码及原生 VIDEO 读取验证；2.5 成功生成仍待实测。前述审核失败仅描述对应历史任务。

后台“测试渠道连接”会返回 `Task Plugin channel test is not supported`，表示测试功能不支持此插件，不代表模型或渠道失效；不要据此删除模型。

本地 VIDEO 通过 ComfyUI 导出 MP4；AUDIO 编码为 16 位 PCM WAV，保留采样率与通道数。素材上传返回的 URL 被写入 `images` 或 `metadata.content`。超时时间用于每次提交/上传请求，不代表整个多素材流程总时长。错误会区分素材上传与视频任务提交：上传失败时明确说明视频生成尚未提交。连接中断仅显示未被底层显式抑制的异常类型链和 host，不显示密钥、提示词或原始服务正文。任务日志为空不能单独证明请求未到达上游或未计费。

节点使用映射后的 Svideo ID 完成素材上传、提交一次生成任务，随后自动等待并下载视频；不额外请求模型列表。任何错误都会停止并明确提示。生成请求超时后可能已经受理，先查控制台再决定是否重跑。错误中已有任务 ID 时，可用相应获取节点续取，不必重复生成。不提供资产库、联网搜索、尾帧提取、并发队列或错误占位图功能。

## 示例

- [Seedance 2.0 工作流](../examples/seedance20.workflow.json)
- [Seedance 2.5 工作流](../examples/seedance25.workflow.json)

均为无密钥文生视频模板。图生、首尾帧和多模态用法在同一生成节点切换模式，并连接对应素材。此版本仅在本地更新，未发布 GitHub。
