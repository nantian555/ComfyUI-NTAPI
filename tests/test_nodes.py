import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ntapi_test_plugin", ROOT / "__init__.py")
PLUGIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PLUGIN
SPEC.loader.exec_module(PLUGIN)
nodes = sys.modules[SPEC.name + ".nodes"]
KEY = "test-" + "credential-not-real"
BUFFER = io.BytesIO()
Image.new("RGB", (10, 8), (40, 120, 200)).save(BUFFER, format="PNG")
PNG = BUFFER.getvalue()
B64 = base64.b64encode(PNG).decode("ascii")


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


def defaults(cls):
    return {name: spec[1]["default"] for name, spec in cls.INPUT_TYPES()["required"].items()}


class NodeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"NTAPI_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def run_image(self, cls=nodes.NTAPIOpenAIImageNode, **values):
        return cls().run(**(defaults(cls) | {"API密钥": KEY, "提示词": "draw"} | values))

    def test_registration(self):
        self.assertEqual(len(PLUGIN.NODE_CLASS_MAPPINGS), 9 if 'NTAPISeedance20Node' in PLUGIN.NODE_CLASS_MAPPINGS else 7)
        for name, cls in PLUGIN.NODE_CLASS_MAPPINGS.items():
            self.assertTrue(name.startswith("NTAPI"))
            self.assertTrue(PLUGIN.NODE_DISPLAY_NAME_MAPPINGS[name].startswith("NTAPI-"))
            self.assertTrue(callable(getattr(cls(), cls.FUNCTION)))
            self.assertEqual(cls.CATEGORY, "NTAPI中转")

    def test_generation_defaults(self):
        with patch.object(nodes, "_request", return_value=response({"data": [{"b64_json": B64}]})) as send:
            image, = self.run_image()
        payload = send.call_args.kwargs["json"]
        self.assertEqual(type(payload["n"]), int)
        self.assertEqual(payload["quality"], "auto")
        self.assertEqual(payload["size"], "auto")
        self.assertEqual(payload["output_format"], "png")
        self.assertEqual(payload["response_format"], "url")
        self.assertNotIn("style", payload)
        self.assertEqual(tuple(image.shape), (1, 8, 10, 3))
        self.assertEqual(image.dtype, torch.float32)

    def test_explicit_options(self):
        with patch.object(nodes, "_request", return_value=response({"data": [{"b64_json": B64}]})) as send:
            self.run_image(**{"质量": "high", "风格": "natural", "返回格式": "b64_json", "数量": 2})
        payload = send.call_args.kwargs["json"]
        self.assertEqual((payload["quality"], payload["style"], payload["response_format"], payload["n"]), ("high", "natural", "b64_json", 2))

    def test_reference_batch(self):
        with patch.object(nodes, "_request", return_value=response({"data": [{"b64_json": B64}]})) as send:
            self.run_image(**{"参考图1": torch.rand(2, 3, 4, 3)})
        self.assertTrue(send.call_args.args[1].endswith("/images/edits"))
        self.assertEqual(len(send.call_args.kwargs["files"]), 2)
        self.assertNotIn("Content-Type", send.call_args.kwargs["headers"])

    def test_gemini_spellings(self):
        for spelling in ("inlineData", "inline_data"):
            payload = {"candidates": [{"content": {"parts": [{spelling: {"data": B64}}]}}]}
            with self.subTest(spelling=spelling), patch.object(nodes, "_request", return_value=response(payload)) as send:
                image, source = self.run_image(nodes.NTAPIGeminiImageNode, **{"接口根地址": "https://ntapi.org/v1", "比例": "16:9", "种子": 42})
                self.assertEqual(tuple(image.shape), (1, 8, 10, 3))
                self.assertEqual(source, "inlineData")
                self.assertIn("/v1beta/models/gemini-3-pro-image-preview:generateContent", send.call_args.args[1])
                config = send.call_args.kwargs["json"]["generationConfig"]
                self.assertEqual(config["imageConfig"]["aspectRatio"], "16:9")
                self.assertEqual(config["seed"], 42)

    def test_failures_raise_without_secret(self):
        bodies = [response({"error": {"message": KEY}}, 401), response({"error": {"message": KEY}}), response({"data": []}), response({"data": [{"b64_json": "invalid"}]}), response({"task_id": "queued-task", "status": "processing"})]
        bad_json = response({})
        bad_json._content = b"<html>gateway failure</html>"
        bodies.append(bad_json)
        for cls in (nodes.NTAPIOpenAIImageNode, nodes.NTAPIGeminiImageNode):
            for body in bodies:
                with self.subTest(node=cls.__name__, body=body.status_code), patch.object(nodes, "_request", return_value=body) as send:
                    with self.assertRaises(RuntimeError) as error:
                        self.run_image(cls)
                    self.assertNotIn(KEY, str(error.exception))
                    self.assertEqual(send.call_count, 1)

    def test_timeout_no_retry(self):
        with patch.object(nodes, "_request", side_effect=requests.Timeout(KEY)) as send:
            with self.assertRaises(RuntimeError) as error:
                self.run_image()
        self.assertEqual(send.call_count, 1)
        self.assertNotIn(KEY, str(error.exception))

    def test_missing_key(self):
        with patch.object(nodes, "_request") as send:
            with self.assertRaises(RuntimeError):
                self.run_image(**{"API密钥": ""})
            send.assert_not_called()

    def test_environment_key_chat_batch(self):
        args = defaults(nodes.NTAPIChatNode) | {"用户提示词": "describe", "参考图1": torch.ones(2, 3, 4, 3)}
        with patch.dict(os.environ, {"NTAPI_API_KEY": KEY}), patch.object(nodes, "_request", return_value=response({"choices": [{"message": {"content": [{"text": "hello"}]}}]})) as send:
            self.assertEqual(nodes.NTAPIChatNode().run(**args), ("hello",))
        self.assertEqual(send.call_args.kwargs["headers"]["Authorization"], "Bearer " + KEY)
        self.assertEqual(len(send.call_args.kwargs["json"]["messages"][1]["content"]), 3)

    def test_chat_error(self):
        args = defaults(nodes.NTAPIChatNode) | {"用户提示词": "hello", "API密钥": KEY}
        with patch.object(nodes, "_request", return_value=response({"error": {"message": KEY}}, 401)):
            with self.assertRaises(RuntimeError):
                nodes.NTAPIChatNode().run(**args)

    def test_download_credentials_same_origin(self):
        for url, auth in [("https://ntapi.org/image.png", True), ("https://cdn.example.org/image.png", False), ("https://ntapi.org:8443/image.png", False), ("http://ntapi.org/image.png", False)]:
            result = response({})
            result._content = PNG
            with self.subTest(url=url), patch.object(nodes, "_request", return_value=result) as send:
                nodes._decode_image_candidates({"data": [{"url": url}]}, "https://ntapi.org/v1", KEY, True)
                self.assertEqual("Authorization" in send.call_args.kwargs["headers"], auth)

    def test_metadata_not_downloaded(self):
        with patch.object(nodes, "_request") as send:
            nodes._decode_image_candidates({"documentation_url": "https://example.org/help", "data": [{"b64_json": B64}]}, nodes.DEFAULT_V1_URL, KEY, True)
            send.assert_not_called()

    def test_data_uri(self):
        images = nodes._decode_image_candidates({"data": [{"url": "data:image/png;base64," + B64}, {"b64_json": B64}]}, nodes.DEFAULT_V1_URL, KEY, True)
        self.assertEqual(len(images), 2)

    def test_example_workflows(self):
        paths = list((ROOT / "examples").glob("*-image.workflow.json"))
        self.assertEqual(len(paths), 2)
        for path in paths:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            source, sink = workflow["nodes"]
            cls = PLUGIN.NODE_CLASS_MAPPINGS[source["type"]]
            names = list(cls.INPUT_TYPES()["required"])
            has_control = cls.INPUT_TYPES()['required']['种子'][1].get('control_after_generate', False)
            self.assertEqual(len(source["widgets_values"]), len(names) + int(has_control))
            key_name = "API秘钥" if has_control else "API密钥"
            self.assertEqual(dict(zip(names, source["widgets_values"]))[key_name], "")
            self.assertEqual(sink["type"], "SaveImage")
            self.assertEqual(workflow["links"], [[1, source["id"], 0, sink["id"], 0, "IMAGE"]])

    def test_explicit_key_wins(self):
        with patch.dict(os.environ, {"NTAPI_API_KEY": "environment-test"}):
            self.assertEqual(nodes._api_key(KEY), KEY)

    def test_gpt_input_order_and_choices(self):
        inputs = nodes.NTAPIOpenAIImageNode.INPUT_TYPES()['required']
        self.assertEqual(list(inputs), ['提示词','API秘钥','模型','比例','分辨率','质量','风格','数量','输出格式','返回格式','绕过代理','超时时间','种子'])
        self.assertTrue(inputs['种子'][1]['control_after_generate'])
        self.assertEqual(inputs['质量'][0], ['auto','high','medium','low'])
        self.assertEqual(inputs['输出格式'][0], ['png','jpeg','webp'])
        self.assertEqual(inputs['返回格式'][0], ['url','b64_json'])

    def test_gemini_input_order_and_supported_fields(self):
        inputs = nodes.NTAPIGeminiImageNode.INPUT_TYPES()['required']
        self.assertEqual(list(inputs), ['提示词','API秘钥','模型','比例','分辨率','输出格式','绕过代理','超时时间','种子'])
        self.assertTrue(inputs['种子'][1]['control_after_generate'])
        self.assertEqual(inputs['模型'][0], nodes.GEMINI_IMAGE_MODELS)
        self.assertEqual(inputs['分辨率'][0], ['1K','2K','4K'])
        for field in ('质量','风格','数量','返回格式'):
            self.assertNotIn(field,inputs)

    def test_gemini_native_options_and_single_request(self):
        body = {'candidates':[{'content':{'parts':[{'inlineData':{'data':B64}}]}}]}
        with patch.dict(os.environ, {'NTAPI_BASE_URL':'https://example.org/v1'}), patch.object(nodes,'_request',return_value=response(body)) as send:
            self.run_image(nodes.NTAPIGeminiImageNode, **{'API秘钥':KEY,'模型':'gemini-3.1-flash-image-preview','比例':'9:16','分辨率':'4K','输出格式':'jpeg','超时时间':333,'种子':42})
        self.assertEqual(send.call_count,1)
        self.assertEqual(send.call_args.args[1], 'https://example.org/v1beta/models/gemini-3.1-flash-image-preview:generateContent')
        self.assertEqual(send.call_args.kwargs['timeout'],(30,333))
        payload=send.call_args.kwargs['json']
        self.assertEqual(payload['contents'][0]['parts'][0]['text'],'draw')
        config=payload['generationConfig']
        self.assertEqual(config['imageConfig'], {'aspectRatio':'9:16','imageSize':'4K','imageOutputOptions':{'mimeType':'image/jpeg'}})
        self.assertEqual(config['seed'],42)
        self.assertNotIn('style',payload)
        self.assertNotIn('n',payload)

    def test_gemini_zero_seed_auto_ratio(self):
        body={'candidates':[{'content':{'parts':[{'inline_data':{'data':B64}}]}}]}
        with patch.object(nodes,'_request',return_value=response(body)) as send:
            self.run_image(nodes.NTAPIGeminiImageNode)
        config=send.call_args.kwargs['json']['generationConfig']
        self.assertNotIn('seed',config)
        self.assertNotIn('aspectRatio',config['imageConfig'])

    def test_gpt_dimensions_and_auto(self):
        self.assertEqual(nodes._image_size('1:1','4k'), '2880x2880')
        self.assertEqual(nodes._image_size('16:9','4k'), '3840x2160')
        self.assertEqual(nodes._image_size('9:16','2k'), '1440x2560')
        self.assertEqual(nodes._image_size('21:9','2k'), '3024x1296')
        for ratio in nodes.IMAGE_RATIOS:
            for resolution in nodes.IMAGE_RESOLUTIONS:
                result = nodes._image_size(ratio,resolution)
                if ratio == 'auto':
                    self.assertEqual(result,'auto')
                else:
                    w,h = map(int,result.split('x'))
                    a,b = map(int,ratio.split(':'))
                    self.assertAlmostEqual(w/h,a/b)

    def test_gpt_new_parameters_json_and_multipart(self):
        for with_ref in (False, True):
            with self.subTest(edit=with_ref), patch.object(nodes, '_request', return_value=response({'data':[{'b64_json':B64}]})) as send:
                extra = {'参考图1':torch.ones(1,3,4,3)} if with_ref else {}
                self.run_image(**{'API秘钥':KEY,'模型':'gpt-image-2.5-flare','比例':'9:16','分辨率':'4k','输出格式':'webp','超时时间':321,'种子':123,**extra})
                fields = send.call_args.kwargs['data' if with_ref else 'json']
                self.assertEqual(fields['model'],'gpt-image-2.5-flare')
                self.assertEqual(fields['size'],'2160x3840')
                self.assertEqual(fields['output_format'],'webp')
                self.assertNotIn('seed',fields)
                self.assertEqual(send.call_args.kwargs['timeout'],(30,321))

    def test_gpt_download_timeout_and_environment_url(self):
        result = response({})
        result._content = PNG
        with patch.dict(os.environ, {'NTAPI_BASE_URL':'https://example.org/v1'}), patch.object(nodes,'_request',side_effect=[response({'data':[{'url':'https://cdn.example.org/image.png'}]}),result]) as send:
            self.run_image(**{'超时时间':222})
            self.assertEqual(send.call_args_list[0].args[1],'https://example.org/v1/images/generations')
            self.assertEqual(send.call_args_list[1].kwargs['timeout'],222)

    def test_transport_credentials(self):
        with patch.object(nodes.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            nodes._request("POST", "https://ntapi.org/v1/chat/completions", True, json={})
            self.assertFalse(session.trust_env)
            self.assertFalse(session.request.call_args.kwargs["allow_redirects"])
            nodes._request("POST", "https://ntapi.org/v1/chat/completions", False, json={})
            self.assertTrue(session.trust_env)
            with self.assertRaises(RuntimeError):
                nodes._request("POST", "http://ntapi.org/v1/chat/completions", True, headers=nodes._headers(KEY))


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                cls.seen.append((self.path, dict(self.headers), raw))
                if self.path == "/redirect":
                    self.send_response(307)
                    self.send_header("Location", "/unexpected")
                    body = b""
                else:
                    self.send_response(200)
                    body = json.dumps({"data": [{"b64_json": B64}]}).encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_bypass_all_proxy(self):
        with patch.dict(os.environ, {"ALL_PROXY": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            self.assertEqual(nodes._request("POST", self.url + "/v1/images/generations", True, json={"n": 1}, timeout=2).status_code, 200)

    def test_no_post_redirect(self):
        before = len(self.seen)
        self.assertEqual(nodes._request("POST", self.url + "/redirect", True, json={"prompt": "private"}, timeout=2).status_code, 307)
        self.assertEqual(len(self.seen), before + 1)

    def test_json_multipart(self):
        args = defaults(nodes.NTAPIOpenAIImageNode) | {"提示词": "test", "API密钥": KEY, "接口地址": self.url + "/v1"}
        nodes.NTAPIOpenAIImageNode().run(**args)
        self.assertEqual(type(json.loads(self.seen[-1][2])["n"]), int)
        args["参考图1"] = torch.ones(2, 3, 4, 3)
        nodes.NTAPIOpenAIImageNode().run(**args)
        path, headers, raw = self.seen[-1]
        self.assertEqual(path, "/v1/images/edits")
        self.assertIn("multipart/form-data; boundary=", headers["Content-Type"])
        self.assertEqual(raw.count(b'name="image[]"'), 2)


if __name__ == "__main__":
    unittest.main()
