/* Live-provider UI contract exercised with synthetic values only. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/opt/google/chrome/chrome',args:['--no-sandbox']});
 try{
  const page=await browser.newPage(),errors=[],calls=[];page.on('pageerror',e=>errors.push(e.message));
  const root=path.resolve(__dirname,'../app/dashboard/static/dashboard');
  let config={enabled:false,configured:true,server_url:'https://vault.example.test',write_enabled:true,default_folder_id:null,client_id_configured:true,client_secret_configured:true,master_password_configured:true};
  const folders=[{id:'home',name:'Home Network'},{id:'work',name:'Luxury Leisure'}];
  const secret={id:'vw:account:existing',name:'Existing login',provider:'vaultwarden',direct:true,folder_id:'home',folder_name:'Home Network',fields:['login.username','login.password','notes'],default_field:'login.password',version:'opaque-revision',value_type:'password'};
  await page.route('**/*',async route=>{
   const req=route.request(),p=new URL(req.url()).pathname,json=data=>route.fulfill({json:data});
   if(p.startsWith('/dashboard-assets/')){const file=path.join(root,p.slice('/dashboard-assets/'.length));return route.fulfill({path:file,contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'image/png'});}
   if(p==='/dashboard/api/session')return json({has_admin:true,user:{id:'fixture',username:'Test'}});
   if(p==='/dashboard/api/advanced/settings')return json({enabled:false});
   if(p==='/dashboard/api/providers/secrets'){
    if(req.method()==='PUT'){config={...config,...req.postDataJSON()};calls.push({action:'settings',payload:req.postDataJSON()});}
    return json(config);
   }
   if(p==='/dashboard/api/providers/secrets/test'){calls.push({action:'test'});return json({status:'unlocked',folder_count:2});}
   if(p==='/dashboard/api/providers/secrets/folders'||p==='/api/v2/secrets/folders')return json({supported:true,folders});
   if(p==='/api/v2/secrets'){
    if(req.method()==='POST')calls.push({action:'create',payload:req.postDataJSON()});
    return json(req.method()==='POST'?secret:{active_provider:'vaultwarden',secrets:[secret],value_types:['password','text']});
   }
   if(p==='/api/v2/secrets/vw%3Aaccount%3Aexisting/reveal'||p==='/api/v2/secrets/vw:account:existing/reveal'){calls.push({action:'reveal',payload:req.postDataJSON()});return json({name:secret.name,value:'synthetic-explicit-value',expires_in_seconds:60});}
   if(p==='/api/v2/secrets/vw%3Aaccount%3Aexisting'||p==='/api/v2/secrets/vw:account:existing'){calls.push({action:'edit',payload:req.postDataJSON()});return json(secret);}
   if(req.isNavigationRequest())return route.fulfill({path:path.join(root,'index.html'),contentType:'text/html'});
   throw Error('Unexpected API '+req.method()+' '+p);
  });
  await page.goto('http://gh2-ui.test/dashboard/settings#secrets');
  await page.getByRole('heading',{name:'Optional default folder',exact:true}).waitFor();
  assert.equal(await page.getByText('Folder mapping',{exact:true}).count(),0);
  assert.equal(await page.getByText('Link an existing vault item',{exact:true}).count(),0);
  await page.getByRole('button',{name:'Test saved connection',exact:true}).click();
  await page.getByText('Vault connection and unlock succeeded.',{exact:true}).waitFor();
  await page.getByLabel('Enable external secret provider').check();
  await page.getByRole('button',{name:'Load vault folders',exact:true}).click();
  await page.getByLabel('Default folder for new secrets',{exact:true}).selectOption('home');
  await page.getByRole('button',{name:'Save provider settings',exact:true}).click();
  await page.getByText('Secret provider settings saved.',{exact:true}).waitFor();
  assert.equal(calls.find(x=>x.action==='settings').payload.default_folder_id,'home');
  for(const width of [1500,768,390]){
   await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Settings overflow '+width);
   if(process.env.UI_SCREENSHOT_DIR){fs.mkdirSync(process.env.UI_SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.UI_SCREENSHOT_DIR,'secret-settings-'+width+'.png'),fullPage:true});}
  }
  await page.goto('http://gh2-ui.test/dashboard/secrets');await page.getByText('Existing login',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Remove',exact:true}).count(),0);
  await page.getByLabel('Field for Existing login',{exact:true}).selectOption('login.username');
  await page.getByRole('button',{name:'Reveal',exact:true}).click();await page.getByRole('dialog',{name:'Revealed secret',exact:true}).waitFor();
  assert.deepEqual(calls.find(x=>x.action==='reveal').payload,{field:'login.username'});
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Edit',exact:true}).click();await page.getByLabel('Replacement value').fill('synthetic-new');
  await page.getByRole('button',{name:'Save changes',exact:true}).click();await page.getByText('Secret updated.',{exact:true}).waitFor();
  const edit=calls.find(x=>x.action==='edit').payload;assert.equal(edit.field,'login.username');assert.equal(edit.expected_version,'opaque-revision');assert(!('description' in edit));
  await page.getByRole('button',{name:'New secret',exact:true}).click();await page.getByLabel('Name',{exact:true}).fill('Synthetic secret');await page.getByLabel('Secret value',{exact:true}).fill('synthetic-create');await page.getByLabel('Folder (optional)',{exact:true}).selectOption('__unfiled');
  await page.getByRole('button',{name:'Save secret',exact:true}).click();await page.getByText('Secret saved.',{exact:true}).waitFor();
  assert.equal(calls.find(x=>x.action==='create').payload.folder_id,null);assert(!('space_id' in calls.find(x=>x.action==='create').payload));
  assert.deepEqual(errors,[]);console.log('PASS: disabled connection test; optional default folder; direct existing entries; selected-field reveal/edit; no remote deletion; global creation; explicit unfiled destination; responsive settings.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
