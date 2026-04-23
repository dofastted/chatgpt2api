import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-[0.08em] transition-colors",
  {
    variants: {
      variant: {
        default: "border-amber-300/20 bg-amber-300/12 text-amber-100",
        secondary: "border-white/10 bg-white/[0.05] text-stone-300",
        outline: "border-white/12 bg-background text-stone-200",
        success: "border-emerald-400/18 bg-emerald-400/12 text-emerald-300",
        warning: "border-amber-300/20 bg-amber-300/14 text-amber-200",
        danger: "border-rose-400/20 bg-rose-400/12 text-rose-300",
        info: "border-sky-400/18 bg-sky-400/12 text-sky-300",
        violet: "border-violet-400/18 bg-violet-400/12 text-violet-200",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
