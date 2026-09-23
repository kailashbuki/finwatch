import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * `base` must match the GitHub Pages path. For a project page the site is served from
 * /<repo>/, so CI passes VITE_BASE=/<repo>/; local dev and user/org pages use '/'.
 */
export default defineConfig({
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
})
