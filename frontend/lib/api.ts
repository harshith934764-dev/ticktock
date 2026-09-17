const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
export async function apiGet(path:string){const t=typeof window!=="undefined"?localStorage.getItem("ticktock_token"):null;const r=await fetch(`${API}${path}`,{headers:t?{Authorization:`Bearer ${t}`}:{},cache:"no-store"});if(!r.ok)throw new Error(await r.text());return r.json();}
export async function apiPost(path:string,body:any){const t=typeof window!=="undefined"?localStorage.getItem("ticktock_token"):null;const r=await fetch(`${API}${path}`,{method:"POST",headers:{"Content-Type":"application/json",...(t?{Authorization:`Bearer ${t}`}:{})},body:JSON.stringify(body)});if(!r.ok)throw new Error(await r.text());return r.json();}
export {API};
