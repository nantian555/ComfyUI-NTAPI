import { app } from "../../scripts/app.js";

const imageNodes = new Set(["NTAPIOpenAIImageNode", "NTAPIGeminiImageNode"]);
const dynamicReferences = new Set();
let pendingReferences = [];

app.registerExtension({
    name: "NTAPI.GPTImageParameters",
    beforeConfigureGraph(data) {
        pendingReferences = [];
        if (!dynamicReferences.size) return;
        const removed = new Set();
        for (const node of data.nodes || []) {
            if (!dynamicReferences.has(node.type)) continue;
            const refs = (node.inputs || []).filter(input => /^参考图(?:[1-9]|1[0-4])$/.test(input.name));
            if (!refs.length) continue;
            refs.sort((a, b) => Number(a.name.slice(3)) - Number(b.name.slice(3)));
            for (const input of refs) {
                if (input.link == null) continue;
                const link = (data.links || []).find(link => Array.isArray(link) ? link[0] === input.link : link.id === input.link);
                if (!link) continue;
                pendingReferences.push({target: node.id,
                    source: Array.isArray(link) ? link[1] : link.origin_id,
                    slot: Array.isArray(link) ? link[2] : link.origin_slot});
                removed.add(input.link);
            }
            node.inputs = (node.inputs || []).filter(input => !refs.includes(input));
        }
        data.links = (data.links || []).filter(link => !removed.has(Array.isArray(link) ? link[0] : link.id));
        for (const node of data.nodes || []) {
            for (const output of node.outputs || []) {
                if (output.links) output.links = output.links.filter(id => !removed.has(id));
            }
        }
    },
    afterConfigureGraph() {
        const next = new Map();
        for (const reference of pendingReferences) {
            const node = app.graph.getNodeById(reference.target);
            const source = app.graph.getNodeById(reference.source);
            const index = (next.get(reference.target) || 0) + 1;
            const slot = node?.findInputSlot(`参考图.参考图${index}`);
            if (source && node && slot >= 0) source.connect(reference.slot, node, slot);
            next.set(reference.target, index);
        }
        pendingReferences = [];
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!imageNodes.has(nodeData.name)) return;
        if (nodeData.input?.optional?.["参考图"]?.[0] === "COMFY_AUTOGROW_V3") dynamicReferences.add(nodeData.name);
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            const control = this.widgets?.find(w => w.name === "control_after_generate");
            if (control) control.label = "运行后控制";
            return result;
        };
        const configured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = configured?.apply(this, arguments);
            const old = info.widgets_values;
            if (nodeData.name === "NTAPIGeminiImageNode") {
                if (!Array.isArray(old) || old.length !== 9) return result;
                const names = ["提示词", "API秘钥", "模型", "比例", "分辨率", "输出格式", "绕过代理", "超时时间", "种子", "control_after_generate"];
                const values = [old[0], old[6], old[2] || old[1], old[4], old[3], "png", old[8], 900, old[5], "fixed"];
                for (const [index, name] of names.entries()) {
                    const widget = this.widgets?.find(w => w.name === name);
                    if (widget) widget.value = values[index];
                }
                const renamed = {"API密钥": "API秘钥", "模型预设": "模型", "图像比例": "比例", "图像尺寸": "分辨率"};
                for (const input of this.inputs || []) {
                    if (renamed[input.name]) {
                        input.name = renamed[input.name];
                        if (input.widget) input.widget.name = input.name;
                    }
                }
                if (old[7] && old[7] !== "https://ntapi.org") {
                    console.warn("NTAPI：旧 Gemini 自定义接口地址已移除，请在启动环境中设置 NTAPI_BASE_URL。");
                }
                return result;
            }
            // Convert the original 11-widget layout before it can misplace credentials.
            if (!Array.isArray(old) || old.length !== 11) return result;
            const ratio = { "1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3" }[old[3]] || "auto";
            const values = [old[0], old[8], old[2] || old[1], ratio, "1k",
                ["auto", "high", "medium", "low"].includes(old[4]) ? old[4] : "auto",
                old[5], old[6], "png", old[7] === "b64_json" ? "b64_json" : "url",
                old[10], 900, 0, "fixed"];
            const names = ["提示词", "API秘钥", "模型", "比例", "分辨率", "质量", "风格", "数量", "输出格式", "返回格式", "绕过代理", "超时时间", "种子", "control_after_generate"];
            for (const [index, name] of names.entries()) {
                const widget = this.widgets?.find(w => w.name === name);
                if (widget) widget.value = values[index];
            }
            const oldKey = this.inputs?.find(input => input.name === "API密钥");
            if (oldKey) {
                oldKey.name = "API秘钥";
                if (oldKey.widget) oldKey.widget.name = "API秘钥";
            }
            if (old[9] && old[9] !== "https://ntapi.org/v1") {
                console.warn("NTAPI：旧工作流的自定义接口地址已移除，请在启动环境中设置 NTAPI_BASE_URL。");
            }
            return result;
        };
    },
});
