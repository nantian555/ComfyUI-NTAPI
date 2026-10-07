from .nodes import (CATEGORY_NAME, NTAPIGeminiImageNode as GeminiRequest,
                    NTAPIOpenAIImageNode as ImageRequest)

try:
    from comfy_api.latest import io
except ImportError:
    io = None


NODE_CLASS_MAPPINGS = {}

if io is not None:
    def _image_schema(request, node_id, display_name):
        inputs = []
        for name, (kind, options) in request.INPUT_TYPES()["required"].items():
            if isinstance(kind, list):
                inputs.append(io.Combo.Input(name, options=kind, **options))
            else:
                input_type = {"STRING": io.String, "INT": io.Int, "BOOLEAN": io.Boolean}[kind]
                inputs.append(input_type.Input(name, **options))
        inputs.append(io.Autogrow.Input(
            "参考图",
            template=io.Autogrow.TemplateNames(io.Image.Input("image"),
                                               names=[f"参考图{i}" for i in range(1, 15)], min=0),
            optional=True,
        ))
        outputs = [io.Image.Output(display_name="图像")]
        if request is GeminiRequest:
            outputs.append(io.String.Output(display_name="结果格式"))
        return io.Schema(node_id=node_id, display_name=display_name,
                         category=CATEGORY_NAME, inputs=inputs, outputs=outputs)

    class NTAPIOpenAIImageNode(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return _image_schema(ImageRequest, "NTAPIOpenAIImageNode", "NTAPI-GPT生图")

        @classmethod
        def execute(cls, 参考图=None, **values):
            return io.NodeOutput(*ImageRequest().run(**values, **(参考图 or {})))

    NODE_CLASS_MAPPINGS["NTAPIOpenAIImageNode"] = NTAPIOpenAIImageNode

    class NTAPIGeminiImageNode(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return _image_schema(GeminiRequest, "NTAPIGeminiImageNode", "NTAPI-Gemini生图")

        @classmethod
        def execute(cls, 参考图=None, **values):
            return io.NodeOutput(*GeminiRequest().run(**values, **(参考图 or {})))

    NODE_CLASS_MAPPINGS["NTAPIGeminiImageNode"] = NTAPIGeminiImageNode
