"use client";
import {useState} from "react";
import {api} from "../lib/api";

export default function AIAssistant(){
 const [q,setQ]=useState(""); const [results,setResults]=useState<any[]>([]); const [msg,setMsg]=useState("");
 async function search(){
  setMsg("");
  try{const r=await api<any>("/api/ai/search",{method:"POST",body:JSON.stringify({query:q})});setResults(r.videos||[]);}
  catch(e:any){setMsg(e.message||"Login required");}
 }
 return <section className="ai-box"><h2>🤖 AI Search</h2><div className="ai-row"><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Try: funny cricket videos"/><button onClick={search}>Search</button></div>{msg&&<p className="error">{msg}</p>}{results.map(v=><div className="ai-result" key={v.id}><b>@{v.creator}</b><p>{v.caption||v.title}</p></div>)}</section>
}
