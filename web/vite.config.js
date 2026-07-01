import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// For GitHub Pages project sites the app is served from /<repo>/.
// Override with BASE_PATH env (the deploy workflow sets it to /ai-storage-prep/).
const base = process.env.BASE_PATH || '/ai-storage-prep/'

export default defineConfig({
  base,
  plugins: [vue()],
})
