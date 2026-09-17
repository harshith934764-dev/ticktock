"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import VideoCard from "../components/VideoCard";
import {api,logout} from "../lib/api";
type Video={id:number|string;url:string;creator?:string;caption?:string;likes?:number;comments?:number;views?:number};
export default function Home(){
 const [videos,setVideos]=useState<Video[]>([]); const [error,setError]=useState(""); const [logged,setLogged]=useState(false);
 useEffect(()=>{setLogged(!!localStorage.getItem("ticktock_token"));api<Video[]>("/api/videos").then(setVideos).catch(e=>setError(e.message));},[]);
 return <main className="feed"><section className="hero"><h1>Tick Tock 🍼</h1><p>Short videos. People. Community.</p><div className="actions">{logged?<button onClick={()=>{logout();location.reload()}}>Logout</button>:<><Link href="/login">Login</Link><Link href="/register">Register</Link></>}</div></section>
 {error&&<div className="error">{error}</div>}<section className="video-list">{videos.map(v=><VideoCard key={v.id} video={v}/>)}{!error&&!videos.length&&<p>No videos available yet.</p>}</section></main>;
}
