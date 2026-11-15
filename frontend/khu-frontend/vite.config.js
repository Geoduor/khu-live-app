import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Environment variables keep their old Create React App names (REACT_APP_API_URL,
// REACT_APP_GA_ID, REACT_APP_PUBLIC_URL), so nothing has to change in Vercel and the
// source (and the plain-Node tests that read it) keep using process.env.REACT_APP_*.
const KNOWN = ["REACT_APP_API_URL", "REACT_APP_GA_ID", "REACT_APP_PUBLIC_URL"];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "REACT_APP_");
  const define = {};
  for (const k of new Set([...KNOWN, ...Object.keys(env)])) {
    define[`process.env.${k}`] = JSON.stringify(env[k] ?? "");
  }
  define["process.env.PUBLIC_URL"] = JSON.stringify("");
  return {
    plugins: [react()],
    define,
    server: { port: 3000 },
    build: {
      outDir: "build", // same folder as before, so Vercel needs no change
      // Keep older Android phones working (CRA's browserslist was equally broad).
      target: ["es2018", "chrome70", "safari12", "firefox68"],
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/setupTests.js"],
      include: ["src/**/*.test.{js,jsx}"],
    },
  };
});
