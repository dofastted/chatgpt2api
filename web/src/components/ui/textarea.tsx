import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "border-input placeholder:text-white/50 focus-visible:border-ring focus-visible:ring-ring/50 flex min-h-32 w-full rounded-[28px] border-4 border-[#00F5D4]/70 bg-[rgba(15,7,31,0.86)] px-4 py-3 text-sm text-white shadow-[0_0_18px_rgba(0,245,212,0.12)] outline-none focus-visible:ring-[4px] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
