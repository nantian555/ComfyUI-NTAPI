import unittest
from unittest.mock import patch

import torch

from test_nodes import PLUGIN, nodes
import sys

dynamic = sys.modules[PLUGIN.__name__ + '.gpt_autogrow']


@unittest.skipIf(dynamic.io is None, 'Native Autogrow tests require a ComfyUI runtime')
class AutogrowTests(unittest.TestCase):
    def test_optional_fourteen_named_slots(self):
        for name in ('NTAPIOpenAIImageNode','NTAPIGeminiImageNode'):
            cls = dynamic.NODE_CLASS_MAPPINGS[name]
            inputs = cls.INPUT_TYPES()
            self.assertEqual(list(inputs['required']), list(nodes.NODE_CLASS_MAPPINGS[name].INPUT_TYPES()['required']))
            kind, options = inputs['optional']['参考图']
            self.assertEqual(kind, 'COMFY_AUTOGROW_V3')
            self.assertEqual(options['template']['names'], [f'参考图{i}' for i in range(1,15)])
            self.assertEqual(options['template']['min'], 0)

    def test_empty_and_full_execution(self):
        image = torch.ones(1,2,2,3)
        for name in ('NTAPIOpenAIImageNode','NTAPIGeminiImageNode'):
            cls = dynamic.NODE_CLASS_MAPPINGS[name]
            expected = (image,'inlineData') if name == 'NTAPIGeminiImageNode' else (image,)
            self.assertEqual(tuple(cls.RETURN_TYPES), ('IMAGE','STRING') if len(expected)==2 else ('IMAGE',))
            for count in (0,1,14):
                refs = {f'参考图{i}':image for i in range(1,count+1)}
                with self.subTest(node=name,count=count), patch.object(nodes.NODE_CLASS_MAPPINGS[name],'run',return_value=expected) as run:
                    cls.execute(参考图=refs, 提示词='test')
                    self.assertEqual(len(run.call_args.kwargs),count+1)
                    self.assertEqual(run.call_args.kwargs['提示词'],'test')


if __name__ == '__main__':
    unittest.main()
