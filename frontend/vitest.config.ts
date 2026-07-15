/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Vitest configuration. Re-uses the Vite plugin stack so JSX / TSX
 * load the same way they do in the dev server. The `test` block opts
 * into the happy-dom environment which gives us `window`, `EventSource`,
 * and `fetch` shims — needed for the SSE / fetch-touching tests.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
