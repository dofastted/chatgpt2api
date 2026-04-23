import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl border text-sm font-medium tracking-[0.01em] transition-all duration-200 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-amber-400/70 focus-visible:ring-4 focus-visible:ring-amber-400/20 aria-invalid:ring-destructive/30 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default:
          "border-amber-300/35 bg-[linear-gradient(135deg,rgba(245,158,11,0.98),rgba(251,191,36,0.94))] text-stone-950 shadow-[0_0_28px_rgba(245,158,11,0.22)] hover:border-amber-200/45 hover:brightness-105",
        destructive:
          "border-rose-400/25 bg-rose-500/90 text-white hover:bg-rose-500 focus-visible:ring-destructive/30",
        outline:
          "border-white/12 bg-white/[0.03] text-stone-100 hover:border-white/20 hover:bg-white/[0.08]",
        secondary:
          "border-amber-400/10 bg-amber-400/10 text-amber-100 hover:bg-amber-400/16",
        ghost:
          "border-transparent bg-transparent text-stone-300 shadow-none hover:bg-white/[0.06] hover:text-stone-50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-11 px-5 py-2 has-[>svg]:px-4",
        sm: "h-9 gap-1.5 px-4 text-xs has-[>svg]:px-3",
        lg: "h-12 px-7 has-[>svg]:px-5",
        icon: "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
