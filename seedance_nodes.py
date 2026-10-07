import io as buffers
import json
import os
import tempfile
import wave
from urllib.parse import urlparse

import requests
import torch

from .nodes import CATEGORY_NAME, DEFAULT_ROOT_URL, _api_key, _headers, _tensor_to_pil
from .video_nodes import NTAPIVideoFetchNode, NTAPIVideoTaskFailed, _request, _task_body, _task_id
from .gpt_autogrow import io


MODELS_20 = ["doubao-seedance-2-0-260128", "doubao-seedance-2-0-fast-260128", "doubao-seedance-2.0-mini"]
MODELS_25 = ["seedance2.5t2v", "seedance2.5i2v", "seedance2.5multi"]
MODELS_25_LEGACY = [f"seedance-2.5-{region}standard-{mode}"
                    for region in ("", "global-") for mode in ("t2v", "i2v", "multi")]
RATIOS = ["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"]
RESOLUTIONS = ["480p", "720p", "1080p", "2k", "4k", "native1080p", "native4k"]
MODES = ["文生视频", "首尾帧", "多模态参考"]
MODE_SUFFIX = {"文生视频": "t2v", "首尾帧": "i2v", "多模态参考": "multi"}
TIERS_20 = {MODELS_20[0]: "standard", MODELS_20[1]: "fast", MODELS_20[2]: "mini"}


def _root(values):
    root = (values.get("接口根地址") or os.environ.get("NTAPI_BASE_URL") or DEFAULT_ROOT_URL).strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    if urlparse(root).hostname in {"ntapi.org", "www.ntapi.org"}:
        return "https://api.ntapi.org"
    return root


def _task_endpoint20(values):
    return _root(values) + "/v1/videos"


def _model_id(values, protocol):
    models = MODELS_20 if protocol == "2.0" else MODELS_25
    custom = values.get("自定义模型", "").strip()
    if custom:
        return custom
    alias = values.get("模型", models[0])
    suffix = MODE_SUFFIX.get(values.get("模式", MODES[0]))
    if not suffix:
        raise RuntimeError("NTAPI Seedance：未知生成模式。")
    if protocol == "2.0" and alias in TIERS_20:
        return f"Svideo-2.0-{TIERS_20[alias]}-{suffix}"
    if protocol == "2.5" and (alias in MODELS_25 or alias in MODELS_25_LEGACY):
        return f"Svideo-2.5-standard-{suffix}"
    return alias


