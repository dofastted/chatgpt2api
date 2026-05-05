import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";
import { TopNav } from "@/components/top-nav";

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-heading",
});

const bodyFont = Inter({
  subsets: ["latin"],
  variable: "--font-body",
});

const monoFont = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "image-2",
  description: "image-2",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${headingFont.variable} ${bodyFont.variable} ${monoFont.variable} app-shell antialiased`}
        style={{
          fontFamily:
            'var(--font-body),"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif',
        }}
      >
        <Toaster position="top-center" richColors />
        <main className="app-shell__main min-h-screen px-4 py-4 sm:px-6 lg:px-8">
          <div className="mx-auto flex max-w-[1440px] flex-col gap-5">
            <TopNav />
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
