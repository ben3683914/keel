import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      // Thresholds activate with the first real module (T-009), per the scaffold design doc.
      // thresholds: { lines: 80, branches: 75 },
    },
  },
});
