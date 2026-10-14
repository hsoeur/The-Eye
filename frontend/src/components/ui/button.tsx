import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const variants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none select-none",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:brightness-110",
        secondary: "border bg-surface hover:bg-raised",
        ghost: "hover:bg-raised text-muted hover:text-fg",
        danger: "border border-crit/40 text-crit hover:bg-crit/10",
      },
      size: { sm: "h-7 px-2.5 text-xs", md: "h-8 px-3 text-[13px]", icon: "h-8 w-8" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, type = "button", ...p }, ref) => (
  <button ref={ref} type={type} className={cn(variants({ variant, size }), className)} {...p} />
));
Button.displayName = "Button";
