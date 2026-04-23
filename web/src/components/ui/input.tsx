import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "border-input file:text-foreground placeholder:text-stone-500 selection:bg-primary selection:text-primary-foreground flex h-11 w-full min-w-0 rounded-[16px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-stone-100 shadow-none transition-[color,box-shadow,border-color,background-color] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 focus-visible:border-amber-300/40 focus-visible:bg-white/[0.06] focus-visible:ring-4 focus-visible:ring-amber-300/12",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
