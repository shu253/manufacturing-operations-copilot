import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  },
  preview: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
          antd: ["antd", "@ant-design/icons"],
          charts: ["echarts", "echarts-for-react"]
        }
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/testSetup.ts",
    exclude: ["e2e/**", "node_modules/**", "dist/**"]
  }
});
