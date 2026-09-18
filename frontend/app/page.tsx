'use client';
import { useEffect,useState } from 'react';
import Link from 'next/link';
import { apiGet } from '../lib/api';
import AIAssistant from '../components/AIAssistant';
import VideoCard from '../components/VideoCard';
export default function Home(){const [tab,setTab]=useState('for-you');const [videos,setVideos]=useState<any[]>([]);const [loading,setLoading]=useState(true);const [error,setError]=useState('');
 useEffect(()=>{setLoading(true);setError('');apiGet(tab==='trending'?'/api/feed/trending':'/api/feed/for-you').then(setVideos).catch(e=>setError(e.message)).finally(()=>setLoading(false))},[tab]);
 return <main className="feed"><section className="hero"><h1>Tick Tock</h1><p>Short videos, creators and your personalized feed.</p><div className="actions"><Link href="/upload">⬆️ Upload</Link><Link href="/creator">📊 Creator Studio</Link><Link href="/login">Login</Link></div></section><AIAssistant/><div className="tabs"><button className={tab==='for-you'?'active':''} onClick={()=>setTab('for-you')}>For You</button><button className={tab==='trending'?'active':''} onClick={()=>setTab('trending')}>🔥 Trending</button></div>{loading&&<p>Loading videos…</p>}{error&&<p className="error">{error}</p>}<section className="video-list">{videos.map(v=><VideoCard key={v.id} video={v}/>)}{!loading&&!videos.length&&<p>No public videos yet.</p>}</section></main>}
