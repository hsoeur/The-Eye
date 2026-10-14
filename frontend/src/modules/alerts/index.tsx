import { Bell } from "lucide-react";
import { lazy } from "react";
import type { FrontModule } from "@/app/registry";
import type { AlertsData } from "./types";

const mod: FrontModule = {
  id: "alerts",
  icon: Bell,
  Page: lazy(() => import("./Page")),
  search: {
    url: "/api/alerts",
    items: (d: AlertsData) => (d.alerts ?? []).map((a) => ({ id: a.id, label: a.message, hint: a.target_name, to: `/alerts/${a.id}` })),
  },
};
export default mod;
