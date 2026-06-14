import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Toaster } from "@/components/ui/toast";
import "./globals.css";
import { TopNav } from "@/components/top-nav";

const bodyFont = Inter({
  subsets: ["latin"],
  variable: "--font-body",
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
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className={`${bodyFont.variable} app-shell antialiased`}
        style={{
          fontFamily:
            'var(--font-body),"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif',
        }}
      >
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => {
              try {
                const storageKey = 'chatgpt2api-theme';
                const storedTheme = window.localStorage.getItem(storageKey);
                const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
                const resolvedTheme = storedTheme === 'light' || storedTheme === 'dark'
                  ? storedTheme
                  : mediaQuery.matches
                    ? 'dark'
                    : 'light';
                const root = document.documentElement;
                root.classList.toggle('dark', resolvedTheme === 'dark');
                root.classList.toggle('light', resolvedTheme === 'light');
                root.style.colorScheme = resolvedTheme;
              } catch (error) {
                void error;
              }
            })();`,
          }}
        />
        <Toaster />
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
