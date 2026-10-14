import { Container } from "lucide-react";
import { lazy } from "react";
import type { FrontModule } from "@/app/registry";

const mod: FrontModule = {
  id: "docker",
  icon: Container,
  Page: lazy(() => import("./Page")),
  search: {
    url: "/api/docker",
    items: (d: { containers?: { id: string; name: string; image: string }[] }) =>
      (d.containers ?? []).map((c) => ({ id: c.id, label: c.name, hint: c.image, to: `/docker/${c.id}` })),
  },
};
export default mod;
