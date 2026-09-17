import "./globals.css";
import Link from "next/link";
export const metadata={title:"Tick Tock",description:"Short videos and social community"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body><header className="topbar"><Link href="/" className="logo">Tick Tock</Link><nav><Link href="/">Home</Link><Link href="/login">Login</Link><Link href="/register">Register</Link></nav></header>{children}</body></html>}
