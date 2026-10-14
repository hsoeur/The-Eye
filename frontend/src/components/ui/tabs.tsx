import * as T from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const Tabs = T.Root;

export function TabList({ children }: { children: ReactNode }) {
  return <T.List className="flex gap-1 border-b">{children}</T.List>;
}

export function Tab({ value, children, count }: { value: string; children: ReactNode; count?: number }) {
  return (
    <T.Trigger
      value={value}
      className={cn("-mb-px flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2 text-[13px] font-medium text-muted transition-colors hover:text-fg",
        "data-[state=active]:border-accent data-[state=active]:text-fg")}
    >
      {children}
      {count ? <span className="rounded bg-crit/12 px-1.5 text-[10px] font-semibold text-crit">{count}</span> : null}
    </T.Trigger>
  );
}

export const TabPanel = ({ value, children }: { value: string; children: ReactNode }) => (
  <T.Content value={value} className="fade-in pt-4 outline-none">{children}</T.Content>
);
