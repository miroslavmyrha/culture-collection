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
      // One budget for every test and hook, in place of per-test overrides (#60). Measured per test over
      // the whole suite (1085 tests): slowest 5.8 s without added load (other sessions kept the machine
      // busy even then), 9.0 s with 4 busy processes on the 4 cores, 13.1 s with 8. The default 5 s failed
      // a test at 8. 40 s is 3 times the slowest at 8. Hooks were not timed apart and get the same. The
      // wait inside a test (asyncUtilTimeout, src/test/setup.ts) is shorter, so a missing element fails
      // with its own message before the test times out.
      testTimeout: 40_000,
      hookTimeout: 40_000,
      // Dates render the same on every machine and in CI.
      env: { TZ: 'UTC' },
    },
  }),
)
