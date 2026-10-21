import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api calls are forwarded to the FastAPI server.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
