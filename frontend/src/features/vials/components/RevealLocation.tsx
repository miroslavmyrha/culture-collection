import { type MouseEvent, useState } from 'react'
import { Box, Button, Typography } from '@/components/ui'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { useRevealLocation } from '../api/mutations'
import { type Location, locationText, type Vial } from '../schemas'
import { vialError } from '../vialErrors'

/**
 * Where a vial of a regulated strain is, for a holder of the lab's location grant (ADR 0009).
 * Masked until asked; each "Reveal location" is a request the server records before it
 * answers. "Hide location" forgets the answer, here and in the mutation cache: the next look is
 * a new reveal. The button keeps its place and the focus, the text next to it is announced. The
 * strain page remounts this after the vial moved, so an old answer never stays; focus on the
 * button then goes to the section, not the body.
 */
export function RevealLocation({ labId, vial }: { labId: string; vial: Vial }) {
  const reveal = useRevealLocation(labId)
  const [shown, setShown] = useState<Location | null>(null)
  const [failure, setFailure] = useState<string>()
  const remember = useFocusReturnOnUnmount()
  const toggle = (event: MouseEvent<HTMLButtonElement>) => {
    remember(event.currentTarget)
    if (reveal.isPending) return
    if (shown) {
      setShown(null)
      reveal.reset()
      return
    }
    setFailure(undefined)
    reveal.mutate(vial.public_id, {
      onSuccess: ({ location }) => (location ? setShown(location) : setFailure('The vial has no place now.')),
      onError: (error) => setFailure(vialError(error)),
    })
  }
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 1 }}>
      <Typography component="span" variant="inherit" aria-live="polite" sx={{ overflowWrap: 'anywhere' }}>
        {shown ? locationText(shown) : (failure ?? 'Hidden: regulated strain')}
      </Typography>
      <Button
        size="small"
        onClick={toggle}
        aria-disabled={reveal.isPending}
        aria-busy={reveal.isPending}
        aria-label={`${shown ? 'Hide' : 'Reveal'} the location of vial ${vial.label}`}
        sx={{ '&[aria-disabled="true"]': { color: 'text.disabled', cursor: 'progress' } }}
      >
        {shown ? 'Hide location' : 'Reveal location'}
      </Button>
    </Box>
  )
}
