export const API_BASE=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000';
export const API=API_BASE;
export async function api<T=any>(path:string,options:RequestInit={}){const token=typeof window!=='undefined'?localStorage.getItem('ticktock_token'):null;const headers=new Headers(options.headers||{});if(options.body&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');if(token)headers.set('Authorization',`Bearer ${token}`);const r=await fetch(`${API_BASE}${path}`,{...options,headers,cache:'no-store'});if(!r.ok)throw new Error(await r.text());return r.json() as Promise<T>}
export async function apiGet<T=any>(path:string){return api<T>(path)}
export async function apiPost<T=any>(path:string,body:any){return api<T>(path,{method:'POST',body:JSON.stringify(body)})}
export function saveAuth(data:any){if(typeof window==='undefined')return;const token=data?.token||data?.access_token;if(token)localStorage.setItem('ticktock_token',token);if(data?.user)localStorage.setItem('ticktock_user',JSON.stringify(data.user))}