def _post(values, url, **payload):
    key = _api_key(values.get("API秘钥", ""))
    timeout = int(values.get("超时时间", 900))
    uploading = "files" in payload
    stage = "素材上传" if uploading else "视频任务提交"
    hint = ("本次视频生成尚未提交，请检查素材上传接口。" if uploading
            else "未自动重试，请先查看控制台是否已有任务。")
    try:
        response = _request("POST", url, values.get("绕过代理", True),
                            headers=_headers(key, "files" not in payload),
                            timeout=(min(30, timeout), timeout), **payload)
    except requests.Timeout:
        raise RuntimeError(f"NTAPI Seedance：{stage}请求超时。{hint}") from None
    except requests.exceptions.ProxyError:
        raise RuntimeError(f"NTAPI Seedance：{stage}代理连接失败，请检查“绕过代理”设置。{hint}") from None
    except requests.exceptions.SSLError:
        raise RuntimeError(f"NTAPI Seedance：{stage} TLS 证书或加密连接失败，请检查系统时间、证书和代理。{hint}") from None
    except requests.ConnectionError as error:
        causes = []
        pending = [error]
        while pending:
            current = pending.pop(0)
            name = type(current).__name__
            if name not in causes:
                causes.append(name)
            cause = current.__cause__
            if cause is None and not current.__suppress_context__:
                cause = current.__context__
            if cause is not None:
                pending.append(cause)
            for item in getattr(current, "args", ()):
                if isinstance(item, BaseException):
                    pending.append(item)
        host = urlparse(url).hostname or "unknown"
        raise RuntimeError(f"NTAPI Seedance：{stage}连接在请求期间被中断（{'+'.join(causes)}，host={host}）。{hint}") from None
    except requests.RequestException as error:
        raise RuntimeError(f"NTAPI Seedance：{stage}网络请求失败（{type(error).__name__}）。{hint}") from None
    if uploading and response.status_code in {404, 501}:
        raise RuntimeError("NTAPI Seedance：服务端尚未提供 /v1/svideo/files 素材上传接口，请部署配套服务端更新。本次视频生成尚未提交。")
    if response.status_code == 400:
        try:
            rejected = response.json()
        except ValueError:
            rejected = {}
        error = rejected.get("error", rejected) if isinstance(rejected, dict) else {}
        if isinstance(error, dict) and error.get("code") == "fail_to_fetch_task":
            message = error.get("message", "")
            if isinstance(message, str):
                try:
                    error = json.loads(message)
                except ValueError:
                    pass
        if isinstance(error, dict) and error.get("code") == "invalid_video_edit_parameters":
            raise RuntimeError("NTAPI Seedance 2.5：上游拒绝参考视频参数，要求比例 adaptive、时长 duration=-1。未自动重试。")
        if isinstance(error, dict) and error.get("code") == "plugin_usage_invalid":
            raise RuntimeError("NTAPI Seedance：服务端计费参数校验拒绝了请求，请检查 Svideo 插件版本及自动时长处理。未自动重试。")
    try:
        body = _task_body(response)
    except RuntimeError as error:
        if "JSON" in str(error):
            raise RuntimeError(f"NTAPI Seedance：{stage}接口返回非 JSON：{urlparse(url).path}。{hint}") from None
        raise RuntimeError(f"NTAPI Seedance：{stage}失败。{error} {hint}") from None
    if body.get("error"):
        raise RuntimeError(f"NTAPI Seedance：{stage}服务报告错误。{hint}")
    return body


def _upload(values, protocol, stream, filename, mime):
    body = _post(values, _root(values) + "/v1/svideo/files",
                 data={"model": _model_id(values, protocol)}, files=[("file", (filename, stream, mime))])
    url = body.get("url")
    if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
        raise RuntimeError("NTAPI Seedance：上传响应缺少 HTTP(S) 文件URL，未提交视频生成。")
    return url


def _items(group):
    return [group[name] for name in sorted(group or {}, key=lambda name: int(name.rsplit("_", 1)[-1]))
            if group[name] is not None]


def _frames(images):
    for batch in images:
        yield from batch if batch.ndim == 4 else batch.unsqueeze(0)


def _image_url(frame, values, protocol):
    with buffers.BytesIO() as file:
        _tensor_to_pil(frame).save(file, format="PNG")
        file.seek(0)
        return _upload(values, protocol, file, "reference.png", "image/png")


def _media_content(values, protocol):
    mode = values.get("模式", MODES[0])
    content = []
    if mode not in MODES:
        raise RuntimeError("NTAPI Seedance：未知生成模式。")
    if mode == "文生视频":
        return content
    if mode == "首尾帧":
        if values.get("首帧") is None:
            raise RuntimeError("NTAPI Seedance：首尾帧模式需要首帧；尾帧可不连接。")
        for name in ("首帧", "尾帧"):
            if values.get(name) is not None:
                for frame in _frames([values[name]]):
                    content.append({"type": "image_url", "image_url": {"url": _image_url(frame, values, protocol)}})
        return content
    for frame in _frames(_items(values.get("参考图"))):
        content.append({"type": "image_url", "image_url": {"url": _image_url(frame, values, protocol)}})
    for video in _items(values.get("参考视频")):
        with tempfile.TemporaryDirectory(prefix="ntapi_seedance_") as directory:
            path = os.path.join(directory, "reference.mp4")
            video.save_to(path, format="mp4")
            with open(path, "rb") as file:
                url = _upload(values, protocol, file, "reference.mp4", "video/mp4")
        content.append({"type": "video_url", "video_url": {"url": url}})
    for audio in _items(values.get("参考音频")):
        for waveform in audio["waveform"]:
            samples = waveform.detach().to(device="cpu", dtype=torch.float32).transpose(0, 1)
            pcm = samples.clamp(-1, 1).mul(32767).round().to(torch.int16).numpy().astype("<i2").tobytes()
            with buffers.BytesIO() as file:
                with wave.open(file, "wb") as output:
                    output.setnchannels(waveform.shape[0])
                    output.setsampwidth(2)
                    output.setframerate(int(audio["sample_rate"]))
                    output.writeframes(pcm)
                file.seek(0)
                url = _upload(values, protocol, file, "reference.wav", "audio/wav")
            content.append({"type": "audio_url", "audio_url": {"url": url}})
    return content


