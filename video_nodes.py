import os
import tempfile
import time
from urllib.parse import quote, urljoin

import requests

from .nodes import CATEGORY_NAME, DEFAULT_V1_URL, _api_key, _data_url, _headers, _origin, _request

try:
    import folder_paths
    from comfy.model_management import throw_exception_if_processing_interrupted
    from comfy_api.latest import InputImpl, Types
except ImportError:
    folder_paths = None


VIDEO_MODELS = ["omni-flash", "omni-flash-1080p", "omni-flash-4k",
                "omni-flash-components", "omni-flash-components-1080p", "omni-flash-components-4k"]
EDIT_MODELS = ["omni-flash-edit", "omni-flash-edit-1080p", "omni-flash-edit-4k"]
MODES = ["文生视频", "图生视频", "首尾帧", "多参考图"]
DESCRIPTION = "视频兼容接口，尚未在 NTAPI 实测。提交只执行一次，任务ID接视频任务获取节点。"


def _connection_inputs():
    return {"API密钥": ("STRING", {"default": ""}),
            "接口地址": ("STRING", {"default": DEFAULT_V1_URL}),
            "绕过代理": ("BOOLEAN", {"default": True})}


def _parameters(values, default_model):
    return {"model": values.get("自定义模型", "").strip() or values.get("模型预设", default_model),
            "prompt": values.get("提示词", ""),
            "seconds": str(values.get("时长秒数", 8)),
            "size": values.get("尺寸", "1280x720")}


def _endpoint(values):
    return (values.get("接口地址") or DEFAULT_V1_URL).strip().rstrip("/") + "/videos"


def _task_body(response):
    if not 200 <= response.status_code < 300:
        if response.status_code == 503:
            raise RuntimeError("NTAPI 视频：HTTP 503，接口已连通，但当前模型/分组没有可用渠道，或上游服务暂不可用。")
        raise RuntimeError(f"NTAPI 视频：HTTP {response.status_code}，请检查模型权限及服务控制台。")
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError("NTAPI 视频：上游没有返回 JSON 任务数据。") from None
    if not isinstance(body, dict):
        raise RuntimeError("NTAPI 视频：任务响应格式错误。")
    return body


def _task_id(value):
    task = str(value or "").strip()
    if not task or len(task) > 512 or task in {".", ".."} or any(c in task for c in "/\\?#\r\n"):
        raise RuntimeError("NTAPI 视频：任务ID为空或格式不正确。")
    return task


def _submit(values, payload, files=None):
    key = _api_key(values.get("API密钥", ""))
    request = {"json": payload} if files is None else {"data": payload, "files": files}
    try:
        response = _request("POST", _endpoint(values), values.get("绕过代理", True),
                            headers=_headers(key, files is None), timeout=(30, 120), **request)
    except requests.RequestException:
        raise RuntimeError("NTAPI 视频：提交连接失败或超时，未自动重试。请先在控制台确认是否已创建任务。") from None
    body = _task_body(response)
    if body.get("error"):
        raise RuntimeError("NTAPI 视频：服务拒绝了任务，请查看控制台记录。")
    return (_task_id(body.get("id") or body.get("task_id")),)


class NTAPIVideoGenerateNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "模式": (MODES, {"default": MODES[0]}),
            "提示词": ("STRING", {"default": "", "multiline": True}),
            "模型预设": (VIDEO_MODELS, {"default": VIDEO_MODELS[0]}),
            "自定义模型": ("STRING", {"default": ""}),
            "时长秒数": ("INT", {"default": 8, "min": 1, "max": 120}),
            "尺寸": ("STRING", {"default": "1280x720"}),
            **_connection_inputs()},
            "optional": {"首帧": ("IMAGE",), "尾帧": ("IMAGE",),
                         "参考图批次": ("IMAGE", {"tooltip": "多张图片先用图片批次节点合并，不截断批次。"})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("任务ID",)
    FUNCTION = "run"
    CATEGORY = CATEGORY_NAME
    DESCRIPTION = DESCRIPTION
    OUTPUT_NODE = True

    def run(self, **values):
        payload = _parameters(values, VIDEO_MODELS[0])
        mode = values.get("模式", MODES[0])
        if mode not in MODES:
            raise RuntimeError("NTAPI 视频：未知生成模式。")
        if mode == "多参考图":
            batch = values.get("参考图批次")
            if batch is None:
                raise RuntimeError("NTAPI 视频：多参考图模式需要参考图批次。")
            payload["images"] = [_data_url(frame) for frame in batch]
            payload["generation_type"] = "reference"
        elif mode != "文生视频":
            first = values.get("首帧")
            if first is None:
                raise RuntimeError("NTAPI 视频：请连接首帧。")
            frames = [*first]
            if mode == "首尾帧":
                last = values.get("尾帧")
                if last is None:
                    raise RuntimeError("NTAPI 视频：首尾帧模式需要尾帧。")
                frames.extend(last)
            payload["images"] = [_data_url(frame) for frame in frames]
            payload["generation_type"] = "frame"
        return _submit(values, payload)


class NTAPIVideoEditNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "提示词": ("STRING", {"default": "", "multiline": True}),
            "模型预设": (EDIT_MODELS, {"default": EDIT_MODELS[0]}),
            "自定义模型": ("STRING", {"default": ""}),
            "时长秒数": ("INT", {"default": 8, "min": 1, "max": 120}),
            "尺寸": ("STRING", {"default": "1280x720"}),
            **_connection_inputs()},
            "optional": {"原视频": ("VIDEO",), "视频URL": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("任务ID",)
    FUNCTION = "run"
    CATEGORY = CATEGORY_NAME
    DESCRIPTION = DESCRIPTION
    OUTPUT_NODE = True

    def run(self, **values):
        payload = _parameters(values, EDIT_MODELS[0])
        url = values.get("视频URL", "").strip()
        if url:
            if not url.startswith(("https://", "http://")):
                raise RuntimeError("NTAPI 视频：视频URL需要 HTTP(S) 地址。")
            payload["images"] = [url]
            return _submit(values, payload)
        video = values.get("原视频")
        if video is None:
            raise RuntimeError("NTAPI 视频：请连接原视频或填写视频URL；同时提供时优先使用URL。")
        _require_video_api()
        with tempfile.TemporaryDirectory(prefix="ntapi_upload_") as directory:
            path = os.path.join(directory, "reference.mp4")
            video.save_to(path, format=Types.VideoContainer.MP4)
            with open(path, "rb") as stream:
                return _submit(values, payload, [("input_reference", ("reference.mp4", stream, "video/mp4"))])


def _require_video_api():
    if folder_paths is None:
        raise RuntimeError("NTAPI 视频：需要支持 VIDEO 类型的新版 ComfyUI。")


def _result_url(body):
    data = body.get("data")
    for item in (body, body.get("result"), data, body.get("content"), body.get("metadata"),
                 data.get("content") if isinstance(data, dict) else None):
        if isinstance(item, dict):
            url = item.get("video_url") or item.get("url")
            if isinstance(url, str) and url:
                return url
    return ""


def _download_video(url, base, key, bypass):
    _require_video_api()
    headers = {"Authorization": "Bearer " + key} if _origin(url) == _origin(base) else {}
    for attempt in range(3):
        if attempt:
            time.sleep(1)
        throw_exception_if_processing_interrupted()
        path = None
        complete = False
        stage = "下载视频"
        try:
            with _request("GET", url, bypass, headers=headers, timeout=(30, 120), stream=True) as response:
                if not 200 <= response.status_code < 300:
                    raise RuntimeError(f"NTAPI 视频：下载失败 HTTP {response.status_code}，请用原任务ID重新获取视频链接，不必重新生成。")
                stage = "保存视频"
                with tempfile.NamedTemporaryFile(dir=folder_paths.get_temp_directory(), prefix="ntapi_video_", suffix=".mp4", delete=False) as output:
                    path = output.name
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        throw_exception_if_processing_interrupted()
                        output.write(chunk)
            stage = "读取视频"
            video = InputImpl.VideoFromFile(path)
            video.get_dimensions()
            complete = True
            return video
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as error:
            if attempt < 2:
                continue
            raise RuntimeError(f"NTAPI 视频：视频已生成，但下载连接失败（{type(error).__name__}），3 次下载尝试均未完成。可用原任务ID重新获取，不必重新生成。") from None
        except requests.RequestException as error:
            raise RuntimeError(f"NTAPI 视频：下载请求失败（{type(error).__name__}），可用原任务ID重新获取，不必重新生成。") from None
        except (OSError, ValueError) as error:
            raise RuntimeError(f"NTAPI 视频：本地{stage}失败（{type(error).__name__}），请检查临时目录权限和视频格式。可用原任务ID重新获取，不必重新生成。") from None
        finally:
            # Keep completed files for downstream VIDEO consumers; remove partial files.
            if path is not None and not complete:
                os.remove(path)


class NTAPIVideoTaskFailed(RuntimeError):
    pass


class NTAPIVideoFetchNode:
    _task_endpoint = staticmethod(_endpoint)

    @staticmethod
    def _completed_url(body, endpoint):
        return urljoin(endpoint + "/", _result_url(body) or "content")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"任务ID": ("STRING", {"default": ""}),
                             "最大等待秒数": ("INT", {"default": 1800, "min": 1, "max": 7200}),
                             "轮询间隔秒数": ("INT", {"default": 5, "min": 1, "max": 60}),
                             **_connection_inputs()}}

    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("视频", "视频URL")
    FUNCTION = "run"
    CATEGORY = CATEGORY_NAME
    DESCRIPTION = "查询既有任务并下载视频，输出连接 Save Video。不提交新生成任务。"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **values):
        return float("nan")

    def run(self, **values):
        task = _task_id(values.get("任务ID"))
        key = _api_key(values.get("API密钥", ""))
        endpoint = self._task_endpoint(values) + "/" + quote(task, safe="")
        bypass = values.get("绕过代理", True)
        deadline = time.monotonic() + int(values.get("最大等待秒数", 1800))
        interval = max(1, int(values.get("轮询间隔秒数", 5)))
        while time.monotonic() < deadline:
            if folder_paths is not None:
                throw_exception_if_processing_interrupted()
            try:
                response = _request("GET", endpoint, bypass, headers=_headers(key),
                                    timeout=max(0.1, min(30, deadline - time.monotonic())))
            except requests.RequestException:
                raise RuntimeError(f"NTAPI 视频：查询中断，任务ID：{task}。可用此ID继续获取。") from None
            try:
                body = _task_body(response)
            except RuntimeError as error:
                raise RuntimeError(f"{error} 任务ID：{task}，可继续获取。") from None
            state = str(body.get("status", "")).lower()
            if body.get("error") or state in {"failed", "failure", "error", "cancelled", "canceled", "rejected"}:
                error = body.get("error")
                code = str(error.get("code", "")) if isinstance(error, dict) else ""
                reason = ("上游错误 1501：内容未通过合规审核，可能涉及版权限制。" if code == "1501"
                          else "请查看服务控制台的失败原因。")
                raise NTAPIVideoTaskFailed(f"NTAPI 视频：任务失败，任务ID：{task}。{reason}该任务已结束，不能续取视频。")
            if state in {"completed", "succeeded", "success", "done", "complete"}:
                url = self._completed_url(body, endpoint)
                return _download_video(url, endpoint, key, bypass), url
            if state not in {"queued", "pending", "processing", "running", "in_progress", "submitted"}:
                raise RuntimeError(f"NTAPI 视频：未知任务状态，任务ID：{task}。请核对接口协议。")
            remaining = min(interval, max(0, deadline - time.monotonic()))
            until = time.monotonic() + remaining
            while time.monotonic() < until:
                if folder_paths is not None:
                    throw_exception_if_processing_interrupted()
                time.sleep(min(0.25, max(0, until - time.monotonic())))
        raise RuntimeError(f"NTAPI 视频：等待超时，任务ID：{task}。可用此ID继续获取，不必重新生成。")


NODE_CLASS_MAPPINGS = {"NTAPIVideoGenerateNode": NTAPIVideoGenerateNode,
                       "NTAPIVideoEditNode": NTAPIVideoEditNode, "NTAPIVideoFetchNode": NTAPIVideoFetchNode}
NODE_DISPLAY_NAME_MAPPINGS = {"NTAPIVideoGenerateNode": "NTAPI-视频生成（兼容模式）",
                              "NTAPIVideoEditNode": "NTAPI-视频编辑（兼容模式）",
                              "NTAPIVideoFetchNode": "NTAPI-视频任务获取"}
