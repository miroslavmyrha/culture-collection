import type { ReactNode } from 'react'
import { AppBar, Box, Container, Toolbar, Typography } from '@/components/ui'

/** The base layout every route renders in: a top bar and the one <main> of the page. */
export function Layout({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="static" elevation={0}>
        <Toolbar>
          <Typography component="p" variant="h6">
            Culture collection
          </Typography>
        </Toolbar>
      </AppBar>
      <Container component="main" maxWidth="lg" sx={{ py: 4, flex: 1 }}>
        {children}
      </Container>
    </Box>
  )
}