def submit_seedance(values, protocol):
    # Check authentication before any media encoding or upload.
    _api_key(values.get("API秘钥", ""))
    selected = values.get("自定义模型", "").strip() or values.get("模型", MODELS_25[0] if protocol == "2.5" else MODELS_20[0])
    mode = values.get("模式", MODES[0])
    if protocol == "2.5" and not values.get("自定义模型", "").strip() and selected in (MODELS_25 + MODELS_25_LEGACY):
        suffix = MODE_SUFFIX.get(mode)
        selected_suffix = (selected[len("seedance2.5"):]
                           if selected in MODELS_25 else selected.rsplit("-", 1)[-1])
        if not suffix or selected_suffix != suffix:
            raise RuntimeError("NTAPI Seedance 2.5：模式与模型不匹配，请选择对应的 t2v/i2v/multi 模型。")
    model = _model_id(values, protocol)
    prompt = values.get("提示词", "")
    duration = int(values.get("时长秒数", 5))
    media = _media_content(values, protocol)
    settings = {"resolution": values.get("分辨率", "720p"), "ratio": values.get("比例", "adaptive"),
                "generate_audio": bool(values.get("生成音频", True))}
    seed = int(values.get("种子", -1))
    if seed >= 0:
        settings["seed"] = seed
    if protocol == "2.5" and mode == "首尾帧":
        settings["ratio"] = "adaptive"
    if protocol == "2.5" and mode == "多模态参考" and any(item["type"] == "video_url" for item in media):
        settings["ratio"] = "adaptive"
        duration = -1
    if duration == -1:
        settings["duration"] = -1
    payload = {
        "model": model,
        "prompt": prompt,
        "metadata": settings,
    }
    if mode == "首尾帧":
        payload["images"] = [item["image_url"]["url"] for item in media]
    elif mode == "多模态参考":
        settings["content"] = media
    if duration != -1:
        payload["seconds"] = str(duration)
    endpoint = _root(values) + "/v1/videos"
    body = _post(values, endpoint, json=payload)
    return (_task_id(body.get("id") or body.get("task_id")),)


class NTAPISeedance20FetchNode(NTAPIVideoFetchNode):
    _task_endpoint = staticmethod(_task_endpoint20)
    DESCRIPTION = "恢复查询 Seedance 2.0 任务。接口根地址与提交节点一致，使用 NTAPI /v1/videos。"

    @classmethod
    def INPUT_TYPES(cls):
        inputs = super().INPUT_TYPES()
        inputs["required"].pop("接口地址")
        inputs["required"]["接口根地址"] = ("STRING", {"default": DEFAULT_ROOT_URL})
        return inputs

def generate_seedance(values, protocol):
    task, = submit_seedance(values, protocol)
    fetch = NTAPISeedance20FetchNode() if protocol == "2.0" else NTAPIVideoFetchNode()
    try:
        return fetch.run(**{
            "任务ID": task, "API密钥": _api_key(values.get("API秘钥", "")),
            "接口根地址": _root(values), "接口地址": _root(values) + "/v1",
            "绕过代理": values.get("绕过代理", True),
            "最大等待秒数": values.get("最大等待秒数", 1800),
            "轮询间隔秒数": values.get("轮询间隔秒数", 5),
        })
    except NTAPIVideoTaskFailed:
        raise
    except RuntimeError as error:
        raise RuntimeError(f"{error} Seedance任务ID：{task}；可在控制台或任务获取节点续取，勿重复生成。") from None


NODE_CLASS_MAPPINGS = {"NTAPISeedance20FetchNode": NTAPISeedance20FetchNode}
NODE_DISPLAY_NAME_MAPPINGS = {"NTAPISeedance20FetchNode": "NTAPI-Seedance 2.0任务获取"}

