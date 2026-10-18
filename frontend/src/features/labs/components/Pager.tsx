import { Box, Button, Typography } from '@/components/ui'

type Props = {
  label: string
  count: number
  shown: number
  limit: number
  offset: number
  loading: boolean
  onOffsetChange: (offset: number) => void
}

/** Previous and next for a limit/offset list. The page owns the URL, this only asks for an offset. */
export function Pager({ label, count, shown, limit, offset, loading, onOffsetChange }: Props) {
  if (count <= limit && offset === 0) return null
  return (
    <Box component="nav" aria-label={label} sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, mt: 2 }}>
      <Typography>
        {offset + 1} to {offset + shown} of {count}
      </Typography>
      <Button disabled={offset === 0 || loading} onClick={() => onOffsetChange(Math.max(0, offset - limit))}>
        Previous
      </Button>
      <Button disabled={offset + limit >= count || loading} onClick={() => onOffsetChange(offset + limit)}>
        Next
      </Button>
    </Box>
  )
}

/** A page past the end (a shared link after rows were removed): offer the first page. */
export function PastTheEnd({ onFirstPage }: { onFirstPage: () => void }) {
  return (
    <Typography>
      This page is empty. <Button onClick={onFirstPage}>Go to the first page</Button>
    </Typography>
  )
}
