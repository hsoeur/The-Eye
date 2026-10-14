import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// En production, le build est servi par le backend Python (theeye/web).
// En développement, `npm run dev` proxifie l'API vers un backend lancé sur le port 8765.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: "../theeye/web",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
