import io
import json
import sys
import tempfile
import unittest
import wave
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import requests
import torch

from test_nodes import PLUGIN, KEY, response

seedance = sys.modules[PLUGIN.__name__ + '.seedance_nodes']
video = sys.modules[PLUGIN.__name__ + '.video_nodes']
IMAGE = torch.ones(1, 4, 6, 3)


def values(**kwargs):
    return {'API秘钥':KEY, '接口根地址':'https://example.org/v1', '提示词':'hello',
            '比例':'16:9', '分辨率':'720p', '时长秒数':5, '生成音频':True,
            '绕过代理':True, '超时时间':75, '种子':123, **kwargs}


class SeedanceTests(unittest.TestCase):
    def test_official_site_uses_api_host(self):
        for root in ('https://ntapi.org','https://ntapi.org/v1','https://www.ntapi.org/v1','https://api.ntapi.org/v1'):
            self.assertEqual(seedance._root({'接口根地址':root}),'https://api.ntapi.org')
        self.assertEqual(seedance._root({'接口根地址':'https://relay.example.org/v1'}),'https://relay.example.org')

    def test_seedance_aliases_map_to_svideo(self):
        modes={'文生视频':'t2v','首尾帧':'i2v','多模态参考':'multi'}
        tiers={seedance.MODELS_20[0]:'standard',seedance.MODELS_20[1]:'fast',seedance.MODELS_20[2]:'mini'}
        for alias,tier in tiers.items():
            for mode,suffix in modes.items():
                with self.subTest(alias=alias,mode=mode):
                    self.assertEqual(seedance._model_id(values(模型=alias,模式=mode),'2.0'),f'Svideo-2.0-{tier}-{suffix}')
        for alias, suffix in zip(seedance.MODELS_25, ('t2v', 'i2v', 'multi')):
            mode={'t2v':'文生视频','i2v':'首尾帧','multi':'多模态参考'}[suffix]
            with self.subTest(alias=alias):
                self.assertEqual(seedance._model_id(values(模型=alias,模式=mode),'2.5'),f'Svideo-2.5-standard-{suffix}')
        for alias in seedance.MODELS_25_LEGACY:
            suffix=alias.rsplit('-',1)[-1]
            mode={'t2v':'文生视频','i2v':'首尾帧','multi':'多模态参考'}[suffix]
            with self.subTest(alias=alias):
                self.assertEqual(seedance._model_id(values(模型=alias,模式=mode),'2.5'),f'Svideo-2.5-standard-{suffix}')
        self.assertEqual(seedance._model_id(values(自定义模型='Svideo-private-model'),'2.0'),'Svideo-private-model')

    def test_text_protocols(self):
        for protocol in ('2.0','2.5'):
            with self.subTest(protocol=protocol), patch.object(seedance,'_request',return_value=response({'id':'task-1'})) as send:
                self.assertEqual(seedance.submit_seedance(values(),protocol),('task-1',))
                call=send.call_args
                payload=call.kwargs['json']
                self.assertEqual(call.kwargs['timeout'],(30,75))
                self.assertEqual(call.kwargs['headers']['Authorization'],'Bearer '+KEY)
                self.assertEqual(call.args[1],'https://example.org/v1/videos')
                # Svideo 1.1.0 rejects fields outside this request contract.
                self.assertEqual(payload,{'model':f'Svideo-{protocol}-standard-t2v',
                    'prompt':'hello','seconds':'5','metadata':{'resolution':'720p',
                    'ratio':'16:9','generate_audio':True,'seed':123}})

    def test_20_frames_upload_order(self):
        replies=[response({'url':'https://cdn.example.org/first.png'}),response({'url':'https://cdn.example.org/last.png'}),response({'task_id':'t'})]
        with patch.object(seedance,'_request',side_effect=replies) as send:
            seedance.submit_seedance(values(模式='首尾帧', 首帧=IMAGE, 尾帧=IMAGE*0),'2.0')
            self.assertEqual(send.call_count,3)
            payload=send.call_args.kwargs['json']
            self.assertEqual(payload['images'],['https://cdn.example.org/first.png','https://cdn.example.org/last.png'])
            self.assertNotIn('messages',payload)
            self.assertNotIn('content',payload['metadata'])
            self.assertTrue(all(call.args[1].endswith('/v1/svideo/files') for call in send.call_args_list[:2]))
            self.assertTrue(all(call.kwargs['data']=={'model':'Svideo-2.0-standard-i2v'} for call in send.call_args_list[:2]))

    def test_25_frames_upload_order_and_duration(self):
        replies=[response({'url':'https://cdn.example.org/first.png'}), response({'url':'https://cdn.example.org/last.png'}),response({'id':'t'})]
        with patch.object(seedance,'_request',side_effect=replies) as send:
            seedance.submit_seedance(values(模式='首尾帧', 模型=seedance.MODELS_25[1], 首帧=IMAGE, 尾帧=IMAGE, 时长秒数=-1),'2.5')
        self.assertEqual(send.call_count,3)
        self.assertEqual(send.call_args_list[0].args[1],'https://example.org/v1/svideo/files')
        payload=send.call_args.kwargs['json']
        self.assertEqual(payload['images'],['https://cdn.example.org/first.png','https://cdn.example.org/last.png'])
        self.assertEqual(payload['metadata']['ratio'],'adaptive')
        self.assertEqual(payload['metadata']['duration'],-1)
        self.assertNotIn('seconds',payload)

    def test_multimodal_upload_and_audio_batches(self):
        class Video:
            def save_to(self,path,**kwargs):
                Path(path).write_bytes(b'test mp4')
        for protocol in ('2.0','2.5'):
            uploads=[]
            payloads=[]
            def server(method,url,bypass,**kwargs):
                if 'files' in kwargs:
                    self.assertEqual(kwargs['data'],{'model':f'Svideo-{protocol}-standard-multi'})
                    filename,file,mime=kwargs['files'][0][1]
                    raw=file.read()
                    self.assertNotIn('Content-Type',kwargs['headers'])
                    if mime=='audio/wav':
                        with wave.open(io.BytesIO(raw),'rb') as wav:
                            self.assertEqual(wav.getnchannels(),2)
                            self.assertEqual(wav.getframerate(),8000)
                            self.assertEqual(wav.getnframes(),16)
                    uploads.append((url,filename))
                    return response({'url':'https://cdn.example.org/'+str(len(uploads))})
                payloads.append(kwargs['json'])
                return response({'id':'t'})
            with self.subTest(protocol=protocol), patch.object(seedance,'_request',side_effect=server):
                seedance.submit_seedance(values(模式='多模态参考', 时长秒数=-1, 模型=seedance.MODELS_25[2] if protocol=='2.5' else seedance.MODELS_20[0],
                    参考图={'参考图_1':torch.zeros(2,4,6,3)}, 参考视频={'参考视频_0':Video()},
                    参考音频={'参考音频_0':{'waveform':torch.ones(2,2,16), 'sample_rate':8000}}),protocol)
            media=payloads[0]['metadata']['content']
            self.assertEqual([part['type'] for part in media],['image_url','image_url','video_url','audio_url','audio_url'])
            self.assertEqual(len(uploads),5)
            self.assertTrue(all(url.endswith('/v1/svideo/files') for url,_ in uploads))
            self.assertEqual([part[part['type']]['url'] for part in media],
                             [f'https://cdn.example.org/{i}' for i in range(1,6)])
            self.assertTrue(all(set(part)=={'type',part['type']} for part in media))
            self.assertNotIn('images',payloads[0])
            self.assertNotIn('messages',payloads[0])

    def test_25_video_edit_keeps_required_automatic_duration_protocol(self):
        image={'type':'image_url','image_url':{'url':'https://cdn.example.org/ref.png'}}
        video_ref={'type':'video_url','video_url':{'url':'https://cdn.example.org/ref.mp4'}}
        audio={'type':'audio_url','audio_url':{'url':'https://cdn.example.org/ref.wav'}}
        for protocol,media,editing in [('2.5',[image,video_ref,audio],True),
                                       ('2.5',[image,audio],False),('2.0',[video_ref],False)]:
            model=seedance.MODELS_25[2] if protocol=='2.5' else seedance.MODELS_20[0]
            with self.subTest(protocol=protocol,editing=editing), patch.object(seedance,'_media_content',return_value=media), patch.object(seedance,'_request',return_value=response({'id':'task'})) as send:
                seedance.submit_seedance(values(模型=model,模式='多模态参考',比例='9:16',时长秒数=8),protocol)
            payload=send.call_args.kwargs['json']
            self.assertEqual(payload['metadata']['content'],media)
            self.assertEqual(payload['metadata']['ratio'],'adaptive' if editing else '9:16')
            if editing:
                self.assertEqual(payload['metadata']['duration'],-1)
                self.assertNotIn('seconds',payload)
            else:
                self.assertEqual(payload['seconds'],'8')
                self.assertNotIn('duration',payload['metadata'])
            send.assert_called_once()

    def test_25_reference_video_always_submits_automatic_duration(self):
        media = [{'type':'video_url','video_url':{'url':'https://cdn.example.org/ref.mp4'}}]
        for duration in (4, 5, 30):
            with self.subTest(duration=duration), patch.object(seedance, '_media_content', return_value=media) as prepare, patch.object(seedance, '_request', return_value=response({'id':'task'})) as send:
                seedance.submit_seedance(values(模型=seedance.MODELS_25[2], 模式='多模态参考',
                    时长秒数=duration, 参考图={'参考图_0':IMAGE}, 参考视频={'参考视频_0':object()}), '2.5')
                prepare.assert_called_once()
                send.assert_called_once()
                payload = send.call_args.kwargs['json']
                self.assertNotIn('seconds', payload)
                self.assertEqual(payload['metadata']['duration'], -1)
                self.assertEqual(payload['metadata']['content'], media)

    def test_video_edit_http_error_is_actionable_without_echoing_body(self):
        error={'code':'invalid_video_edit_parameters','message':KEY}
        for body in (error,{'error':error},{'code':'fail_to_fetch_task','message':json.dumps(error),'data':None}):
            with self.subTest(body=body), patch.object(seedance,'_request',return_value=response(body,400)) as send:
                with self.assertRaisesRegex(RuntimeError,'adaptive') as failure:
                    seedance.submit_seedance(values(),'2.5')
            self.assertIn('-1',str(failure.exception))
            self.assertNotIn(KEY,str(failure.exception))
            send.assert_called_once()

    def test_usage_validation_error_reports_server_side_requirement(self):
        body={'code':'plugin_usage_invalid','message':KEY,'data':None}
        with patch.object(seedance,'_request',return_value=response(body,400)) as send:
            with self.assertRaisesRegex(RuntimeError,'服务端计费参数校验') as error:
                seedance.submit_seedance(values(),'2.5')
        self.assertNotIn(KEY,str(error.exception))
        send.assert_called_once()

    def test_no_retries_and_no_credential_errors(self):
        for reply in (requests.Timeout(KEY),response({'error':KEY},401),response({'url':'not-a-url'})):
            kwargs={'side_effect':reply} if isinstance(reply,Exception) else {'return_value':reply}
            with patch.object(seedance,'_request',**kwargs) as send:
                with self.assertRaises(RuntimeError) as error:
                    seedance.submit_seedance(values(模式='首尾帧', 模型=seedance.MODELS_25[1], 首帧=IMAGE),'2.5')
                self.assertNotIn(KEY,str(error.exception))
                self.assertEqual(send.call_count,1)

    def test_validation_before_upload(self):
        with patch.object(seedance,'_request') as send:
            for protocol,args in [('2.0',values(模式='首尾帧')),('2.5',values(模式='首尾帧',模型=seedance.MODELS_25[0],首帧=IMAGE))]:
                with self.assertRaises(RuntimeError): seedance.submit_seedance(args,protocol)
            send.assert_not_called()

    def test_custom_model_and_no_seed(self):
        with patch.object(seedance,'_request',return_value=response({'id':'t'})) as send:
            seedance.submit_seedance(values(自定义模型='custom-seedance',种子=-1),'2.0')
            payload=send.call_args.kwargs['json']
            self.assertEqual(payload['model'],'custom-seedance')
            self.assertNotIn('seed',payload)

    def test_native_fetch_endpoint_and_content(self):
        with patch.object(video,'_request',return_value=response({'status':'succeeded','video_url':'https://cdn.example.org/out.mp4'})) as send, patch.object(video,'_download_video',return_value='VIDEO'):
            result=seedance.NTAPISeedance20FetchNode().run(**{'任务ID':'task-1','API密钥':KEY,'接口根地址':'https://example.org'})
            self.assertEqual(result,('VIDEO','https://cdn.example.org/out.mp4'))
            self.assertEqual(send.call_args.args[:2],('GET','https://example.org/v1/videos/task-1'))

    def test_one_node_submission_query_and_video(self):
        for protocol in ('2.0','2.5'):
            done={'status':'completed','metadata':{'url':'https://cdn.example.org/out.mp4'}}
            with self.subTest(protocol=protocol), patch.object(seedance,'_request',return_value=response({'id':'task-1'})) as submit, patch.object(video,'_request',return_value=response(done)) as query, patch.object(video,'_download_video',return_value='native-video'):
                self.assertEqual(seedance.generate_seedance(values(),protocol),('native-video','https://cdn.example.org/out.mp4'))
                self.assertEqual(submit.call_count,1)
                self.assertEqual(submit.call_args.args[0],'POST')
                self.assertEqual(query.call_count,1)
                self.assertEqual(query.call_args.args[0],'GET')
                self.assertIn('/v1/videos/',query.call_args.args[1])

    def test_transport_errors_are_actionable_and_secret_safe(self):
        failures=[(requests.Timeout(KEY),'超时'),(requests.exceptions.ProxyError(KEY),'代理'),
                  (requests.exceptions.SSLError(KEY),'TLS'),(requests.ConnectionError(KEY),'连接在请求期间被中断')]
        for failure,word in failures:
            with self.subTest(kind=type(failure).__name__), patch.object(seedance,'_request',side_effect=failure) as send:
                with self.assertRaises(RuntimeError) as error:
                    seedance.submit_seedance(values(),'2.0')
                self.assertIn(word,str(error.exception))
                self.assertNotIn(KEY,str(error.exception))
                self.assertEqual(send.call_count,1)

    def test_connection_error_reports_safe_cause_and_host(self):
        inner=ConnectionResetError(KEY)
        failure=requests.ConnectionError(requests.packages.urllib3.exceptions.ProtocolError('safe',inner))
        with patch.object(seedance,'_request',side_effect=failure):
            with self.assertRaises(RuntimeError) as error:
                seedance.submit_seedance(values(),'2.0')
        message=str(error.exception)
        self.assertIn('ConnectionError',message)
        self.assertIn('ProtocolError',message)
        self.assertIn('ConnectionResetError',message)
        self.assertIn('host=example.org',message)
        self.assertNotIn(KEY,message)

    def test_upload_disconnect_stops_before_video_submission(self):
        failure=requests.ConnectionError(requests.packages.urllib3.exceptions.ProtocolError(
            'safe',ConnectionResetError(KEY)))
        with patch.object(seedance,'_request',side_effect=failure) as send:
            with self.assertRaises(RuntimeError) as error:
                seedance.submit_seedance(values(模式='首尾帧',首帧=IMAGE),'2.0')
        message=str(error.exception)
        self.assertIn('素材上传',message)
        self.assertIn('视频生成尚未提交',message)
        self.assertNotIn('是否已有任务',message)
        self.assertNotIn(KEY,message)
        self.assertEqual(send.call_count,1)
        self.assertEqual(send.call_args.args[1],'https://example.org/v1/svideo/files')

    def test_missing_upload_route_explains_server_update(self):
        with patch.object(seedance,'_request',return_value=response({},404)) as send:
            with self.assertRaisesRegex(RuntimeError,'配套服务端更新'):
                seedance.submit_seedance(values(模式='首尾帧',首帧=IMAGE),'2.0')
        self.assertEqual(send.call_count,1)

    def test_suppressed_urllib3_context_is_not_reported_as_a_cause(self):
        inner=ConnectionResetError(KEY)
        inner.__context__=TypeError('legacy getresponse(buffering=True)')
        inner.__suppress_context__=True
        failure=requests.ConnectionError(requests.packages.urllib3.exceptions.ProtocolError('safe',inner))
        with patch.object(seedance,'_request',side_effect=failure):
            with self.assertRaises(RuntimeError) as error:
                seedance.submit_seedance(values(),'2.0')
        self.assertIn('ConnectionResetError',str(error.exception))
        self.assertNotIn('TypeError',str(error.exception))

    def test_html_response_reports_wrong_api_path(self):
        bad=response({})
        bad._content=b'<!doctype html><html></html>'
        with patch.object(seedance,'_request',return_value=bad):
            with self.assertRaisesRegex(RuntimeError,'非 JSON'):
                seedance.submit_seedance(values(),'2.0')

    def test_one_node_timeout_retains_task_without_resubmit(self):
        with patch.object(seedance,'submit_seedance',return_value=('recover-1',)) as submit, patch.object(seedance.NTAPISeedance20FetchNode,'run',side_effect=RuntimeError('等待超时')) as fetch:
            with self.assertRaisesRegex(RuntimeError,'recover-1'):
                seedance.generate_seedance(values(最大等待秒数=17,轮询间隔秒数=2),'2.0')
            self.assertEqual(submit.call_count,1)
            self.assertEqual(fetch.call_args.kwargs['最大等待秒数'],17)
            self.assertEqual(fetch.call_args.kwargs['轮询间隔秒数'],2)

    def test_review_rejection_shows_reason_without_resume_advice(self):
        body={'status':'failed','error':{'code':'1501','message':KEY}}
        with patch.object(seedance,'submit_seedance',return_value=('failed-task',)) as submit, patch.object(video,'_request',return_value=response(body)) as query:
            with self.assertRaises(RuntimeError) as error:
                seedance.generate_seedance(values(),'2.0')
        message=str(error.exception)
        self.assertIn('1501',message)
        self.assertIn('内容未通过合规审核',message)
        self.assertIn('可能涉及版权限制',message)
        self.assertIn('不能续取',message)
        self.assertNotIn('可在控制台或任务获取节点续取',message)
        self.assertNotIn(KEY,message)
        self.assertEqual(message.count('failed-task'),1)
        submit.assert_called_once()
        query.assert_called_once()


    @unittest.skipIf(seedance.io is None,'Requires native ComfyUI')
    def test_native_autogrow_schemas(self):
        for name,counts in [('NTAPISeedance20Node',[9,3,3]),('NTAPISeedance25Node',[30,10,10])]:
            inputs=seedance.NODE_CLASS_MAPPINGS[name].INPUT_TYPES()
            self.assertEqual(tuple(seedance.NODE_CLASS_MAPPINGS[name].RETURN_TYPES),('VIDEO','STRING'))
            for label,maximum in zip(('参考图','参考视频','参考音频'),counts):
                template=inputs['optional'][label][1]['template']
                self.assertEqual(template['min'],0)
                self.assertEqual(template['max'],maximum)

    @unittest.skipIf(seedance.io is None,'Requires native ComfyUI')
    def test_25_model_menu_uses_three_short_aliases(self):
        inputs = seedance.NODE_CLASS_MAPPINGS['NTAPISeedance25Node'].INPUT_TYPES()
        self.assertEqual(inputs['required']['模型'][1]['options'], seedance.MODELS_25)
        self.assertEqual(seedance.MODELS_25, ['seedance2.5t2v', 'seedance2.5i2v', 'seedance2.5multi'])

    @unittest.skipIf(seedance.io is None,'Requires native ComfyUI')
    def test_examples_and_matching_fetch_nodes(self):
        root=Path(__file__).resolve().parents[1]
        for name,kind,fetch in [('seedance20','NTAPISeedance20Node','NTAPISeedance20FetchNode'),('seedance25','NTAPISeedance25Node','NTAPIVideoFetchNode')]:
            graph=json.loads((root/'examples'/f'{name}.workflow.json').read_text(encoding='utf-8'))
            source,save=graph['nodes']
            self.assertEqual(source['type'],kind)
            self.assertEqual(save['type'],'SaveVideo')
            args=dict(zip(PLUGIN.NODE_CLASS_MAPPINGS[kind].INPUT_TYPES()['required'],source['widgets_values']))
            self.assertEqual(args['API秘钥'],'')
            self.assertEqual(args['模式'],'文生视频')
            self.assertEqual(graph['links'],[[1,1,0,3,0,'VIDEO']])


