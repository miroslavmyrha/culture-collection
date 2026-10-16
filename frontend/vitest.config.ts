import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}', 'tools/**/*.test.ts'],
      restoreMocks: true,
      // Dates render the same on every machine and in CI.
      env: { TZ: 'UTC' },
    },
  }),
)
