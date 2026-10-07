import base64
import io
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import numpy as np
import requests
import torch
from PIL import Image


CATEGORY_NAME = "NTAPI中转"
DEFAULT_V1_URL = "https://ntapi.org/v1"
DEFAULT_ROOT_URL = "https://ntapi.org"

CHAT_MODELS = [
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-6-astra",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.7-flash",
]
OPENAI_IMAGE_MODELS = ["gpt-image-2", "gpt-image-2-all", "gpt-image-2-2K", "gpt-image-2-4K",
                       "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]
GEMINI_IMAGE_MODELS = ["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"]
IMAGE_RATIOS = ["auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5", "16:9", "9:16", "2:1", "1:2", "21:9", "9:21"]
IMAGE_RESOLUTIONS = ["1k", "2k", "4k"]
IMAGE_QUALITIES = ["auto", "high", "medium", "low"]
IMAGE_STYLES = ["服务默认", "vivid", "natural"]
IMAGE_RESPONSE_FORMATS = ["url", "b64_json"]
IMAGE_OUTPUT_FORMATS = ["png", "jpeg", "webp"]
IMAGE_DIMENSIONS = {
    "1:1": [(1024, 1024), (2048, 2048), (2880, 2880)],
    "3:2": [(1248, 832), (2496, 1664), (3504, 2336)],
    "4:3": [(1152, 864), (2304, 1728), (3264, 2448)],
    "5:4": [(1120, 896), (2240, 1792), (3200, 2560)],
    "16:9": [(1280, 720), (2560, 1440), (3840, 2160)],
    "2:1": [(2048, 1024), (2688, 1344), (3840, 1920)],
    "21:9": [(1456, 624), (3024, 1296), (3696, 1584)],
}


def _image_size(ratio, resolution):
    if ratio == "auto":
        return "auto"
    index = IMAGE_RESOLUTIONS.index(resolution)
    if ratio in IMAGE_DIMENSIONS:
        width, height = IMAGE_DIMENSIONS[ratio][index]
    else:
        reverse = ":".join(reversed(ratio.split(":")))
        height, width = IMAGE_DIMENSIONS[reverse][index]
    return f"{width}x{height}"
GEMINI_SIZES = ["1K", "2K", "4K"]
GEMINI_RATIOS = ["自动", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"]


def _request(method: str, url: str, bypass_proxy: bool, **kwargs: Any) -> requests.Response:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("NTAPI：接口或图片地址无效，请使用不含账号密码的 HTTP(S) 地址。")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and kwargs.get("headers", {}).get("Authorization"):
        raise RuntimeError("NTAPI：携带密钥的远程接口必须使用 HTTPS。")
    with requests.Session() as session:
        session.trust_env = not bypass_proxy
        # A redirect can resend a paid request or forward a private prompt.
        return session.request(method, url, allow_redirects=False, **kwargs)


def _api_key(value: str) -> str:
    key = value.strip() or os.environ.get("NTAPI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NTAPI：请填写 API密钥，或设置 NTAPI_API_KEY 环境变量。")
    return key


def _headers(api_key: str, json_body: bool = True) -> Dict[str, str]:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {(api_key or '').strip()}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _model(preset: str, custom: str) -> str:
    return custom.strip() or preset.strip()


def _json_response(response: requests.Response) -> Any:
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"NTAPI：HTTP {response.status_code}，请检查接口地址、密钥权限、余额和服务状态。")
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError("NTAPI：上游返回非 JSON，请检查接口地址和服务状态。") from None
    if not isinstance(body, dict):
        raise RuntimeError("NTAPI：上游返回格式错误，预期 JSON 对象。")
    if body.get("error"):
        raise RuntimeError("NTAPI：上游报告错误，请在服务控制台查看请求记录。")
    if body.get("task_id") or body.get("status") in {"queued", "pending", "processing", "running"}:
        raise RuntimeError("NTAPI：收到异步任务，本版只支持同步结果。请在服务控制台查询任务，避免重复提交。")
    return body


def _reference_frames(kwargs):
    names = sorted((name for name in kwargs if re.fullmatch(r"参考图\d+", name)), key=lambda name: int(name[3:]))
    return [frame for name in names for batch in [kwargs[name]] if isinstance(batch, torch.Tensor)
            for frame in (batch if batch.dim() == 4 else batch.unsqueeze(0))]


def _tensor_to_pil(image: torch.Tensor) -> Image.Image:
    frame = image[0] if image.dim() == 4 else image
    array = frame.detach().cpu().clamp(0, 1).numpy()
    if array.ndim != 3 or array.shape[-1] not in (1, 3, 4):
        raise ValueError(f"不支持的 IMAGE 形状: {tuple(image.shape)}")
    if array.shape[-1] == 1:
        array = np.repeat(array, 3, axis=-1)
    if array.shape[-1] == 4:
        array = array[..., :3]
    return Image.fromarray((array * 255).round().astype(np.uint8), mode="RGB")


def _pil_to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _jpeg_bytes(image: torch.Tensor) -> bytes:
    picture = _tensor_to_pil(image)
    output = io.BytesIO()
    picture.save(output, format="JPEG", quality=100)
    return output.getvalue()


def _data_url(image: torch.Tensor) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(_jpeg_bytes(image)).decode("ascii")


def _inline_data(image: torch.Tensor) -> Dict[str, str]:
    return {"mimeType": "image/jpeg", "data": base64.b64encode(_jpeg_bytes(image)).decode("ascii")}


def _stack_images(images: List[torch.Tensor]) -> torch.Tensor:
    if not images:
        raise RuntimeError("NTAPI：响应中没有图片，请检查模型和参数；本版不支持异步图片任务。")
    height, width = images[0].shape[1:3]
    normalized = []
    for image in images:
        if image.shape[1:3] != (height, width):
            picture = _tensor_to_pil(image).resize((width, height), Image.Resampling.LANCZOS)
            image = _pil_to_tensor(picture)
        normalized.append(image)
    return torch.cat(normalized, dim=0)


def _walk_image_values(body: dict) -> Iterable[Tuple[str, str]]:
    for item in body.get("data", []):
        if item.get("b64_json"):
            yield "base64", item["b64_json"]
        elif item.get("url"):
            yield "url", item["url"]
    for candidate in body.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                yield "base64", inline["data"]
            file_data = part.get("fileData") or part.get("file_data") or {}
            url = file_data.get("fileUri") or file_data.get("file_uri")
            if url:
                yield "url", url
            # Only explicit Markdown image links, not arbitrary prose links.
            for url in re.findall(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", part.get("text", "")):
                yield "url", url


def _origin(url: str) -> tuple:
    parsed = urlparse(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _decode_image_candidates(body: Any, base_url: str, api_key: str, bypass_proxy: bool, timeout_sec: int = 120) -> List[torch.Tensor]:
    images: List[torch.Tensor] = []
    base = base_url.rstrip("/") + "/"
    for kind, value in _walk_image_values(body):
        value = value.strip()
        try:
            if kind == "url" and not value.startswith("data:"):
                image_url = urljoin(base, value)
                headers = {"Accept": "image/*,*/*;q=0.8"}
                if _origin(image_url) == _origin(base_url):
                    headers["Authorization"] = f"Bearer {(api_key or '').strip()}"
                response = _request("GET", image_url, bypass_proxy, headers=headers, timeout=timeout_sec)
                if not 200 <= response.status_code < 300:
                    raise RuntimeError(f"NTAPI：下载图片失败，HTTP {response.status_code}。图片地址需直接返回文件。")
                images.append(_pil_to_tensor(Image.open(io.BytesIO(response.content))))
            else:
                encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
                raw = base64.b64decode(encoded, validate=True)
                images.append(_pil_to_tensor(Image.open(io.BytesIO(raw))))
        except (OSError, ValueError, requests.RequestException):
            raise RuntimeError("NTAPI：图片下载或解码失败，请在控制台检查结果。") from None
    return images


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""
    return ""


def _chat_text(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    if isinstance(body.get("output_text"), str) and body["output_text"].strip():
        return body["output_text"].strip()
    choices = body.get("choices")
    if isinstance(choices, list):
        texts = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or choice.get("delta") or {}
            text = _text_content(message.get("content", "")) if isinstance(message, dict) else ""
            if text:
                texts.append(text)
        if texts:
            return "\n".join(texts).strip()
    return _text_content(body.get("content", ""))


def _gemini_url(root_url: str, model_name: str) -> str:
    root = (root_url or DEFAULT_ROOT_URL).strip().rstrip("/")
    root = re.sub(r"/v1(?:beta)?$", "", root, flags=re.IGNORECASE)
    return f"{root}/v1beta/models/{quote(model_name, safe='-_.')}:generateContent"


def _gemini_ratio(value: str) -> Optional[str]:
    value = (value or "").strip()
    return None if value in {"", "自动", "auto", "Auto"} else value


class NTAPIChatNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "系统提示词": ("STRING", {"multiline": True, "default": "You are a helpful assistant."}),
                "用户提示词": ("STRING", {"multiline": True, "default": ""}),
                "模型预设": (CHAT_MODELS, {"default": CHAT_MODELS[0]}),
                "自定义模型": ("STRING", {"default": ""}),
                "API密钥": ("STRING", {"default": ""}),
                "接口地址": ("STRING", {"default": DEFAULT_V1_URL}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
                "绕过代理": ("BOOLEAN", {"default": True}),
            },
            "optional": {f"参考图{i}": ("IMAGE",) for i in range(1, 5)},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文本",)
    FUNCTION = "run"
    CATEGORY = CATEGORY_NAME
    OUTPUT_NODE = True

    def run(self, **kwargs):
        api_key = _api_key(kwargs.get("API密钥") or "")
        prompt = (kwargs.get("用户提示词") or "").strip()
        refs = _reference_frames(kwargs)
        if not prompt and not refs:
            raise RuntimeError("NTAPI：用户提示词或参考图不能为空。")
        content: Any = prompt
        if refs:
            content = ([{"type": "text", "text": prompt or "请描述或处理这些参考图。"}] + [
                {"type": "image_url", "image_url": {"url": _data_url(image)}} for image in refs
            ])
        payload: Dict[str, Any] = {
            "model": _model(kwargs.get("模型预设") or CHAT_MODELS[0], kwargs.get("自定义模型", "")),
            "stream": False,
            "messages": [
                {"role": "system", "content": kwargs.get("系统提示词") or "You are a helpful assistant."},
                {"role": "user", "content": content},
            ],
        }
        seed = int(kwargs.get("种子", 0) or 0)
        if seed > 0:
            payload["seed"] = seed
        try:
            response = _request(
                "POST", (kwargs.get("接口地址") or DEFAULT_V1_URL).strip().rstrip("/") + "/chat/completions",
                bool(kwargs.get("绕过代理", True)), headers=_headers(api_key), json=payload, timeout=(30, 300)
            )
            body = _json_response(response)
            text = _chat_text(body)
            if not text:
                raise RuntimeError("NTAPI：响应没有文本，请检查模型或内容限制。")
            return (text,)
        except requests.RequestException:
            raise RuntimeError("NTAPI：网络请求失败或超时，请检查代理和服务状态；请勿立即重复提交。") from None


class NTAPIOpenAIImageNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"multiline": True, "default": ""}),
                "API秘钥": ("STRING", {"default": "", "tooltip": "留空时使用 NTAPI_API_KEY 环境变量。"}),
                "模型": (OPENAI_IMAGE_MODELS, {"default": OPENAI_IMAGE_MODELS[0]}),
                "比例": (IMAGE_RATIOS, {"default": "auto", "tooltip": "auto 交给服务决定；固定比例与分辨率共同确定像素尺寸。"}),
                "分辨率": (IMAGE_RESOLUTIONS, {"default": "1k"}),
                "质量": (IMAGE_QUALITIES, {"default": "auto"}),
                "风格": (IMAGE_STYLES, {"default": "服务默认"}),
                "数量": ("INT", {"default": 1, "min": 1, "max": 10}),
                "输出格式": (IMAGE_OUTPUT_FORMATS, {"default": "png"}),
                "返回格式": (IMAGE_RESPONSE_FORMATS, {"default": "url"}),
                "绕过代理": ("BOOLEAN", {"default": True}),
                "超时时间": ("INT", {"default": 900, "min": 60, "max": 1200, "tooltip": "秒；单次生成请求或结果图片下载的等待时间，不会自动重试。"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True,
                                  "tooltip": "用于 ComfyUI 缓存及运行后控制，不发送给图片接口，不保证相同种子复现。"}),
            },
            "optional": {f"参考图{i}": ("IMAGE",) for i in range(1, 15)},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "run"
    CATEGORY = CATEGORY_NAME

    def run(self, **kwargs):
        api_key = _api_key(kwargs.get("API秘钥") or kwargs.get("API密钥") or "")
        prompt = (kwargs.get("提示词") or "").strip()
        if not prompt:
            raise RuntimeError("NTAPI：GPT 生图提示词不能为空。")
        refs = _reference_frames(kwargs)
        base_url = (kwargs.get("接口地址") or os.environ.get("NTAPI_BASE_URL") or DEFAULT_V1_URL).strip().rstrip("/")
        model_name = kwargs.get("模型") or _model(kwargs.get("模型预设") or OPENAI_IMAGE_MODELS[0], kwargs.get("自定义模型", ""))
        timeout_sec = int(kwargs.get("超时时间", 900))
        fields = {
            "model": model_name,
            "prompt": prompt,
            "size": kwargs.get("尺寸") or _image_size(kwargs.get("比例", "auto"), kwargs.get("分辨率", "1k")),
            "n": int(kwargs.get("数量", 1)),
        }
        for label, field, default in (("质量", "quality", "auto"), ("风格", "style", "服务默认"),
                                      ("输出格式", "output_format", "png"), ("返回格式", "response_format", "url")):
            value = kwargs.get(label, default)
            if value != "服务默认":
                fields[field] = value
        bypass_proxy = bool(kwargs.get("绕过代理", True))
        try:
            if refs:
                files = [("image" if len(refs) == 1 else "image[]", (f"reference-{i}.jpg", _jpeg_bytes(image), "image/jpeg"))
                         for i, image in enumerate(refs, 1)]
                response = _request(
                    "POST", base_url + "/images/edits", bypass_proxy,
                    headers=_headers(api_key, json_body=False), data={key: str(value) for key, value in fields.items()}, files=files, timeout=(min(30, timeout_sec), timeout_sec)
                )
            else:
                response = _request(
                    "POST", base_url + "/images/generations", bypass_proxy,
                    headers=_headers(api_key), json=fields, timeout=(min(30, timeout_sec), timeout_sec)
                )
            body = _json_response(response)
            images = _decode_image_candidates(body, base_url, api_key, bypass_proxy, timeout_sec)
            return (_stack_images(images),)
        except requests.RequestException:
            raise RuntimeError("NTAPI：生图请求失败或超时，请检查服务控制台；请勿立即重复提交。") from None


class NTAPIGeminiImageNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "提示词": ("STRING", {"multiline": True, "default": ""}),
                "API秘钥": ("STRING", {"default": "", "tooltip": "留空时使用 NTAPI_API_KEY 环境变量。"}),
                "模型": (GEMINI_IMAGE_MODELS, {"default": GEMINI_IMAGE_MODELS[0]}),
                "比例": (GEMINI_RATIOS, {"default": "自动"}),
                "分辨率": (GEMINI_SIZES, {"default": "2K"}),
                "输出格式": (IMAGE_OUTPUT_FORMATS, {"default": "png", "tooltip": "请求 Gemini 的输出 MIME 格式；实际支持情况以模型服务为准。"}),
                "绕过代理": ("BOOLEAN", {"default": True}),
                "超时时间": ("INT", {"default": 900, "min": 60, "max": 1200, "tooltip": "秒；用于请求与结果图片下载，不自动重试。"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True,
                                  "tooltip": "0 不发送种子；正数发送给 Gemini。可复现性取决于服务支持。"}),
            },
            "optional": {f"参考图{i}": ("IMAGE",) for i in range(1, 15)},
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图像", "结果格式")
    FUNCTION = "run"
    CATEGORY = CATEGORY_NAME

    def run(self, **kwargs):
        api_key = _api_key(kwargs.get("API秘钥") or kwargs.get("API密钥") or "")
        prompt = (kwargs.get("提示词") or "").strip()
        refs = _reference_frames(kwargs)
        if not prompt and not refs:
            raise RuntimeError("NTAPI：提示词或参考图不能为空。")
        parts: List[Dict[str, Any]] = [{"text": prompt or "请根据参考图生成图像。"}]
        parts.extend({"inlineData": _inline_data(image)} for image in refs)
        generation_config: Dict[str, Any] = {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "imageSize": kwargs.get("分辨率", kwargs.get("图像尺寸", "2K")),
                "imageOutputOptions": {"mimeType": {
                    "png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"
                }.get(kwargs.get("输出格式", "png"), "image/png")},
            },
        }
        ratio = _gemini_ratio(kwargs.get("比例", kwargs.get("图像比例", "自动")))
        if ratio:
            generation_config["imageConfig"]["aspectRatio"] = ratio
        seed = int(kwargs.get("种子", 0) or 0)
        if seed > 0:
            generation_config["seed"] = seed
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": generation_config}
        model_name = kwargs.get("模型") or _model(kwargs.get("模型预设") or GEMINI_IMAGE_MODELS[0], kwargs.get("自定义模型", ""))
        root_url = kwargs.get("接口根地址") or os.environ.get("NTAPI_BASE_URL") or DEFAULT_ROOT_URL
        timeout_sec = int(kwargs.get("超时时间", 900))
        bypass_proxy = bool(kwargs.get("绕过代理", True))
        try:
            response = _request(
                "POST", _gemini_url(root_url, model_name), bypass_proxy,
                headers=_headers(api_key), json=body, timeout=(min(30, timeout_sec), timeout_sec)
            )
            payload = _json_response(response)
            images = _decode_image_candidates(payload, root_url, api_key, bypass_proxy, timeout_sec)
            result_format = "inlineData" if any(
                isinstance(part, dict) and ("inlineData" in part or "inline_data" in part)
                for candidate in payload.get("candidates", []) if isinstance(candidate, dict)
                for part in (candidate.get("content", {}).get("parts", []) if isinstance(candidate.get("content"), dict) else [])
            ) else "url"
            return (_stack_images(images), result_format)
        except requests.RequestException:
            raise RuntimeError("NTAPI：Gemini 请求失败或超时，请检查服务控制台；请勿立即重复提交。") from None


NODE_CLASS_MAPPINGS = {
    "NTAPIChatNode": NTAPIChatNode,
    "NTAPIOpenAIImageNode": NTAPIOpenAIImageNode,
    "NTAPIGeminiImageNode": NTAPIGeminiImageNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NTAPIChatNode": "NTAPI-语言模型",
    "NTAPIOpenAIImageNode": "NTAPI-GPT生图",
    "NTAPIGeminiImageNode": "NTAPI-Gemini生图",
}
