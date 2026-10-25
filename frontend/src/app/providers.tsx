import { CacheProvider } from '@emotion/react'
import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { createEmotionCache } from './emotion'
import { SCHEME_KEY, schemeStorage } from './scheme'
import { theme } from './theme'

// Once per page load: the nonce is fixed for the document, and a new cache per render would
// insert every style again.
const emotionCache = createEmotionCache()

export function Providers({ children, client }: { children: ReactNode; client: QueryClient }) {
  return (
    <CacheProvider value={emotionCache}>
      <ThemeProvider theme={theme} defaultMode="system" modeStorageKey={SCHEME_KEY} storageManager={schemeStorage}>
        <CssBaseline enableColorScheme />
        <QueryClientProvider client={client}>
          {children}
        </QueryClientProvider>
      </ThemeProvider>
    </CacheProvider>
  )
}
