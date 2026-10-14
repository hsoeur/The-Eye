import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { ConfirmProvider } from "@/components/ui/dialog";
import { ThemeProvider } from "@/lib/theme";
import App from "./app/App";
import "./index.css";

const client = new QueryClient({ defaultOptions: { queries: { staleTime: 1000, refetchOnWindowFocus: true } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <ConfirmProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ConfirmProvider>
        <Toaster position="bottom-right" toastOptions={{ style: { background: "var(--surface)", border: "1px solid var(--border)", color: "var(--fg)" } }} />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
