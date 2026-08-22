import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** Разбор Markdown нужен одному экрану из четырёх — чату, и грузиться должен с ним. */
const MARKDOWN_PACKAGES = [
  "react-markdown",
  "remark-",
  "rehype-",
  "micromark",
  "mdast-",
  "hast-",
  "unist-",
  "unified",
  "vfile",
  "devlop",
  "decode-named-character-reference",
  "property-information",
  "space-separated-tokens",
  "comma-separated-tokens",
  "html-url-attributes",
  "trim-lines",
  "bail",
  "is-plain-obj",
  "trough",
  "extend",
  "character-entities",
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("react-diff-view") || id.includes("gitdiff-parser")) {
            return "diff";
          }
          if (MARKDOWN_PACKAGES.some((name) => id.includes(name))) {
            return "markdown";
          }
          return "vendor";
        },
      },
    },
  },
});
