"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LoaderCircle, LockKeyhole } from "lucide-react";
import { toast } from "@/components/ui/toast";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/api";
import { setStoredAuthKey } from "@/store/auth";

export default function LoginPage() {
  const router = useRouter();
  const [authKey, setAuthKey] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleLogin = async () => {
    const normalizedAuthKey = authKey.trim();
    if (!normalizedAuthKey) {
      toast.error("请输入密钥");
      return;
    }

    setIsSubmitting(true);
    try {
      const session = await login(normalizedAuthKey);
      await setStoredAuthKey(normalizedAuthKey);
      router.replace(session.role === "admin" ? "/accounts" : "/image");
    } catch (error) {
      const message = error instanceof Error ? error.message : "登录失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="minimal-page-shell grid min-h-[calc(100vh-1rem)] place-items-center px-4 py-6">
      <div className="grid w-full max-w-[1320px] gap-8 lg:grid-cols-[1.08fr_0.92fr]">
        <section className="minimal-panel minimal-grid-bg flex flex-col gap-6 p-8 sm:p-10">
          <div className="minimal-kicker">single key login</div>
          <div className="space-y-4">
            <h1 className="minimal-heading text-5xl sm:text-6xl lg:text-8xl">
              Sign in once,
              <br />
              then move on.
            </h1>
            <p className="max-w-[680px] text-lg leading-8 text-stone-400">
              登录方式不变。仍然只有一个密钥输入框，普通密钥进入 `/image`，管理员密钥进入 `/accounts`。
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="minimal-panel-soft space-y-3 p-5">
              <div className="minimal-kicker text-[11px]">role split</div>
              <div className="text-2xl font-semibold tracking-tight text-stone-100">User / Admin</div>
              <p className="text-sm leading-6 text-stone-400">保留现有角色判断和跳转，不加新入口。</p>
            </div>
            <div className="minimal-panel-soft space-y-3 p-5">
              <div className="minimal-kicker text-[11px]">enter submit</div>
              <div className="text-2xl font-semibold tracking-tight text-stone-100">Fast Path</div>
              <p className="text-sm leading-6 text-stone-400">继续保留回车提交，登录页不额外加流程。</p>
            </div>
            <div className="minimal-panel-soft space-y-3 p-5">
              <div className="minimal-kicker text-[11px]">feedback</div>
              <div className="text-2xl font-semibold tracking-tight text-stone-100">Toast First</div>
              <p className="text-sm leading-6 text-stone-400">失败仍然直接提示，不绕远路。</p>
            </div>
          </div>
        </section>

        <Card className="w-full max-w-none bg-[rgba(13,13,18,0.82)]">
          <CardContent className="space-y-8 p-6 sm:p-8">
            <div className="space-y-5 text-center">
              <div className="mx-auto inline-flex size-16 items-center justify-center rounded-full border border-amber-300/20 bg-amber-300/12 text-amber-200 shadow-[0_0_32px_rgba(245,158,11,0.16)]">
                <LockKeyhole className="size-6" />
              </div>
              <div className="space-y-3">
                <div className="minimal-kicker justify-center">secure access</div>
                <h1 className="minimal-heading text-4xl sm:text-5xl">Welcome Back</h1>
                <p className="text-sm leading-7 text-stone-400">一个输入框，一个主按钮，权限边界保持原样。</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <div className="rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-xs text-stone-300">
                普通密钥 → /image
              </div>
              <div className="rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-xs text-stone-300">
                管理员密钥 → /accounts
              </div>
            </div>

            <div className="space-y-3">
              <label htmlFor="auth-key" className="block text-sm font-medium text-stone-300">
                密钥
              </label>
              <Input
                id="auth-key"
                type="password"
                value={authKey}
                onChange={(event) => setAuthKey(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void handleLogin();
                  }
                }}
                placeholder="请输入密钥"
                className="h-14 text-base"
              />
            </div>

            <div className="minimal-panel-soft space-y-3 p-4">
              <div className="minimal-kicker text-[11px]">status note</div>
              <p className="text-sm leading-6 text-stone-400">无效授权仍然走 toast。这里只保留轻提示，不再堆高刺激色块。</p>
            </div>

            <Button className="h-14 w-full text-sm" onClick={() => void handleLogin()} disabled={isSubmitting}>
              {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              登录
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
