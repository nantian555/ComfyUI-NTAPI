import { app } from "../../scripts/app.js";

function labelReference(input) {
    const match = /^(参考图|参考视频|参考音频)\.\1(_?)(\d+)$/.exec(input.name);
    if (!match) return;
    // Keep the native names used for execution; only change the visible label.
    const label = match[1] + (Number(match[3]) + (match[2] ? 1 : 0));
    Object.defineProperty(input, "label", {
        configurable: true, enumerable: true,
        get: () => label,
        set: () => {},
    });
}

function syncSeedanceDuration(node) {
    const duration = node.widgets?.find(widget => widget.name === "时长秒数");
    if (!duration) return;
    const multimodal = node.widgets.some(widget => widget.name === "模式" && widget.value === "多模态参考");
    const hasVideo = node.inputs?.some(input => input.name.startsWith("参考视频.") && input.link != null);
    duration.disabled = Boolean(multimodal && hasVideo);
    if (duration.disabled) duration.value = -1;
    node.setDirtyCanvas?.(true);
}

function migrateSeedance25Model(node) {
    const model = node.widgets?.find(widget => widget.name === "模型");
    if (!model || typeof model.value !== "string") return;
    const match = /^seedance-2\.5-(?:global-)?standard-(t2v|i2v|multi)$/.exec(model.value);
    if (match) model.value = `seedance2.5${match[1]}`;
}

app.registerExtension({
    name: "NTAPI.ReferenceLabels",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!nodeData.name.startsWith("NTAPI")) return;
        const addInput = nodeType.prototype.addInput;
        nodeType.prototype.addInput = function () {
            const input = addInput.apply(this, arguments);
            if (input) labelReference(input);
            return input;
        };
        for (const event of ["onNodeCreated", "onConfigure", "onConnectionsChange"]) {
            const previous = nodeType.prototype[event];
            nodeType.prototype[event] = function () {
                const result = previous?.apply(this, arguments);
                for (const input of this.inputs || []) labelReference(input);
                if (nodeData.name === "NTAPISeedance25Node") {
                    migrateSeedance25Model(this);
                    syncSeedanceDuration(this);
                }
                return result;
            };
        }
        if (!["NTAPISeedance20Node", "NTAPISeedance25Node"].includes(nodeData.name)) return;
        const configured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = configured?.apply(this, arguments);
            const old = info.widgets_values;
            if (Array.isArray(old) && old.length === 14) {
                const values = [...old.slice(0, 12), 1800, 5, ...old.slice(12)];
                for (const [index, widget] of this.widgets.entries()) widget.value = values[index];
            }
            if (nodeData.name === "NTAPISeedance25Node") {
                migrateSeedance25Model(this);
                syncSeedanceDuration(this);
            }
            return result;
        };
        if (nodeData.name === "NTAPISeedance25Node") {
            const created = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = created?.apply(this, arguments);
                const mode = this.widgets?.find(widget => widget.name === "模式");
                if (mode) {
                    const callback = mode.callback;
                    const node = this;
                    mode.callback = function () {
                        const result = callback?.apply(this, arguments);
                        syncSeedanceDuration(node);
                        return result;
                    };
                }
                return result;
            };
        }
    },
});
