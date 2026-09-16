
(function(){
"use strict";
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const api=async(u,opt)=>{const r=await fetch(u,opt);const d=await r.json().catch(()=>({success:false,message:"Bad response"}));if(!r.ok||d.success===false)throw Error(d.message||"Request failed");return d};
function ensure(){
 if(document.getElementById("ttSuperFab"))return;
 const b=document.createElement("button");b.id="ttSuperFab";b.className="tt-super-fab";b.textContent="✨ Super";b.onclick=open;document.body.appendChild(b);
}
function open(){let x=document.getElementById("ttSuper");if(!x){x=document.createElement("div");x.id="ttSuper";x.innerHTML=`
<div class="tt-super-backdrop"></div><section class="tt-super-panel">
<div class="tt-super-head"><div><b style="font-size:21px">✨ Tick Tock Super</b><div class="tt-super-muted">Social tools + AI creator studio</div></div><button class="tt-super-btn" id="ttSuperClose">×</button></div>
<div class="tt-super-tabs">
<button class="active" data-tab="home">🏠 Hub</button><button data-tab="stories">📖 Stories</button><button data-tab="messages">💬 Messages</button><button data-tab="creator">📊 Creator</button><button data-tab="ai">🤖 AI</button>
</div>
<div id="ttSuperBody"></div></section>`;document.body.appendChild(x);
 x.querySelector("#ttSuperClose").onclick=()=>x.remove();x.querySelector(".tt-super-backdrop").onclick=()=>x.remove();
 x.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{x.querySelectorAll("[data-tab]").forEach(q=>q.classList.toggle("active",q===b));render(b.dataset.tab)});
}
render("home")}
async function render(tab){
 const b=document.getElementById("ttSuperBody"); if(!b)return;b.innerHTML='<div class="tt-super-muted">Loading…</div>';
 try{
 if(tab==="home"){const d=await api("/api/super/overview");b.innerHTML=`
 <div class="tt-super-grid"><div class="tt-super-card"><b>${d.stats.followers}</b><div class="tt-super-muted">Followers</div></div><div class="tt-super-card"><b>${d.stats.following}</b><div class="tt-super-muted">Following</div></div><div class="tt-super-card"><b>${d.stats.views}</b><div class="tt-super-muted">Views</div></div><div class="tt-super-card"><b>${d.reposts.length}</b><div class="tt-super-muted">Your reposts</div></div></div>
 <h3 style="margin:18px 0 8px">🔥 Trending</h3><div id="ttTrend"></div><h3 style="margin:18px 0 8px">🎬 Recommended</h3><div id="ttRec"></div>`;
 const [t,r]=await Promise.all([api("/api/super/trending"),api("/api/super/recommendations")]);
 document.getElementById("ttTrend").innerHTML=(t.hashtags||[]).map(x=>`<span class="tt-super-btn" style="display:inline-block;margin:4px">#${esc(x.tag)} <small>${x.posts}</small></span>`).join("")||'<div class="tt-super-muted">No trends yet.</div>';
 document.getElementById("ttRec").innerHTML=(r.videos||[]).slice(0,8).map(v=>`<div class="tt-super-row"><div class="tt-super-spacer"><b>${esc(v.title||"Video")}</b><div class="tt-super-muted">@${esc(v.creator||"creator")} · ${esc(v.tags||"")}</div></div></div>`).join("")||'<div class="tt-super-muted">No recommendations yet.</div>';
 }
 if(tab==="stories"){b.innerHTML=`<div class="tt-super-card"><b>➕ Add Story</b><input class="tt-super-input" id="ttStoryUrl" placeholder="Media URL (your uploaded image/video URL)"><input class="tt-super-input" id="ttStoryCaption" placeholder="Story caption"><button class="tt-super-btn primary" id="ttStoryAdd">Publish for 24h</button></div><div id="ttStories" style="margin-top:15px"></div>`;
 const d=await api("/api/super/stories");const s=document.getElementById("ttStories");s.innerHTML=`<div class="tt-super-story">${(d.stories||[]).map(v=>`<div class="tt-super-story-card">${/\.(mp4|webm|mov)(\?|$)/i.test(v.media_url)?`<video src="${esc(v.media_url)}" controls playsinline></video>`:`<img src="${esc(v.media_url)}" alt="">`}<b>@${esc(v.username)}</b><div class="tt-super-muted">${esc(v.caption||"")}</div></div>`).join("")}</div>`;
 document.getElementById("ttStoryAdd").onclick=async()=>{try{await api("/api/super/stories",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({media_url:document.getElementById("ttStoryUrl").value,caption:document.getElementById("ttStoryCaption").value})});render("stories")}catch(e){alert(e.message)}};
 }
 if(tab==="messages"){b.innerHTML=`<div class="tt-super-muted">Choose a person to open a chat.</div><div id="ttPeople"></div>`;const d=await api("/api/super/conversations");document.getElementById("ttPeople").innerHTML=(d.users||[]).slice(0,30).map(u=>`<div class="tt-super-row"><div class="tt-super-spacer"><b>@${esc(u.username)}</b><div class="tt-super-muted">${esc(u.last_message||"Start a conversation")}</div></div><button class="tt-super-btn" data-chat="${esc(u.uid)}">Chat</button></div>`).join("");document.querySelectorAll("[data-chat]").forEach(q=>q.onclick=()=>chat(q.dataset.chat));}
 if(tab==="creator"){const d=await api("/api/super/overview");b.innerHTML=`<div class="tt-super-grid"><div class="tt-super-card"><b>${d.stats.followers}</b><div class="tt-super-muted">Followers</div></div><div class="tt-super-card"><b>${d.stats.following}</b><div class="tt-super-muted">Following</div></div><div class="tt-super-card"><b>${d.stats.views}</b><div class="tt-super-muted">Total views</div></div></div><div class="tt-super-card" style="margin-top:12px"><b>💡 Creator checklist</b><p class="tt-super-muted" style="margin-top:8px">Post consistently, use clear hooks, add captions, reply to comments, and review retention/engagement in your analytics.</p></div>`}
 if(tab==="ai"){b.innerHTML=`<div class="tt-super-card"><b>🤖 AI Content Studio</b><textarea class="tt-super-textarea" id="ttAiSuperTopic" placeholder="Example: Hyderabad street food, gym transformation, college life…"></textarea><button class="tt-super-btn primary" id="ttAiSuperGo">Generate 5 ideas + hooks + hashtags</button><div id="ttAiSuperOut" style="margin-top:15px"></div></div>`;document.getElementById("ttAiSuperGo").onclick=async()=>{const o=document.getElementById("ttAiSuperOut");o.textContent="Creating…";try{const d=await api("/api/ai/super-ideas",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({topic:document.getElementById("ttAiSuperTopic").value})});const r=d.result||{};o.innerHTML=`<b>Ideas</b><ol>${(r.ideas||[]).map(x=>`<li>${esc(x)}</li>`).join("")}</ol><b>Hooks</b><ul>${(r.hooks||[]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul><b>Hashtags</b><p>${(r.hashtags||[]).map(x=>"#"+esc(x)).join(" ")}</p>`}catch(e){o.textContent=e.message}}}
 }catch(e){b.innerHTML=`<div class="tt-super-card">${esc(e.message)}</div>`}
}
async function chat(uid){const b=document.getElementById("ttSuperBody");try{const d=await api("/api/super/messages/"+encodeURIComponent(uid));b.innerHTML=`<button class="tt-super-btn" id="ttBack">← Back</button><h3 style="margin:12px 0">@${esc(d.user.username)}</h3><div id="ttChatBox" style="min-height:240px">${(d.messages||[]).map(m=>`<div class="tt-super-message ${m.sender_id==window.TICKTOCK_USER_ID?'mine':''}">${esc(m.body)}</div>`).join("")}</div><div style="display:flex;gap:8px;margin-top:10px"><input class="tt-super-input" id="ttMsg" placeholder="Message…" style="margin:0"><button class="tt-super-btn primary" id="ttSend">Send</button></div>`;document.getElementById("ttBack").onclick=()=>render("messages");document.getElementById("ttSend").onclick=async()=>{const el=document.getElementById("ttMsg");if(!el.value.trim())return;try{await api("/api/super/messages/"+encodeURIComponent(uid),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({body:el.value})});chat(uid)}catch(e){alert(e.message)}}}catch(e){b.textContent=e.message}}
document.addEventListener("DOMContentLoaded",ensure); if(document.readyState!=="loading")ensure();
})();
