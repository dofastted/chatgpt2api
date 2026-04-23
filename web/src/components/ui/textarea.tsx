import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "border-input placeholder:text-stone-500 flex min-h-32 w-full rounded-[18px] border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-stone-100 outline-none focus-visible:border-amber-300/40 focus-visible:bg-white/[0.06] focus-visible:ring-4 focus-visible:ring-amber-300/12 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