if io is not None:
    def _schema(protocol, node_id):
        models = MODELS_20 if protocol == "2.0" else MODELS_25
        inputs = [io.String.Input("提示词", default="", multiline=True),
                  io.String.Input("API秘钥", default="", tooltip="留空使用 NTAPI_API_KEY。"),
                  io.Combo.Input("模型", options=models, default=models[0],
                                 tooltip="2.5 仅显示 t2v、i2v、multi 三个 NTAPI 模型；提交时映射为 Svideo ID。" if protocol == "2.5" else "Seedance 参考名称；提交时按版本、档位和模式映射为 NTAPI 的 Svideo 模型ID。"),
                  io.String.Input("自定义模型", default="",
                                  tooltip="填写时原样发送并覆盖别名映射；留空则把上方 Seedance 参考名称映射为 Svideo。"),
                  io.Combo.Input("模式", options=MODES, default=MODES[0]),
                  io.Combo.Input("比例", options=RATIOS, default="adaptive",
                                 tooltip="2.5 首尾帧或带参考视频时自动使用 adaptive。" if protocol == "2.5" else "输出视频比例。"),
                  io.Combo.Input("分辨率", options=RESOLUTIONS if protocol == "2.0" else RESOLUTIONS[:-1], default="720p"),
                  io.Int.Input("时长秒数", default=5, min=-1, max=15 if protocol == "2.0" else 30,
                               tooltip=("多模态接入参考视频时固定使用 -1，由上游按参考视频处理时长；不接参考视频时按此秒数提交。参考视频不自动裁剪或补帧。"
                                        if protocol == "2.5" else "目标生成时长；正数按固定秒数提交，-1 使用自动时长。参考视频保持输入时长。")),
                  io.Boolean.Input("生成音频", default=True),
                  io.String.Input("接口根地址", default=DEFAULT_ROOT_URL),
                  io.Boolean.Input("绕过代理", default=True),
                  io.Int.Input("超时时间", default=900, min=30, max=3600),
                  io.Int.Input("最大等待秒数", default=1800, min=1, max=7200),
                  io.Int.Input("轮询间隔秒数", default=5, min=1, max=60),
                  io.Int.Input("种子", default=-1, min=-1, max=2147483647, control_after_generate=True),
                  io.Image.Input("首帧", optional=True), io.Image.Input("尾帧", optional=True)]
        for label, kind, cap in (("参考图", io.Image, 9 if protocol == "2.0" else 30),
                                 ("参考视频", io.Video, 3 if protocol == "2.0" else 10),
                                 ("参考音频", io.Audio, 3 if protocol == "2.0" else 10)):
            inputs.append(io.Autogrow.Input(label, optional=True, template=io.Autogrow.TemplatePrefix(
                kind.Input("media"), prefix=label + "_", min=0, max=cap)))
        return io.Schema(node_id=node_id, display_name=f"NTAPI-Seedance {protocol}生成（兼容模式）",
                         category=CATEGORY_NAME, inputs=inputs,
                         outputs=[io.Video.Output(display_name="视频"), io.String.Output(display_name="视频URL")],
                         is_output_node=True, description="参考接口预设，NTAPI 协议尚未实测。自动提交、等待和下载，视频输出直接连接 Save Video。")

    class NTAPISeedance20Node(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return _schema("2.0", "NTAPISeedance20Node")

        @classmethod
        def execute(cls, **values):
            return io.NodeOutput(*generate_seedance(values, "2.0"))

    class NTAPISeedance25Node(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return _schema("2.5", "NTAPISeedance25Node")

        @classmethod
        def execute(cls, **values):
            return io.NodeOutput(*generate_seedance(values, "2.5"))

    NODE_CLASS_MAPPINGS.update(NTAPISeedance20Node=NTAPISeedance20Node, NTAPISeedance25Node=NTAPISeedance25Node)
    NODE_DISPLAY_NAME_MAPPINGS.update(NTAPISeedance20Node="NTAPI-Seedance 2.0生成（兼容模式）",
                                     NTAPISeedance25Node="NTAPI-Seedance 2.5生成（兼容模式）")
