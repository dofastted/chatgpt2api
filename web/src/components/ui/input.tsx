import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "border-input file:text-foreground placeholder:text-white/50 selection:bg-primary selection:text-primary-foreground flex h-11 w-full min-w-0 rounded-[24px] border-4 border-[#00F5D4]/70 bg-[rgba(15,7,31,0.86)] px-4 py-2 text-sm text-white shadow-[0_0_18px_rgba(0,245,212,0.12)] transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 focus-visible:border-[#FFE600] focus-visible:ring-[4px] focus-visible:ring-[#FF3AF2]/30",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
