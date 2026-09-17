'use client';
import { useEffect, useRef, useState } from 'react';
import { apiPost } from '../lib/api';

type Video={id:string|number;url:string;title?:string;creator?:string;caption?:string;likes?:number;comments?:number;shares?:number;views?:number;liked?:boolean;saved?:boolean};

export default function VideoCard({video}:{video:Video}){
 const ref=useRef<HTMLVideoElement|null>(null); const [liked,setLiked]=useState(!!video.liked); const [likes,setLikes]=useState(video.likes||0); const [saved,setSaved]=useState(!!video.saved); const [views,setViews]=useState(video.views||0);
 useEffect(()=>{const el=ref.current;if(!el)return;const obs=new IntersectionObserver(es=>{for(const e of es){if(e.isIntersecting){el.play().catch(()=>{});apiPost(`/api/videos/${video.id}/view`,{}).then(x=>setViews(x.views)).catch(()=>{});}else el.pause();}}, {threshold:.65});obs.observe(el);return()=>obs.disconnect()},[video.id]);
 const like=()=>apiPost(`/api/videos/${video.id}/like`,{}).then(x=>{setLiked(x.liked);setLikes(x.count)}).catch(()=>{});
 const bookmark=()=>apiPost(`/api/videos/${video.id}/bookmark`,{}).then(x=>setSaved(x.saved)).catch(()=>{});
 const share=()=>{navigator.clipboard?.writeText(window.location.origin+`/video/${video.id}`).catch(()=>{});apiPost(`/api/videos/${video.id}/share`,{}).catch(()=>{});};
 return <article className="video-card"><video ref={ref} src={video.url} muted loop playsInline preload="metadata" controls/><div className="video-info"><strong>@{video.creator||'creator'}</strong><h3>{video.title||'Tick Tock video'}</h3>{video.caption&&<p>{video.caption}</p>}<div className="video-actions"><button onClick={like}>{liked?'❤️':'🤍'} {likes}</button><button onClick={()=>window.location.href=`/video/${video.id}`}>💬 {video.comments||0}</button><button onClick={share}>🔗</button><button onClick={bookmark}>{saved?'🔖':'📑'}</button><span>👁️ {views}</span></div></div></article>
}
