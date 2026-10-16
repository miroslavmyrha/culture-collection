// oxlint-disable-next-line import/no-unassigned-import -- must run before any schema is created
import '@/lib/zod-setup'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createApp } from '@/app/create-app'
import { Providers } from '@/app/providers'
import { onUnhandledRejection } from '@/lib/report'
import { initTrustedTypes } from '@/lib/sanitize'
import { installStaleChunkReload } from '@/lib/stale-chunks'

// Before anything renders: global error nets and the Trusted Types policy.
window.addEventListener('unhandledrejection', onUnhandledRejection)
installStaleChunkReload()
initTrustedTypes()

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

const { queryClient, router } = createApp()

createRoot(root).render(
  <StrictMode>
    <Providers client={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
)
