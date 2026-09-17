"use client";

import { FormEvent, useState } from "react";
import { API_BASE, api, saveAuth } from "../lib/api";
import { useRouter } from "next/navigation";

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [otp,setOtp]=useState("");
  const [step,setStep]=useState<"password"|"otp">( "password");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault(); setError(""); setBusy(true);
    try {
      if (step==="password") {
        const data=await api<any>(`/api/auth/${mode}`, {
          method:"POST", body:JSON.stringify({email,password})
        });
        setStep("otp");
      } else {
        const endpoint=mode==="login" ? "/api/auth/verify-login-otp" : "/api/auth/verify-otp";
        const data=await api<any>(endpoint,{method:"POST",body:JSON.stringify({email,otp})});
        saveAuth(data); router.push("/");
      }
    } catch(err:any) { setError(err.message || "Something went wrong"); }
    finally { setBusy(false); }
  }

  return <div className="auth-card">
    <h1>{mode==="login" ? "Welcome back 👋" : "Create Tick Tock account 🍼"}</h1>
    <p>{step==="password" ? "Use your Gmail address." : "Enter the 6-digit OTP sent to your email."}</p>
    <form onSubmit={submit}>
      <label>Gmail<input type="email" required value={email} disabled={step==="otp"} onChange={e=>setEmail(e.target.value)} placeholder="you@gmail.com"/></label>
      {step==="password" && <label>Password<input type="password" required minLength={8} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Letters + numbers"/></label>}
      {step==="otp" && <label>OTP<input inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required value={otp} onChange={e=>setOtp(e.target.value.replace(/\D/g,""))} placeholder="123456"/></label>}
      {error && <div className="error">{error}</div>}
      <button disabled={busy}>{busy ? "Please wait..." : step==="password" ? (mode==="login"?"Send Login OTP":"Create Account & Send OTP") : "Verify & Continue"}</button>
    </form>
    {step==="password" && mode==="login" && <a className="google" href={`${API_BASE}/api/auth/google`}>Continue with Google</a>}
  </div>;
}
