
/* Tick Tock AI Assistant — safe client-side UI.
   The OpenAI key is NEVER placed here. */
(function () {
  "use strict";
  function esc(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));}
  function toast(msg){
    let t=document.getElementById("ttAiToast");
    if(!t){t=document.createElement("div");t.id="ttAiToast";document.body.appendChild(t);}
    t.textContent=msg;t.classList.add("show");clearTimeout(t._x);t._x=setTimeout(()=>t.classList.remove("show"),2600);
  }
  async function call(path, body){
    const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});
    const d=await r.json().catch(()=>({success:false,message:"Invalid server response"}));
    if(!r.ok||d.success===false) throw new Error(d.message||"AI request failed");
    return d;
  }
  function modal(){
    let m=document.getElementById("ttAiModal");
    if(m) return m;
    m=document.createElement("div");
    m.id="ttAiModal";
    m.innerHTML=`<div class="tt-ai-backdrop" data-ai-close></div>
      <section class="tt-ai-card" role="dialog" aria-modal="true">
        <button class="tt-ai-x" data-ai-close>×</button>
        <div class="tt-ai-kicker">TICK TOCK AI</div>
        <h2>Make something people remember.</h2>
        <p class="tt-ai-muted">Create captions, hooks and a complete short-video plan.</p>
        <div class="tt-ai-tabs">
          <button class="active" data-ai-tab="caption">✨ Caption</button>
          <button data-ai-tab="plan">🎬 Creator plan</button>
          <button data-ai-tab="search">🔎 Smart search</button>
        </div>
        <div class="tt-ai-pane" data-pane="caption">
          <input id="ttAiTitle" placeholder="Video title / idea">
          <textarea id="ttAiContext" placeholder="Describe your video in a few words..."></textarea>
          <select id="ttAiTone"><option>premium and natural</option><option>funny</option><option>energetic</option><option>minimal</option><option>Telugu-friendly</option></select>
          <button class="tt-ai-primary" id="ttAiCaptionBtn">Generate caption</button>
        </div>
        <div class="tt-ai-pane" data-pane="plan" hidden>
          <textarea id="ttAiIdea" placeholder="Example: 20-second Hyderabad street-food reel"></textarea>
          <button class="tt-ai-primary" id="ttAiPlanBtn">Build my video plan</button>
        </div>
        <div class="tt-ai-pane" data-pane="search" hidden>
          <input id="ttAiSearch" placeholder="Try: funny Hyderabad food videos">
          <button class="tt-ai-primary" id="ttAiSearchBtn">Search with AI</button>
        </div>
        <div id="ttAiResult" class="tt-ai-result" hidden></div>
      </section>`;
    document.body.appendChild(m);
    m.querySelectorAll("[data-ai-close]").forEach(x=>x.onclick=()=>m.classList.remove("open"));
    m.querySelectorAll("[data-ai-tab]").forEach(b=>b.onclick=()=>{
      m.querySelectorAll("[data-ai-tab]").forEach(x=>x.classList.toggle("active",x===b));
      m.querySelectorAll(".tt-ai-pane").forEach(p=>p.hidden=p.dataset.pane!==b.dataset.aiTab);
      m.querySelector("#ttAiResult").hidden=true;
    });
    m.querySelector("#ttAiCaptionBtn").onclick=async()=>{
      try{
        const d=await call("/api/ai/caption",{title:m.querySelector("#ttAiTitle").value,context:m.querySelector("#ttAiContext").value,tone:m.querySelector("#ttAiTone").value});
        const r=d.result||{}; show(`<b>Hook</b><div>${esc(r.hook)}</div><br><b>Caption</b><div>${esc(r.caption)}</div><br><b>Hashtags</b><div>${(r.hashtags||[]).map(x=>"#"+esc(x)).join(" ")}</div>`);
      }catch(e){toast(e.message)}
    };
    m.querySelector("#ttAiPlanBtn").onclick=async()=>{
      try{
        const d=await call("/api/ai/creator-plan",{idea:m.querySelector("#ttAiIdea").value});
        const r=d.result||{}; show(`<b>Hook</b><div>${esc(r.hook)}</div><br><b>Shots</b><ol>${(r.shot_list||[]).map(x=>`<li>${esc(x)}</li>`).join("")}</ol><br><b>Voiceover</b><div>${esc(r.voiceover)}</div><br><b>Caption</b><div>${esc(r.caption)}</div><br><b>Hashtags</b><div>${(r.hashtags||[]).map(x=>"#"+esc(x)).join(" ")}</div>`);
      }catch(e){toast(e.message)}
    };
    m.querySelector("#ttAiSearchBtn").onclick=async()=>{
      try{
        const d=await call("/api/ai/search",{query:m.querySelector("#ttAiSearch").value});
        const r=d.videos||[]; show(`<b>${esc(d.category||"Smart search")}</b><div class="tt-ai-muted">Matched terms: ${(d.terms||[]).map(esc).join(", ")}</div><div class="tt-ai-results-list">${r.map(v=>`<button class="tt-ai-result-row" data-video-url="${esc(v.url)}"><b>${esc(v.title||"Untitled")}</b><small>@${esc(v.creator||"creator")}</small></button>`).join("")||"<div>No matching Tick Tock videos yet.</div>"}</div>`);
      }catch(e){toast(e.message)}
    };
    return m;
  }
  function show(html){const m=modal(),r=m.querySelector("#ttAiResult");r.innerHTML=html;r.hidden=false;}
  window.openTickTockAI=function(){modal().classList.add("open");};
  document.addEventListener("click",e=>{
    const row=e.target.closest(".tt-ai-result-row");
    if(row && row.dataset.videoUrl){navigator.clipboard?.writeText(row.dataset.videoUrl);toast("Video link copied");}
  });
})();

