import { Compass } from "lucide-react";
import { Link, Route, Routes, useLocation, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/card";
import { usePoll } from "@/lib/usePoll";
import type { Overview as OverviewData } from "@/lib/types";
import { ErrorBoundary } from "./ErrorBoundary";
import { Layout } from "./Layout";
import Overview from "./Overview";
import { frontModule } from "./registry";

function ModuleRoute() {
  const { module } = useParams();
  const { pathname } = useLocation();
  const { data } = usePoll<OverviewData>("/api/overview", 5000);
  const def = module ? frontModule(module) : undefined;
  if (data && !data.modules.some((m) => m.id === module)) return <NotFound />;
  if (!def) return data ? <NotFound /> : null;
  return <ErrorBoundary resetKey={`/${module}`}><def.Page key={pathname.split("/")[1]} /></ErrorBoundary>;
}

function NotFound() {
  return <Empty icon={<Compass />} title="Page introuvable" hint="Ce module n'existe pas ou est désactivé."
    action={<Link to="/"><Button>Retour à la vue d'ensemble</Button></Link>} />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path=":module/*" element={<ModuleRoute />} />
      </Route>
    </Routes>
  );
}
