import { KeyRound } from "lucide-react";
import { lazy } from "react";
import type { FrontModule } from "@/app/registry";

const mod: FrontModule = {
  id: "vault",
  icon: KeyRound,
  Page: lazy(() => import("./Page")),
};
export default mod;
