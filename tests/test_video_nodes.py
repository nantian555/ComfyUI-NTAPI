import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import torch

from test_nodes import PLUGIN, KEY, defaults, response
import sys

video = sys.modules[PLUGIN.__name__ + ".video_nodes"]


class VideoTests(unittest.TestCase):
    def generate(self, mode, **extra):
        values = defaults(video.NTAPIVideoGenerateNode) | {"模式": mode, "提示词": "test", "API密钥": KEY} | extra
        return video.NTAPIVideoGenerateNode().run(**values)

    def test_generation_modes_and_order(self):
        first, last = torch.zeros(1, 3, 4, 3), torch.ones(1, 3, 4, 3)
        cases = [("文生视频", {}, 0, None), ("图生视频", {"首帧": first}, 1, "frame"),
                 ("首尾帧", {"首帧": first, "尾帧": last}, 2, "frame"),
                 ("多参考图", {"参考图批次": torch.cat((first, last, first))}, 3, "reference")]
        for mode, extra, count, kind in cases:
            with self.subTest(mode=mode), patch.object(video, "_request", return_value=response({"id": "task-1", "status": "queued"})) as send:
                self.assertEqual(self.generate(mode, **extra), ("task-1",))
                args = send.call_args
                self.assertTrue(args.args[1].endswith("/v1/videos"))
                data = args.kwargs["json"]
                self.assertEqual(len(data.get("images", [])), count)
                self.assertEqual(data.get("generation_type"), kind)
                if mode == "首尾帧":
                    self.assertNotEqual(data["images"][0], data["images"][1])

    def test_missing_inputs_no_request(self):
        with patch.object(video, "_request") as send:
            for mode in ("图生视频", "首尾帧", "多参考图"):
                with self.assertRaises(RuntimeError):
                    self.generate(mode)
            send.assert_not_called()

    def test_no_paid_retries(self):
        for result in (requests.Timeout(KEY), response({"error": KEY}, 503)):
            with patch.object(video, "_request", **({"side_effect": result} if isinstance(result, Exception) else {"return_value": result})) as send:
                with self.assertRaises(RuntimeError) as error:
                    self.generate("文生视频")
                self.assertEqual(send.call_count, 1)
                self.assertNotIn(KEY, str(error.exception))

    def test_edit_url_and_local_video(self):
        values = defaults(video.NTAPIVideoEditNode) | {"API密钥": KEY, "视频URL": "https://example.org/in.mp4"}
        with patch.object(video, "_request", return_value=response({"task_id": "edit-task"})) as send:
            video.NTAPIVideoEditNode().run(**values)
            self.assertEqual(send.call_args.kwargs["json"]["images"], [values["视频URL"]])
        class LocalVideo:
            def save_to(self, path, **options):
                Path(path).write_bytes(b"test video upload")
        def inspect_upload(*args, **kwargs):
            self.assertEqual(kwargs["files"][0][0], "input_reference")
            self.assertEqual(kwargs["files"][0][1][1].read(), b"test video upload")
            self.assertNotIn("Content-Type", kwargs["headers"])
            return response({"id": "local-task"})
        values.update({"视频URL": "", "原视频": LocalVideo()})
        with patch.object(video, "folder_paths", object()), patch.object(video, "Types", SimpleNamespace(VideoContainer=SimpleNamespace(MP4="mp4")), create=True), patch.object(video, "_request", side_effect=inspect_upload):
            self.assertEqual(video.NTAPIVideoEditNode().run(**values), ("local-task",))

    def fetch(self, **extra):
        return video.NTAPIVideoFetchNode().run(**(defaults(video.NTAPIVideoFetchNode) | {"API密钥": KEY, "任务ID": "task-1"} | extra))

    def test_query_completion_and_content_fallback(self):
        for body, suffix in [({"status": "completed"}, "/videos/task-1/content"),
                             ({"status": "succeeded", "result": {"url": "https://cdn.example.org/out.mp4"}}, "out.mp4")]:
            with patch.object(video, "_request", return_value=response(body)) as send, patch.object(video, "_download_video", return_value="video-object"):
                result, url = self.fetch()
                self.assertEqual(result, "video-object")
                self.assertTrue(url.endswith(suffix))
                self.assertEqual(send.call_args.args[0], "GET")

    def test_failure_unknown_and_timeout(self):
        for state in ("failed", "cancelled", "unexpected"):
            with patch.object(video, "_request", return_value=response({"status": state, "error": KEY if state == "failed" else None})):
                with self.assertRaises(RuntimeError) as error:
                    self.fetch()
                self.assertIn("task-1", str(error.exception))
                self.assertNotIn(KEY, str(error.exception))
        with patch.object(video.time, "monotonic", side_effect=[0, 2]), patch.object(video, "_request") as send:
            with self.assertRaisesRegex(RuntimeError, "等待超时"):
                self.fetch(**{"最大等待秒数": 1})
            send.assert_not_called()

    def test_pending_then_completed(self):
        replies = [response({"status": "queued"}), response({"status": "completed"})]
        clock = iter([0, 0, 0, 0, 0, 10, 10, 10])
        with patch.object(video, "_request", side_effect=replies) as send, patch.object(video.time, "monotonic", side_effect=lambda: next(clock)), patch.object(video, "_download_video", return_value="video"):
            self.assertEqual(self.fetch()[0], "video")
            self.assertEqual(send.call_count, 2)

    def test_task_path_boundary(self):
        for task in ("", "..", "../other", "x?key=secret", "x\ny"):
            with self.assertRaises(RuntimeError):
                video._task_id(task)

    def test_query_http_error_keeps_id(self):
        with patch.object(video, "_request", return_value=response({"error": KEY}, 401)):
            with self.assertRaises(RuntimeError) as error:
                self.fetch()
            self.assertIn("task-1", str(error.exception))
            self.assertNotIn(KEY, str(error.exception))

    def test_video_examples(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / 'examples').glob('video-*.workflow.json'):
            workflow = json.loads(path.read_text(encoding='utf-8'))
            source, fetch, save = workflow['nodes']
            for node in (source, fetch):
                cls = PLUGIN.NODE_CLASS_MAPPINGS[node['type']]
                values = dict(zip(cls.INPUT_TYPES()['required'], node['widgets_values']))
                self.assertEqual(values['API密钥'], '')
            self.assertEqual(save['type'], 'SaveVideo')
            self.assertEqual(workflow['links'], [[1,1,0,2,0,'STRING'], [2,2,0,3,0,'VIDEO']])

    def test_download_cleanup_and_credentials(self):
        class Stream:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_content(self, **options): yield b"video bytes"
        class Decoded:
            def __init__(self, path): self.path = path
            def get_dimensions(self): return (16, 16)
        with tempfile.TemporaryDirectory() as directory, patch.object(video, "folder_paths", SimpleNamespace(get_temp_directory=lambda: directory)), patch.object(video, "throw_exception_if_processing_interrupted", create=True), patch.object(video, "InputImpl", SimpleNamespace(VideoFromFile=Decoded), create=True):
            for address, has_key in [("https://ntapi.org/v1/videos/x/content", True), ("https://cdn.example.org/a.mp4", False)]:
                with patch.object(video, "_request", return_value=Stream()) as send:
                    result = video._download_video(address, "https://ntapi.org/v1", KEY, True)
                    self.assertEqual(Path(result.path).read_bytes(), b"video bytes")
                    self.assertEqual("Authorization" in send.call_args.kwargs["headers"], has_key)
                    Path(result.path).unlink()
            with patch.object(video, "_request", return_value=Stream()) as send, patch.object(Decoded, "get_dimensions", side_effect=ValueError("bad video")):
                with self.assertRaisesRegex(RuntimeError,'读取视频'):
                    video._download_video("https://cdn.example.org/a.mp4", "https://ntapi.org/v1", KEY, True)
                self.assertEqual(list(Path(directory).iterdir()), [])
                send.assert_called_once()

    def test_download_retries_get_and_discards_partial_files(self):
        class Stream:
            status_code=200
            def __init__(self,broken=False): self.broken=broken
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def iter_content(self,**kwargs):
                yield b'partial' if self.broken else b'complete video'
                if self.broken: raise requests.exceptions.ChunkedEncodingError(KEY)
        class Decoded:
            def __init__(self,path): self.path=path
            def get_dimensions(self): return (16,16)
        with tempfile.TemporaryDirectory() as directory, patch.object(video,'folder_paths',SimpleNamespace(get_temp_directory=lambda:directory)), patch.object(video,'throw_exception_if_processing_interrupted',create=True), patch.object(video,'InputImpl',SimpleNamespace(VideoFromFile=Decoded),create=True), patch.object(video.time,'sleep'):
            with patch.object(video,'_request',side_effect=[Stream(True),Stream()]) as send:
                result=video._download_video('https://cdn.example.org/a.mp4','https://ntapi.org/v1',KEY,True)
            self.assertEqual(Path(result.path).read_bytes(),b'complete video')
            self.assertEqual(len(list(Path(directory).iterdir())),1)
            self.assertEqual(send.call_count,2)
            self.assertTrue(all(call.args[0]=='GET' and call.kwargs['headers']=={} for call in send.call_args_list))

    def test_download_retry_limit_and_local_failures_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(video,'folder_paths',SimpleNamespace(get_temp_directory=lambda:directory)), patch.object(video,'throw_exception_if_processing_interrupted',create=True), patch.object(video.time,'sleep'):
            with patch.object(video,'_request',side_effect=requests.ConnectionError(KEY)) as send:
                with self.assertRaisesRegex(RuntimeError,'下载连接') as error:
                    video._download_video('https://cdn.example.org/a.mp4?secret=yes','https://ntapi.org/v1',KEY,True)
            self.assertEqual(send.call_count,3)
            self.assertNotIn(KEY,str(error.exception))
            self.assertNotIn('secret=yes',str(error.exception))
            self.assertEqual(list(Path(directory).iterdir()),[])
            rejected=response({},403)
            rejected._content_consumed=True
            with patch.object(video,'_request',return_value=rejected) as send:
                with self.assertRaisesRegex(RuntimeError,'HTTP 403'):
                    video._download_video('https://cdn.example.org/a.mp4','https://ntapi.org/v1',KEY,True)
            send.assert_called_once()
            completed=response({})
            completed._content_consumed=True
            with patch.object(video,'_request',return_value=completed) as send, patch.object(video.tempfile,'NamedTemporaryFile',side_effect=PermissionError(KEY)):
                with self.assertRaisesRegex(RuntimeError,'保存视频') as error:
                    video._download_video('https://cdn.example.org/a.mp4','https://ntapi.org/v1',KEY,True)
            send.assert_called_once()
            self.assertNotIn(KEY,str(error.exception))


if __name__ == "__main__":
    unittest.main()
