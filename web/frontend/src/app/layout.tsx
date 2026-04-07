import type { Metadata } from "next";
import { Noto_Serif_SC } from "next/font/google";
import { Geist_Mono } from "next/font/google";
import "./globals.css";

const serifSC = Noto_Serif_SC({
  variable: "--font-serif-sc",
  subsets: ["latin"],
  weight: ["400", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ANNIE - Midnight Train",
  description:
    "AI-powered murder mystery with cognitive NPCs — memory, secrets, and social dynamics",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${serifSC.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-[family-name:var(--font-serif-sc)]">
        {children}
      </body>
    </html>
  );
}
