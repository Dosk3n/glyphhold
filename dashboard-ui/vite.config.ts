import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/dashboard-assets/",
  plugins: [react()],
  build: {
    outDir: "../app/dashboard/static/dashboard",
    emptyOutDir: true,
  },
});
