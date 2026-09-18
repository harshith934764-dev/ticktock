"use client";
import {FormEvent,useState} from "react";
import {api} from "../../lib/api";
export default function Forgot(){
 const [email,setEmail]=useState(""); const [otp,setOtp]=useState(""); const [password,setPassword]=useState("");
 const [sent,setSent]=useState(false); const [msg,setMsg]=useState(""); const [err,setErr]=useState("");
 async function send(e:FormEvent){e.preventDefault();setErr("");try{await api("/api/auth/forgot-password",{method:"POST",body:JSON.stringify({email})});setSent(true);setMsg("OTP sent.");}catch(x:any){setErr(x.message)}}
 async function reset(e:FormEvent){e.preventDefault();setErr("");try{await api("/api/auth/reset-password",{method:"POST",body:JSON.stringify({email,otp,new_password:password})});setMsg("Password reset. You can login now.");}catch(x:any){setErr(x.message)}}
 return <main className="auth-page"><div className="auth-card"><h1>Reset password 🔐</h1>
 <form onSubmit={sent?reset:send}><label>Gmail<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label>
 {sent&&<><label>OTP<input required maxLength={6} value={otp} onChange={e=>setOtp(e.target.value.replace(/\D/g,""))}/></label><label>New password<input type="password" required minLength={8} value={password} onChange={e=>setPassword(e.target.value)}/></label></>}
 {err&&<div className="error">{err}</div>}{msg&&<div className="success">{msg}</div>}<button>{sent?"Reset Password":"Send OTP"}</button></form></div></main>;
}
