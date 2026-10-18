/* Deterministic browser regression checks over the built dashboard. No live data or credentials.
   Build dashboard-ui first. Set PLAYWRIGHT_MODULE if Playwright is installed outside this repo. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../app/dashboard/static/dashboard');
const origin=process.env.GH2_ASSET_ORIGIN||'http://gh2-layout.test';
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const spaces=[{id:'personal',name:'Personal',can_write:true},{id:'long',name:'An exceptionally long space name for layout regression checks',can_write:true}];
 const memory=(i,body,extra={})=>({id:'fixture-'+i,title:'Memory '+i,body,summary:'',space_id:'personal',record_type:'fact',version:1,updated_at:'2026-10-18T12:00:00Z',...extra});
 const memories=[memory(1,'Short.'),memory(2,'A long paragraph of saved context. '.repeat(50)),memory(3,'X'.repeat(2000)),memory(4,'Body',{summary:'A long summary. '.repeat(100),title:'An extremely long title '.repeat(20)}),memory(5,'Short.',{space_id:'long',record_type:'profile',stale:true}),memory(6,'Long content '.repeat(80),{space_id:'long',record_type:'profile',stale:true})];
 let login={state:'idle',message:'Not signing in'},authenticated=true;
 let config={enabled:false,space_ids:['personal'],frequency:'daily',weekday:0,hour:3,minute:0,timezone:'Europe/London',model:'saved-unlisted-model',reasoning:'low',batch_size:20,timeout_seconds:180,max_context_chars:60000,execution_policy:'review'};
 let saved;
 let proposals=[],jobs=[];
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  const json=data=>route.fulfill({json:data});
  if(p.startsWith('/dashboard-assets/')){if(process.env.GH2_ASSET_ORIGIN)return route.continue();const file=path.join(root,p.slice('/dashboard-assets/'.length));const type=file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/plain';return route.fulfill({path:file,contentType:type});}
  if(p==='/dashboard/api/session')return json({has_admin:true,user:{id:'fixture-user',username:'UI regression'}});
  if(p==='/api/v2/capabilities')return json({spaces,default_space_id:'personal'});
  if(p==='/dashboard/api/categories')return json([{id:'general',name:'General'}]);
  if(p==='/api/v2/memories')return json({memories});
  if(p==='/api/v2/secrets')return json({secrets:[{id:'long-secret',name:'LONG_UNBROKEN_SECRET_IDENTIFIER_'.repeat(5),description:'Connection metadata description '.repeat(12),provider:'builtin',space_id:'personal',value_type:'password',version:1,updated_at:'2026-10-18T12:00:00Z'}],value_types:['password']});
  if(p==='/dashboard/api/advanced/settings'){if(req.method()==='PUT'){saved=req.postDataJSON();config={...config,...saved};}return json(config);}
  if(p==='/dashboard/api/advanced/status')return json({installed:true,authenticated,auth_mode:authenticated?'chatgpt':null,worker_running:true,login,models:[{id:'',label:'Account default'},{id:'model-small',label:'Small model'},{id:'model-large',label:'Large model'}],reasoning_levels:['low','medium','high']});
  if(p==='/dashboard/api/advanced/jobs')return json({jobs});
  if(p==='/dashboard/api/activity')return json({events:[]});
  if(p.startsWith('/dashboard/api/advanced/jobs/'))return json({id:'job-one',state:'completed',result:'Fixture review finished'});
  if(p.endsWith('/approve')){proposals=proposals.map(x=>x.id===p.split('/').at(-2)?{...x,state:'applied'}:x);return json({status:'applied'});}
  if(p==='/dashboard/api/advanced/proposals/pending-count')return json({count:proposals.filter(x=>['pending','proposed'].includes(x.state)&&x.payload.operation!=='question').length});
  if(p==='/dashboard/api/advanced/proposals')return json({proposals});
  if(req.isNavigationRequest()&&process.env.GH2_ASSET_ORIGIN)return route.continue();
  if(req.isNavigationRequest())return route.fulfill({path:path.join(root,'index.html'),contentType:'text/html'});
  throw Error('Unexpected request '+p);
 });
 for(const width of[1500,900,768,390]){
  await page.setViewportSize({width,height:1050});await page.goto(origin+'/dashboard/memories');await page.locator('.resource-row').nth(5).waitFor();
  const boxes=await page.locator('.resource-row').evaluateAll(rows=>rows.map(row=>{const r=row.getBoundingClientRect(),m=row.querySelector('.memory-metadata').getBoundingClientRect(),d=row.querySelector('.memory-updated').getBoundingClientRect();return{x:m.x,width:m.width,dateX:d.x,dateHeight:d.height,dateOffset:d.y-r.y}}));
  if(width>740){for(const box of boxes){assert.equal(box.width,260);assert.equal(box.x,boxes[0].x);assert.equal(box.dateHeight,boxes[0].dateHeight);}for(const i of[1,2,3])assert.equal(boxes[i].dateOffset,boxes[0].dateOffset);assert.equal(boxes[4].dateOffset,boxes[5].dateOffset);}
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page overflow at '+width);
  if(process.env.UI_SCREENSHOT_DIR){fs.mkdirSync(process.env.UI_SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.UI_SCREENSHOT_DIR,'memories-'+width+'.png'),fullPage:true});}
 }
 await page.goto(origin+'/dashboard/settings');await page.getByText('Connected',{exact:true}).waitFor();assert.equal(await page.getByText('Not signing in',{exact:true}).count(),0);await page.getByText('Idle',{exact:true}).waitFor();
 const model=page.getByLabel('Codex model',{exact:true}),reasoning=page.getByLabel('Reasoning level',{exact:true});
 assert.equal(await model.evaluate(e=>e.tagName),'SELECT');assert.equal(await reasoning.evaluate(e=>e.tagName),'SELECT');assert.equal(await model.inputValue(),'saved-unlisted-model');assert.equal(await model.locator('option[value="[object Object]"]').count(),0);
 await model.selectOption('model-small');await reasoning.selectOption('medium');await page.getByRole('button',{name:'Save settings',exact:true}).click();await page.getByText('Advanced Memory settings saved.',{exact:true}).waitFor();assert.equal(saved.model,'model-small');assert.equal(saved.reasoning,'medium');await page.reload();await model.waitFor();assert.equal(await model.inputValue(),'model-small');
 authenticated=false;login={state:'pending',message:'Finish sign-in in your browser',url:'https://auth.openai.com/codex/device',code:'DEMO-CODE'};await page.reload();await page.getByText('Finish sign-in in your browser',{exact:true}).waitFor();await page.getByRole('link',{name:'Open official sign-in page ↗'}).waitFor();await page.getByText('DEMO-CODE',{exact:true}).waitFor();
 login={state:'failed',message:'Sign-in expired; try again'};await page.reload();await page.getByText('Sign-in expired; try again',{exact:true}).waitFor();
 authenticated=true;login={state:'idle',message:'Not signing in'};
 proposals=[{id:'proposal-one',state:'pending',payload:{operation:'profile',title:'Update a profile',body:'Confirmed updated profile'},reason:'New source information'},{id:'proposal-two',state:'proposed',payload:{operation:'move',destination_space_id:'personal'},reason:'Confirmed personal context'},{id:'proposal-question',state:'pending',payload:{operation:'question'},reason:'Needs clarification'},{id:'proposal-done',state:'applied',payload:{operation:'profile'},reason:'Already applied'}];
 jobs=[{id:'job-one',state:'completed',created_at:'2026-10-18T12:00:00Z'}];
 await page.goto(origin+'/dashboard/settings');await page.getByLabel('Enable Advanced Memory',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:/^Memory reviews/}).count(),0);assert.equal(await page.getByRole('heading',{name:'Proposed improvements',exact:true}).count(),0);assert.equal(await page.getByRole('heading',{name:'Run history',exact:true}).count(),0);
 await page.getByLabel('Enable Advanced Memory',{exact:true}).check();await page.getByRole('button',{name:'Save settings',exact:true}).click();await page.getByRole('button',{name:'Memory reviews 2 awaiting approval',exact:true}).waitFor();await page.getByRole('button',{name:'Memory reviews 2 awaiting approval',exact:true}).click();await page.getByRole('heading',{name:'Memory reviews',exact:true}).waitFor();await page.getByRole('heading',{name:'Proposed improvements',exact:true}).waitFor();await page.getByRole('heading',{name:'Run history',exact:true}).waitFor();await page.getByRole('button',{name:'Approve',exact:true}).first().click();await page.getByRole('button',{name:'Memory reviews 1 awaiting approval',exact:true}).waitFor();await page.getByRole('button',{name:'Details',exact:true}).click();await page.getByRole('dialog',{name:'Run details',exact:true}).waitFor();await page.keyboard.press('Escape');
 for(const width of[1500,768,390]){await page.setViewportSize({width,height:1050});await page.goto(origin+'/dashboard/memory-reviews');await page.getByRole('heading',{name:'Proposed improvements',exact:true}).waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Review page overflow '+width);if(process.env.UI_SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.UI_SCREENSHOT_DIR,'reviews-'+width+'.png'),fullPage:true});}
 await page.goto(origin+'/dashboard/settings');await page.getByLabel('Enable Advanced Memory',{exact:true}).uncheck();await page.getByRole('button',{name:'Save settings',exact:true}).click();await page.getByRole('button',{name:/^Memory reviews/}).waitFor({state:'hidden'});await page.goto(origin+'/dashboard/activity');await page.getByLabel('Filter activity by actor',{exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'Proposed improvements',exact:true}).count(),0);
 for(const width of[1500,768,390]){await page.setViewportSize({width,height:1050});await page.goto(origin+'/dashboard/secrets');await page.getByText('LONG_UNBROKEN_SECRET_IDENTIFIER_'.repeat(5),{exact:true}).waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Long secret identifier overflow '+width);}
 assert.deepEqual(errors,[]);
 console.log('PASS: memory layout; sign-in states; model/reasoning persistence; conditional Memory reviews navigation, approval-only badge, approval/count refresh, run details and Settings/Activity separation.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
