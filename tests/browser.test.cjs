const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html=fs.readFileSync('app/src/main/assets/index.html','utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const acorn=require(process.env.ACORN_PATH||'acorn');acorn.parse(source,{ecmaVersion:5});
const timers=[],requests=[],listeners={},elements={};
['video','fit','fill','touch','status'].forEach(id=>elements[id]={style:{},naturalWidth:600,naturalHeight:1000});
const video=elements.video;
video.getBoundingClientRect=()=>{const left=parseFloat(video.style.left),top=parseFloat(video.style.top),width=parseFloat(video.style.width),height=parseFloat(video.style.height);return {left,top,width,height,right:left+width,bottom:top+height};};
function XHR(){requests.push(this);this.open=(m,u)=>{this.method=m;this.url=u;};this.setRequestHeader=()=>{};this.send=b=>this.body=JSON.parse(b);}
const window={innerWidth:768,innerHeight:1024,addEventListener:(n,f)=>listeners[n]=f};
const document={hidden:false,getElementById:id=>elements[id],addEventListener:(n,f)=>listeners[n]=f};
vm.runInNewContext(source,{window,document,XMLHttpRequest:XHR,setTimeout:(f,t)=>timers.push({f,t}),setInterval:()=>{}});
assert.strictEqual(video.src,'/frame?n=0');assert.strictEqual(timers.length,0,'wait for image decoding');
video.onload();assert.strictEqual(video.style.height,'1024px');
const next=timers.shift();next.f();assert.strictEqual(video.src,'/frame?n=1');
elements.touch.onclick();
function touch(id,x,y){return {identifier:id,clientX:x,clientY:y};}
function event(a,ts){listeners[a]({target:video,changedTouches:ts,preventDefault:()=>{}});}
event('touchstart',[touch(1,384,512),touch(2,400,600)]);
assert.strictEqual(requests.length,1,'one input request at a time');
event('touchmove',[touch(1,420,550)]);event('touchmove',[touch(1,430,560)]);
event('touchend',[touch(1,430,560)]);event('touchcancel',[touch(2,400,600)]);
requests[0].readyState=4;requests[0].status=200;requests[0].onreadystatechange();
const batch=requests[1].body;
assert.deepStrictEqual(batch.map(e=>e.a),['down','move','up','cancel']);
assert.strictEqual(batch[0].id,1);assert.strictEqual(batch[2].id,0);assert.strictEqual(batch[3].id,1);
requests[1].readyState=4;requests[1].status=200;requests[1].onreadystatechange();
window.innerWidth=1024;window.innerHeight=768;listeners.resize();
assert.strictEqual(video.style.height,'768px');
const r=video.getBoundingClientRect();event('touchstart',[touch(3,r.left+10,r.top+10)]);
assert(requests[2].body[0].x>=0&&requests[2].body[0].x<=1);
listeners.pagehide();requests[2].readyState=4;requests[2].status=200;requests[2].onreadystatechange();
assert.strictEqual(requests[3].body[0].a,'cancel');
console.log('PASS: ES5 syntax, one-frame decode, serialized input, move coalescing, multitouch up/cancel, portrait/landscape mapping, pagehide');
