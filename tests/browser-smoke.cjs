const {chromium}=require('playwright');
const {spawn}=require('child_process');
const path=require('path');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('timers/promises');
const root=path.resolve(__dirname,'..');
const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8767','--no-access-log'],{
  cwd:root,env:{...process.env,ECG_API_KEY:'',ECG_CORS_ORIGINS:'http://localhost:5173'},stdio:['ignore','ignore','pipe']});
let browser;
(async()=>{
  for(let i=0;i<100;i++){
    try{const r=await fetch('http://127.0.0.1:8767/health');if(r.ok)break;}catch{}
    if(i===99)throw new Error('Servidor não iniciou');
    await delay(100);
  }
  browser=await chromium.launch({...(process.env.ECG_BROWSER_EXECUTABLE?{executablePath:process.env.ECG_BROWSER_EXECUTABLE}:{}),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'],headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8767');
  const component=page.locator('ecg-viewer');
  assert.equal(await component.isVisible(),false);
  assert.equal(await page.locator('#record').inputValue(),'1');
  await page.locator('#file').setInputFiles(process.env.ECG_TEST_FILE || path.join(root,'examples/synthetic.wxml'));
  assert.equal(await page.locator('#record').inputValue(),'1');
  await page.locator('#record').fill('');
  await page.locator('#submit').click();
  assert.equal(await page.locator('#record').inputValue(),'1');
  await page.waitForFunction(()=>document.querySelector('ecg-viewer').ready,{timeout:30000});
  await component.scrollIntoViewIfNeeded();
  assert.equal(await component.isVisible(),true);
  assert.match(await page.locator('#status').innerText(),/Baixar/);
  const state=()=>page.evaluate(()=>{
    const v=document.querySelector('ecg-viewer');const img=v.image.getBoundingClientRect();
    return {zoom:v.zoom,width:img.width,height:img.height,aspect:v.aspect,left:v.viewport.scrollLeft,top:v.viewport.scrollTop,
      clientWidth:v.viewport.clientWidth,scrollWidth:v.viewport.scrollWidth,src:v.image.src,complete:v.image.complete};
  });
  const fit=await state();assert.equal(fit.zoom,1);assert.ok(fit.complete);assert.ok(fit.src.startsWith('blob:'));
  await page.evaluate(()=>document.querySelector('ecg-viewer').setZoom(4));
  const enlarged=await state();assert.equal(enlarged.zoom,4);
  assert.ok(Math.abs(enlarged.width/enlarged.height-fit.width/fit.height)<.00001);
  assert.ok(Math.abs(enlarged.width/enlarged.clientWidth-4)<.001);
  assert.ok(enlarged.scrollWidth>enlarged.clientWidth*3.9);
  const vp=component.locator('.viewport');const rect=await vp.boundingBox();
  await page.mouse.move(rect.x+300,rect.y+140);await page.mouse.down();
  await page.mouse.move(rect.x+190,rect.y+80,{steps:6});await page.mouse.up();
  const dragged=await state();assert.ok(dragged.left>enlarged.left+90);
  await page.evaluate(()=>document.querySelector('ecg-viewer').setZoom(16));
  assert.equal((await state()).zoom,16);
  await component.getByRole('button',{name:'Ajustar largura'}).click();
  assert.equal((await state()).zoom,1);
  assert.equal((await state()).left,0);
  await page.evaluate(()=>document.querySelector('ecg-viewer').viewport.focus());
  await page.keyboard.press('+');assert.ok((await state()).zoom>1);
  await page.keyboard.press('0');assert.equal((await state()).zoom,1);
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(200);
  await component.scrollIntoViewIfNeeded();
  await component.getByRole('button',{name:'Aumentar zoom'}).click();
  assert.ok((await state()).zoom>1);
  await page.setViewportSize({width:1280,height:1000});
  await page.selectOption('#format','pdf');
  assert.equal(await page.locator('#layout').inputValue(),'reference');
  await page.locator('#submit').click();
  await page.locator('#preview iframe').waitFor({timeout:30000});
  assert.equal(await component.isVisible(),false);
  const cors=await page.request.fetch('http://127.0.0.1:8767/convert?format=svg',{
    method:'OPTIONS',headers:{Origin:'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-API-Key'}});
  assert.equal(cors.status(),200);assert.equal(cors.headers()['access-control-allow-origin'],'http://localhost:5173');
  await page.locator('#record').fill('2');
  await page.locator('#file').setInputFiles(path.join(root,'examples/synthetic.wxml'));
  assert.equal(await page.locator('#record').inputValue(),'1');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({browser:browser.version(),passed:['upload WXML','SVG blob no navegador','proporção de zoom','zoom 400% e 1600%','arraste','ajuste largura','teclado','mobile','exportação PDF','CORS'],pageErrors:errors}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();server.kill('SIGTERM');
});
