import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { crx } from "@crxjs/vite-plugin"
import manifest from "./manifest.json" with { type: "json" }

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    crx({ manifest }),
  ],
  build: {
    target: "es2020",
    rollupOptions: {
      input: {
        sidepanel: "src/sidepanel/index.html",
        popup: "src/popup/index.html",
      },
    },
  },
})
