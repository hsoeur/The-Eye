import { Network } from "lucide-react";
import { lazy } from "react";
import type { FrontModule } from "@/app/registry";

const mod: FrontModule = {
  id: "network",
  icon: Network,
  Page: lazy(() => import("./Page")),
  search: {
    url: "/api/network/state",
    items: (d: { devices?: Record<string, { ip: string; label?: string; hostname?: string; vendor?: string }> }) =>
      Object.values(d.devices ?? {}).map((x) => ({ id: x.ip, label: x.label || x.hostname || x.ip, hint: x.hostname || x.label ? x.ip : x.vendor, to: `/network/${x.ip}` })),
  },
};
export default mod;
