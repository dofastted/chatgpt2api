"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LoaderCircle, LockKeyhole } from "lucide-react";
import { toast } from "sonner";

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
      toast.error("请输入 密钥");
      return;
    }

    setIsSubmitting(true);
    try {
      const session = await login(normalizedAuthKey);
      await setStoredAuthKey(normalizedAuthKey);
      const targetPath = session.role === "admin" ? "/accounts" : "/image";
      router.replace(targetPath);
    } catch (error) {
      const message = error instanceof Error ? error.message : "登录失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-page-shell grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
      <div className="grid w-full max-w-[1320px] gap-8 lg:grid-cols-[1.08fr_0.92fr]">
        <section className="max-panel max-grid-bg flex flex-col gap-6 p-8 sm:p-10">
          <div className="max-kicker">single key login</div>
          <div className="space-y-4">
            <h1 className="max-heading text-5xl sm:text-6xl lg:text-8xl">Welcome Back</h1>
            <p className="max-w-[680px] text-lg leading-8 text-white/80">
              登录流程不变，视觉改成更强的控制台气质。普通密钥继续进入画图页，管理员密钥继续进入号池管理。
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="max-panel-soft space-y-3 p-5">
              <div className="text-sm font-black uppercase tracking-[0.2em] text-[#FFE600]">Role Split</div>
              <div className="font-['Outfit'] text-2xl font-black uppercase text-white">User / Admin</div>
              <p className="text-sm leading-6 text-white/72">保留现有角色判断和跳转，不加新入口。</p>
            </div>
            <div className="max-panel-soft space-y-3 p-5">
              <div className="text-sm font-black uppercase tracking-[0.2em] text-[#00F5D4]">Fast Path</div>
              <div className="font-['Outfit'] text-2xl font-black uppercase text-white">Enter To Go</div>
              <p className="text-sm leading-6 text-white/72">继续保留回车提交，避免登录页变重。</p>
            </div>
            <div className="max-panel-soft space-y-3 p-5">
              <div className="text-sm font-black uppercase tracking-[0.2em] text-[#FF6B35]">Error Slot</div>
              <div className="font-['Outfit'] text-2xl font-black uppercase text-white">Toast First</div>
              <p className="text-sm leading-6 text-white/72">失败信息仍用原来的提示路径，直接给出。</p>
            </div>
          </div>
        </section>

        <Card className="w-full max-w-none border-[#00F5D4]/75 bg-[rgba(15,7,31,0.9)]">
          <CardContent className="space-y-8 p-6 sm:p-8">
            <div className="space-y-5 text-center">
              <div className="mx-auto inline-flex size-16 items-center justify-center rounded-full border-4 border-[#FFE600] bg-[linear-gradient(135deg,#FF3AF2_0%,#7B2FFF_55%,#00F5D4_100%)] text-white shadow-[0_0_20px_rgba(255,58,242,0.3),8px_8px_0_rgba(255,230,0,0.72)]">
                <LockKeyhole className="size-6" />
              </div>
              <div className="space-y-3">
                <div className="max-kicker">access portal</div>
                <h1 className="max-heading text-4xl sm:text-5xl">Auth Key</h1>
                <p className="text-sm leading-7 text-white/72">一个输入框，一个主按钮，清楚说明权限边界。</p>
              </div>
            </div>

            <div className="space-y-3">
              <label htmlFor="auth-key" className="block text-sm font-black uppercase tracking-[0.18em] text-[#FFE600]">
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

            <div className="flex flex-wrap gap-3">
              <div className="rounded-full border-2 border-[#00F5D4] bg-[#00F5D4]/12 px-4 py-2 text-xs font-black uppercase tracking-[0.16em] text-white">
                普通密钥 → /image
              </div>
              <div className="rounded-full border-2 border-[#FF6B35] bg-[#FF6B35]/12 px-4 py-2 text-xs font-black uppercase tracking-[0.16em] text-white">
                管理员密钥 → /accounts
              </div>
            </div>

            <Button
              className="h-14 w-full text-sm"
              onClick={() => void handleLogin()}
              disabled={isSubmitting}
            >
              {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              登录
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
