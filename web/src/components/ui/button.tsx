import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full border-4 text-sm font-black uppercase tracking-[0.18em] transition-all duration-200 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/70 focus-visible:ring-[4px] aria-invalid:ring-destructive/30 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive shadow-[0_0_20px_rgba(255,58,242,0.2),6px_6px_0_rgba(255,230,0,0.9)] hover:-translate-y-0.5",
  {
    variants: {
      variant: {
        default:
          "border-[#FFE600] bg-[linear-gradient(90deg,#FF3AF2_0%,#7B2FFF_45%,#00F5D4_100%)] text-primary-foreground hover:brightness-110",
        destructive:
          "border-[#FFE600] bg-[linear-gradient(90deg,#FF6B35_0%,#FF3AF2_100%)] text-white hover:brightness-110 focus-visible:ring-destructive/30 dark:bg-destructive/60",
        outline:
          "border-[#00F5D4] bg-[rgba(16,8,33,0.72)] text-white hover:bg-[#00F5D4] hover:text-[#0D0D1A] dark:bg-input/30 dark:border-input dark:hover:bg-input/50",
        secondary:
          "border-[#FF6B35] bg-[rgba(123,47,255,0.34)] text-white hover:bg-[rgba(255,58,242,0.48)]",
        ghost:
          "border-transparent bg-transparent text-white shadow-none hover:border-[#FF3AF2] hover:bg-[rgba(255,58,242,0.18)] dark:hover:bg-accent/50",
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
