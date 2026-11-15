(() => {
 const $ = id => document.getElementById(id);
 const state = { reference:null, clips:[], plan:null, objectUrls:[] };
 const fmt = s => { if(!Number.isFinite(s)) return "—"; const m=Math.floor(s/60),r=Math.floor(s%60); return m ? `${m}:${String(r).padStart(2,"0")}` : `${r} ث`; };
 const makeUrl = file => { const url=URL.createObjectURL(file); state.objectUrls.push(url); return url; };
 const probe = file => new Promise(resolve => {
   const v=document.createElement("video"); v.preload="metadata"; v.muted=true; v.src=makeUrl(file);
   v.onloadedmetadata=()=>resolve({duration:v.duration,width:v.videoWidth,height:v.videoHeight,url:v.src,name:file.name,size:file.size});
   v.onerror=()=>resolve({duration:0,width:0,height:0,url:v.src,name:file.name,size:file.size,error:true});
 });
 const thumb = async info => {
   if(!info.duration) return "";
   return new Promise(resolve=>{
     const v=document.createElement("video");v.muted=true;v.preload="auto";v.src=info.url;
     v.onloadeddata=()=>{try{v.currentTime=Math.min(1,info.duration*.2)}catch(e){resolve("");}};
     v.onseeked=()=>{try{const c=document.createElement("canvas");c.width=120;c.height=68;c.getContext("2d").drawImage(v,0,0,120,68);resolve(c.toDataURL("image/jpeg",.65));}catch(e){resolve("");}};
     v.onerror=()=>resolve("");
   });
 };
 const brightness = async info => {
   if(!info.duration) return null;
   return new Promise(resolve=>{
     const v=document.createElement("video");v.muted=true;v.preload="auto";v.src=info.url;
     const times=[.12,.32,.52,.72,.9].map(x=>Math.max(0,Math.min(info.duration-.1,info.duration*x)));
     let i=0,vals=[];
     v.onloadeddata=()=>{v.currentTime=times[0]};
     v.onseeked=()=>{
       try{const c=document.createElement("canvas");c.width=24;c.height=24;const ctx=c.getContext("2d",{willReadFrequently:true});ctx.drawImage(v,0,0,24,24);const d=ctx.getImageData(0,0,24,24).data;let sum=0;for(let p=0;p<d.length;p+=4)sum+=.2126*d[p]+.7152*d[p+1]+.0722*d[p+2];vals.push(sum/(d.length/4));}catch(e){}
       i++;if(i<times.length){v.currentTime=times[i]}else resolve(vals.length?vals:null);
     };
     v.onerror=()=>resolve(null);
   });
 };
 $("referenceInput").addEventListener("change",async e=>{
   const f=e.target.files[0];if(!f)return;state.reference=await probe(f);
   $("referenceMeta").textContent=`${f.name} · ${fmt(state.reference.duration)} · ${state.reference.width}×${state.reference.height}`;
   $("referencePreview").src=state.reference.url;$("refInfo").textContent=fmt(state.reference.duration);$("previewGrid").hidden=false;
 });
 $("footageInput").addEventListener("change",async e=>{
   const files=Array.from(e.target.files||[]);if(!files.length)return;
   $("footageMeta").textContent="جارٍ قراءة معلومات اللقطات...";
   state.clips=await Promise.all(files.map(probe));
   $("footageMeta").textContent=`${state.clips.length} ملفات فيديو · ${state.clips.reduce((n,x)=>n+x.duration,0).toFixed(1)} ثانية إجمالاً`;
   $("clipsCount").textContent=state.clips.length+" مقاطع";$("previewGrid").hidden=false;
   $("clipList").innerHTML="";
   for(let i=0;i<state.clips.length;i++){const c=state.clips[i],im=await thumb(c),el=document.createElement("div");el.className="clip-item";const img=document.createElement("img");img.className="clip-thumb";img.src=im;const span=document.createElement("span");span.textContent=`${i+1}. ${c.name} — ${fmt(c.duration)}`;el.append(img,span);$("clipList").append(el);}
 });
 $("analyzeBtn").addEventListener("click",async()=>{
   if(!state.reference){$("status").textContent="ارفع الفيديو المرجعي أولاً.";return;}
   if(!state.clips.length){$("status").textContent="أضف لقطة واحدة على الأقل.";return;}
   const target=Math.max(5,Math.min(300,Number($("durationInput").value)||30));
   $("analyzeBtn").disabled=true;$("status").textContent="جارٍ فحص عينات الإطارات وبناء ترتيب أولي...";
   try{
     const refLight=await brightness(state.reference);
     const clipData=await Promise.all(state.clips.map(async(c,i)=>({...c,brightness:await brightness(c),index:i})));
     const total=clipData.reduce((n,c)=>n+c.duration,0);
     let remaining=target,chosen=[];
     const ranked=[...clipData].sort((a,b)=>Math.abs((a.brightness?.reduce((x,y)=>x+y,0)/(a.brightness?.length||1) || 128)-120)-Math.abs((b.brightness?.reduce((x,y)=>x+y,0)/(b.brightness?.length||1) || 128)-120));
     let ordered=ranked;
     if($("styleInput").value==="energetic") ordered=[...clipData].sort((a,b)=>a.duration-b.duration);
     if($("styleInput").value==="cinematic") ordered=[...clipData].sort((a,b)=>b.duration-a.duration);
     for(const c of ordered){if(remaining<=0)break;const take=Math.min(c.duration,remaining, $("styleInput").value==="energetic"?4.5:remaining);if(take>0){chosen.push({...c,used:take,sourceStart:Math.max(0,(c.duration-take)*.15)});remaining-=take;}}
     let cursor=0;chosen=chosen.map(c=>{const x={...c,outStart:cursor,outEnd:cursor+c.used,transition:cursor===0?"بداية":$("styleInput").value==="energetic"?"قطع سريع":"انتقال ناعم"};cursor+=c.used;return x;});
     const plan={createdAt:new Date().toISOString(),reference:{name:state.reference.name,duration:state.reference.duration,width:state.reference.width,height:state.reference.height,brightness:refLight},targetSeconds:target,platform:$("platformInput").value,style:$("styleInput").value,sourceClips:clipData.map(c=>({name:c.name,duration:c.duration,width:c.width,height:c.height,brightness:c.brightness})),timeline:chosen,notes:["التحليل الحالي يعتمد على بيانات الملف وعينات سطوع الإطارات فقط.","اختيار اللقطات وترتيبها أولي ولا يتضمن فهماً دلالياً للمشهد.","التنفيذ الفعلي للانتقالات وتصحيح الألوان وتصدير الفيديو سيضاف في مرحلة المحرك."]};
     state.plan=plan;renderPlan(plan,total);$("results").hidden=false;$("results").scrollIntoView({behavior:"smooth",block:"start"});
     $("status").textContent=remaining>0?`تم إعداد خطة أولية، لكن لقطاتك أقصر من المدة المطلوبة بـ ${remaining.toFixed(1)} ثانية.`:"اكتملت الخطة الأولية. راجعها أدناه.";
   }catch(err){$("status").textContent="تعذر تحليل الفيديو: "+err.message;}finally{$("analyzeBtn").disabled=false;}
 });
 function renderPlan(p,total){
   $("refDuration").textContent=fmt(p.reference.duration);$("clipTotal").textContent=p.sourceClips.length;$("targetDuration").textContent=fmt(p.targetSeconds);$("cutStyle").textContent=p.style==="energetic"?"سريع":p.style==="cinematic"?"سينمائي":"حسب المرجع";$("timelineTotal").textContent="المدة المخططة: "+fmt(p.timeline.reduce((n,x)=>n+x.used,0));
   $("timeline").innerHTML="";
   p.timeline.forEach((c,i)=>{const el=document.createElement("div");el.className="timeline-clip";const a=document.createElement("small"),b=document.createElement("strong"),d=document.createElement("span");a.textContent="CLIP "+String(i+1).padStart(2,"0");b.textContent=c.name.length>18?c.name.slice(0,16)+"…":c.name;d.textContent=fmt(c.used)+" · "+c.transition;el.append(a,b,d);$("timeline").append(el);});
   const vals=p.reference.brightness||[];const avg=vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null;const label=avg===null?"لم تتوفر عينات كافية":avg<70?"الإضاءة منخفضة في عدة عينات":avg>190?"الإضاءة مرتفعة في عدة عينات":"مستوى الإضاءة العام متوسط";
   $("insightText").textContent=`تم فحص ${vals.length} عينات من المرجع. ${label}. تم اختيار ${p.timeline.length} مقاطع من لقطاتك بمدة إجمالية ${fmt(p.timeline.reduce((n,x)=>n+x.used,0))}. المقاس المطلوب ${p.platform}. لم يتم تطبيق انتقالات أو مؤثرات على ملف فيديو بعد.`;
 }
 $("downloadPlanBtn").addEventListener("click",()=>{if(!state.plan)return;const blob=new Blob([JSON.stringify(state.plan,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="SmartCut-edit-plan.json";a.click();URL.revokeObjectURL(a.href);});
 $("resetBtn").addEventListener("click",()=>{state.reference=null;state.clips=[];state.plan=null;$("referenceInput").value="";$("footageInput").value="";$("referencePreview").removeAttribute("src");$("referenceMeta").textContent="لم يتم اختيار فيديو";$("footageMeta").textContent="لم يتم اختيار لقطات";$("clipList").innerHTML="";$("previewGrid").hidden=true;$("results").hidden=true;$("status").textContent="تمت إعادة الاختيار.";window.scrollTo({top:0,behavior:"smooth"});});
 $("helpBtn").addEventListener("click",()=>$("helpDialog").showModal());$("closeHelp").addEventListener("click",()=>$("helpDialog").close());
 window.addEventListener("beforeunload",()=>state.objectUrls.forEach(URL.revokeObjectURL));
})();