/// <reference types="vitest/config" />
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // 后端地址可用 QUOS_API 覆盖(worktree/并行会话场景避让端口)
    proxy: { '/api': process.env.QUOS_API ?? 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
  },
})
