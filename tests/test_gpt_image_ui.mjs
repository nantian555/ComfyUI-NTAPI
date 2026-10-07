import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

let extension;
const graphNodes = new Map();
const source = readFileSync(new URL('../web/gpt_image.js', import.meta.url), 'utf8');
vm.runInNewContext(source.replace(/^import .*;\r?\n/, ''), {
    app: { registerExtension(value) { extension = value; }, graph: {getNodeById(id) { return graphNodes.get(id); }} }, console,
});
class Node {}
await extension.beforeRegisterNodeDef(Node, {name:'NTAPIOpenAIImageNode'});
const names = ['提示词','API秘钥','模型','比例','分辨率','质量','风格','数量','输出格式','返回格式','绕过代理','超时时间','种子','control_after_generate'];
const node = new Node();
node.widgets = names.map(name => ({name,value:null}));
node.inputs = [{name:'API密钥',widget:{name:'API密钥'}}];
node.onNodeCreated();
assert.equal(node.widgets.at(-1).label,'运行后控制');
const old = ['test prompt','gpt-image-2','','1536x1024','服务默认','服务默认',1,'url','test-only-key','https://ntapi.org/v1',true];
node.onConfigure({widgets_values:old});
assert.equal(node.widgets[1].value,'test-only-key');
assert.equal(node.widgets[3].value,'3:2');
assert.equal(node.widgets[5].value,'auto');
assert.equal(node.widgets.at(-1).value,'fixed');
assert.equal(node.inputs[0].name,'API秘钥');
assert.equal(node.widgets.filter(w=>w.value==='test-only-key').length,1);
const before = node.widgets.map(w=>w.value);
node.onConfigure({widgets_values:before});
assert.deepEqual(node.widgets.map(w=>w.value), before);
console.log('GPT UI label, old layout migration and credential position: OK');

class DynamicNode {}
await extension.beforeRegisterNodeDef(DynamicNode, {name:'NTAPIOpenAIImageNode', input:{optional:{'参考图':['COMFY_AUTOGROW_V3',{}]}}});
class GeminiNode {}
await extension.beforeRegisterNodeDef(GeminiNode, {name:'NTAPIGeminiImageNode', input:{optional:{'参考图':['COMFY_AUTOGROW_V3',{}]}}});
const gemini=new GeminiNode();
const geminiNames=['提示词','API秘钥','模型','比例','分辨率','输出格式','绕过代理','超时时间','种子','control_after_generate'];
gemini.widgets=geminiNames.map(name=>({name,value:null}));
gemini.inputs=[{name:'API密钥',widget:{name:'API密钥'}},{name:'图像比例',widget:{name:'图像比例'}}];
gemini.onNodeCreated();
gemini.onConfigure({widgets_values:['draw','gemini-3-pro-image-preview','','4K','16:9',123,'test-gemini-key','https://ntapi.org',false]});
assert.deepEqual(gemini.widgets.map(w=>w.value),['draw','test-gemini-key','gemini-3-pro-image-preview','16:9','4K','png',false,900,123,'fixed']);
assert.equal(gemini.widgets.at(-1).label,'运行后控制');
assert.equal(gemini.inputs[0].name,'API秘钥');
assert.equal(gemini.inputs[1].name,'比例');
assert.equal(gemini.widgets.filter(w=>w.value==='test-gemini-key').length,1);
assert.equal(gemini.widgets.some(w=>['质量','数量','风格','返回格式'].includes(w.name)),false);
const geminiBefore=gemini.widgets.map(w=>w.value);
gemini.onConfigure({widgets_values:geminiBefore});
assert.deepEqual(gemini.widgets.map(w=>w.value),geminiBefore);
console.log('Gemini layout, native-only fields and credential migration: OK');
for (const type of ['NTAPIOpenAIImageNode','NTAPIGeminiImageNode']) {
for (const count of [0,1,14]) {
    const refs=Array.from({length:14},(_,i)=>({name:`参考图${i+1}`,link:i<count?i+1:null}));
    const fixture={nodes:[{id:1,type,inputs:refs},{id:2,type:'EmptyImage',outputs:[{links:Array.from({length:count},(_,i)=>i+1)}]}],links:Array.from({length:count},(_,i)=>[i+1,2,0,1,i,'IMAGE'])};
    extension.beforeConfigureGraph(fixture);
    assert.equal(fixture.nodes[0].inputs.length,0);
    assert.equal(fixture.links.length,0);
    const target={names:['参考图.参考图1'],findInputSlot(name){return this.names.indexOf(name);}};
    const connected=[];
    graphNodes.set(1,target);
    graphNodes.set(2,{connect(sourceSlot,node,slot){connected.push(slot);if(node.names.length<14)node.names.push(`参考图.参考图${node.names.length+1}`);}});
    extension.afterConfigureGraph();
    assert.equal(connected.length,count);
    assert.equal(target.names.length,Math.min(14,count+1));
    assert.deepEqual(connected,Array.from({length:count},(_,i)=>i));
}
}
console.log('Old 0/1/14 reference links reconnect in order through native inputs: OK');
