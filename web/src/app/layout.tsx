import type { Metadata } from "next";
import { DM_Sans, Outfit } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";
import { TopNav } from "@/components/top-nav";

const headingFont = Outfit({
  subsets: ["latin"],
  variable: "--font-heading",
});

const bodyFont = DM_Sans({
  subsets: ["latin"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "ChatGPT 号池管理",
  description: "ChatGPT account pool management dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${headingFont.variable} ${bodyFont.variable} app-shell antialiased`}
        style={{
          fontFamily:
            'var(--font-body),"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif',
        }}
      >
        <Toaster position="top-center" richColors />
        <main className="app-shell__main min-h-screen px-4 py-3 text-stone-900 sm:px-6 lg:px-8">
          <div className="mx-auto flex max-w-[1480px] flex-col gap-5">
            <TopNav />
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
