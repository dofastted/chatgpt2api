import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border-2 px-2.5 py-0.5 text-xs font-black uppercase tracking-[0.14em] transition-colors",
  {
    variants: {
      variant: {
        default: "border-[#FFE600] bg-[#FF3AF2]/20 text-[#FFE600]",
        secondary: "border-[#7B2FFF] bg-[#7B2FFF]/20 text-white",
        outline: "border-[#00F5D4] bg-background text-white",
        success:
          "border-[#00F5D4] bg-[#00F5D4]/16 text-[#00F5D4] dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300",
        warning:
          "border-[#FFE600] bg-[#FFE600]/18 text-[#FFE600] dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300",
        danger:
          "border-[#FF6B35] bg-[#FF6B35]/18 text-[#FF6B35] dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-300",
        info: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300",
        violet:
          "border-[#7B2FFF] bg-[#7B2FFF]/18 text-[#E7D5FF] dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-300",
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
