import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

// The built client is committed to the Python package's static folder, so the Windows PC that
// runs the app never needs Node: it only serves these files.
export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "../src/simple_task_management/static/dist",
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    rollupOptions: {
      input: "src/main.tsx",
      output: { entryFileNames: "app.js", chunkFileNames: "[name].js", format: "es" },
    },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
