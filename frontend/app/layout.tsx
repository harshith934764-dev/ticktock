import "./globals.css";
import Link from "next/link";

// Render runs this app as a live web service. Do not prerender pages at build time.
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const metadata={title:"Tick Tock",description:"Short videos and social community"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body><header className="topbar"><Link href="/" className="logo">Tick Tock</Link><nav><Link href="/">Home</Link><Link href="/login">Login</Link><Link href="/register">Register</Link></nav></header>{children}</body></html>}
