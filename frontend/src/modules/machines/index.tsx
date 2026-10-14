import { Server } from "lucide-react";
import { lazy } from "react";
import type { FrontModule } from "@/app/registry";

const mod: FrontModule = {
  id: "machines",
  icon: Server,
  Page: lazy(() => import("./Page")),
  search: {
    url: "/api/machines",
    items: (d: { hosts?: { id: string; name: string; ip: string }[] }) =>
      (d.hosts ?? []).map((h) => ({ id: h.id, label: h.name, hint: h.ip, to: `/machines/${h.id}` })),
  },
};
export default mod;