@unittest.skipIf(seedance.io is None, 'Requires native ComfyUI')
class ReferenceDurationTests(unittest.TestCase):
    def make_video(self, path, seconds, with_audio=True):
        frames = seconds * 24
        images = torch.zeros(frames, 16, 16, 3)
        images[:, :, :, 0] = torch.linspace(0, 1, frames)[:, None, None]
        audio = None
        if with_audio:
            samples = torch.arange(seconds * 24000)
            tone = torch.sin(samples * (2 * torch.pi * 440 / 24000)) * 0.2
            audio = {'sample_rate': 24000, 'waveform': tone.repeat(1, 2, 1)}
        source = video.InputImpl.VideoFromComponents(video.Types.VideoComponents(
            images=images, audio=audio, frame_rate=Fraction(24)))
        source.save_to(str(path), format='mp4')
        return video.InputImpl.VideoFromFile(str(path))

    def test_uploads_keep_reference_duration_and_version_specific_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original.mp4'
            for protocol, seconds in [('2.5', 8), ('2.5', 2), ('2.0', 8), ('2.0', 2)]:
                source = self.make_video(path, seconds)
                original = path.read_bytes()
                expected = source.get_components()
                uploads = []
                def server(method, url, bypass, **kwargs):
                    if 'files' in kwargs:
                        raw = kwargs['files'][0][1][1].read()
                        uploaded = video.InputImpl.VideoFromFile(io.BytesIO(raw))
                        self.assertAlmostEqual(uploaded.get_duration(), seconds, delta=0.002)
                        components = uploaded.get_components()
                        self.assertEqual(len(components.images), seconds * 24)
                        self.assertTrue(torch.equal(components.images, expected.images))
                        self.assertEqual(components.audio['waveform'].shape[1], 2)
                        self.assertEqual(components.audio['sample_rate'], 24000)
                        self.assertTrue(torch.equal(components.audio['waveform'], expected.audio['waveform']))
                        uploads.append(raw)
                        return response({'url': 'https://cdn.example.org/prepared.mp4'})
                    self.assertEqual(len(uploads), 1)
                    payload = kwargs['json']
                    if protocol == '2.5':
                        self.assertNotIn('seconds', payload)
                        self.assertEqual(payload['metadata']['duration'], -1)
                    else:
                        self.assertEqual(payload['seconds'], '4')
                        self.assertNotIn('duration', payload['metadata'])
                    return response({'id': 'duration-test'})
                with self.subTest(protocol=protocol, seconds=seconds), patch.object(seedance, '_request', side_effect=server) as send:
                    seedance.submit_seedance(values(模式='多模态参考', 时长秒数=4, 模型=seedance.MODELS_25[2] if protocol=='2.5' else seedance.MODELS_20[0],
                        参考视频={'参考视频_0': source}), protocol)
                    self.assertEqual(send.call_count, 2)
                    self.assertEqual(path.read_bytes(), original)

    def test_preserves_input_trim_and_automatic_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_video(Path(directory) / 'original.mp4', 8, with_audio=False)
            trimmed = source.as_trimmed(5, 2)
            def upload(args, protocol, file, filename, mime):
                prepared = video.InputImpl.VideoFromFile(io.BytesIO(file.read()))
                self.assertAlmostEqual(prepared.get_duration(), 2, delta=0.002)
                components = prepared.get_components()
                self.assertIsNone(components.audio)
                self.assertGreater(components.images[0, :, :, 0].mean().item(), 0.5)
                return 'https://cdn.example.org/reference.mp4'
            for duration in (4, -1):
                with self.subTest(duration=duration), patch.object(seedance, '_upload', side_effect=upload) as send:
                    seedance._media_content(values(模式='多模态参考', 时长秒数=duration,
                        参考视频={'参考视频_0':trimmed}), '2.5')
                    send.assert_called_once()

    def test_export_failure_prevents_upload_and_submission(self):
        class BrokenVideo:
            def save_to(self, path, **kwargs):
                raise RuntimeError('export failed')
        with patch.object(seedance, '_request') as send:
            with self.assertRaisesRegex(RuntimeError, 'export failed'):
                seedance.submit_seedance(values(模式='多模态参考', 模型=seedance.MODELS_20[0],
                    参考视频={'参考视频_0': BrokenVideo()}), '2.0')
            send.assert_not_called()


if __name__=='__main__':
    unittest.main()
