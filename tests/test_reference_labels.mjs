import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

let extension;
const source=readFileSync(new URL('../web/reference_labels.js',import.meta.url),'utf8');
vm.runInNewContext(source.replace(/^import .*;\r?\n/,''),{app:{registerExtension(value){extension=value;}}});
for (const type of ['NTAPISeedance20Node','NTAPISeedance25Node','NTAPIOpenAIImageNode','NTAPIGeminiImageNode']) {
    class Node { addInput(name,type) { const slot={name,type}; (this.inputs??=[]).push(slot);return slot;} }
    extension.beforeRegisterNodeDef(Node,{name:type});
    const node=new Node();
    for (const [name,label] of [['参考图.参考图1','参考图1'],['参考图.参考图14','参考图14'],['参考图.参考图_0','参考图1'],['参考视频.参考视频_1','参考视频2'],['参考音频.参考音频_9','参考音频10']]) {
        const slot=node.addInput(name,'IMAGE');
        assert.equal(slot.name,name);
        assert.equal(slot.label,label);
        slot.label=name;
        assert.equal(slot.label,label);
    }
    const loaded={name:'参考视频.参考视频_0',type:'VIDEO',link:42};
    node.inputs.push(loaded);
    node.onConfigure({widgets_values:[]});
    assert.equal(loaded.label,'参考视频1');
    assert.equal(loaded.link,42);
    if(type.startsWith('NTAPISeedance')) {
        node.widgets=Array.from({length:16},()=>({value:0}));
        const old=['prompt','test-key','model','','文生视频','16:9','720p',5,true,'https://ntapi.org',true,900,123,'fixed'];
        node.onConfigure({widgets_values:old});
        assert.deepEqual(node.widgets.map(w=>w.value),[...old.slice(0,12),1800,5,123,'fixed']);
    }
}
for (const type of ['NTAPISeedance20Node','NTAPISeedance25Node']) {
    class Node {
        constructor() {
            this.inputs=[{name:'参考视频.参考视频_0',link:null}];
            this.widgets=[{name:'模型',value:'seedance-2.5-global-standard-multi'}, {name:'模式',value:'多模态参考',callback(){return 'previous';}}, {name:'时长秒数',value:4}];
        }
        addInput() {}
    }
    extension.beforeRegisterNodeDef(Node,{name:type});
    const node=new Node();
    node.onNodeCreated();
    const [model,mode,duration]=node.widgets;
    if(type==='NTAPISeedance25Node') assert.equal(model.value,'seedance2.5multi');
    assert.equal(duration.value,4);
    node.inputs[0].link=42;
    node.onConnectionsChange();
    assert.equal(duration.value,type==='NTAPISeedance25Node'?-1:4);
    assert.equal(Boolean(duration.disabled),type==='NTAPISeedance25Node');
    if(type==='NTAPISeedance25Node') {
        mode.value='文生视频';
        assert.equal(mode.callback(),'previous');
        assert.equal(duration.disabled,false);
        duration.value=8;
        mode.value='多模态参考';mode.callback();
        assert.equal(duration.value,-1);
        node.inputs[0].link=null;node.onConnectionsChange();
        assert.equal(duration.disabled,false);
        node.inputs[0].link=42;duration.value=4;
        node.onConfigure({widgets_values:[]});
        assert.equal(duration.value,-1);
        assert.equal(duration.disabled,true);
    }
}
console.log('NTAPI reference labels, migration and Seedance 2.5 automatic duration UI: OK');
