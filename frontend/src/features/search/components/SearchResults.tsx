import type { ReactNode } from 'react'
import { Box, Mono, Paper, StatusChip, Typography } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import type { useSearch } from '../api/queries'
import { detailOf, type Entry, type entriesOf, groupLabel, identifierOf, resultsSummary, statusLabel, statusTone, type Target } from '../schemas'

// In px: sx reads a width of 1 as 100 % and a margin of 1 as one spacing unit.
export const visuallyHidden = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  p: 0,
  m: '-1px',
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const

type Query = ReturnType<typeof useSearch>

/** What the live region says: nothing while the answer is not for this text, then the failure or the counts. */
function announcement(pending: boolean, query: Query, groups: Parameters<typeof resultsSummary>[0]): string {
  if (pending || (query.isFetching && query.data === undefined)) return ''
  if (query.isError) return `Search failed. ${errorMessage(query.error)}`
  return query.data ? resultsSummary(groups) : ''
}

type PopupProps = {
  shown: boolean
  compact: boolean
  query: Query
  groups: Parameters<typeof resultsSummary>[0]
  sections: ReturnType<typeof entriesOf>
  entries: Entry[]
  active: number
  listId: string
  /** The folded text in the field, and the text the answer is for. */
  text: string
  answered: string
  onPick: (target: Target | null) => void
  onHover: (index: number) => void
}

/** The popup under the field: the results, and the live region that reads out their counts. */
export function SearchPopup({ shown, compact, query, groups, sections, entries, active, listId, text, answered, onPick, onHover }: PopupProps) {
  if (!shown) return null
  return (
    <>
      <Paper
        elevation={8}
        // A press on the popup's padding or scroll bar keeps the focus in the field.
        onMouseDown={(event) => event.preventDefault()}
        sx={{
          position: 'absolute',
          top: 'calc(100% + 4px)',
          right: 0,
          width: compact ? '100%' : 'min(34rem, calc(100vw - 32px))',
          maxHeight: '70vh',
          overflowY: 'auto',
          zIndex: (theme) => theme.zIndex.modal - 1,
        }}
      >
        <Results query={query} sections={sections} entries={entries} active={active} listId={listId} text={text} onPick={onPick} onHover={onHover} />
      </Paper>
      {/* Mounted with the popup, before its content changes, so the counts are read out. */}
      <Box component="output" sx={visuallyHidden}>
        {announcement(answered !== text, query, groups)}
      </Box>
    </>
  )
}

type ResultsProps = {
  query: Query
  sections: ReturnType<typeof entriesOf>
  entries: Entry[]
  active: number
  listId: string
  text: string
  onPick: (target: Target | null) => void
  onHover: (index: number) => void
}

function Results({ query, sections, entries, active, listId, text, onPick, onHover }: ResultsProps) {
  if (query.data === undefined) {
    if (query.isError) return <Message>Search failed. {errorMessage(query.error)} Press Enter to try again.</Message>
    return <Message>Searching…</Message>
  }
  if (sections.length === 0) return <Message>No results for “{text}”. Try an accession number, a vial label or barcode, or a request number such as 2026/7.</Message>
  return (
    // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- a select cannot hold grouped rich options: the APG listbox pattern
    <Box component="ul" role="listbox" id={listId} aria-label="Search results" sx={{ listStyle: 'none', m: 0, p: 0.5 }}>
      {query.isError && (
        <Box component="li" role="presentation" sx={{ px: 1.5, py: 0.5, color: 'warning.main', typography: 'body2' }}>
          Could not refresh the results. {errorMessage(query.error)}
        </Box>
      )}
      {sections.map(({ group, entries: own }) => {
        const labelId = `${listId}-${group.kind}`
        return (
          <Box component="li" role="presentation" key={group.kind}>
            {/* oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- a group of options inside the listbox (APG grouped listbox) */}
            <Box component="ul" role="group" aria-labelledby={labelId} sx={{ listStyle: 'none', m: 0, p: 0 }}>
              <Box component="li" role="presentation" id={labelId} sx={{ px: 1.5, pt: 1, pb: 0.5, typography: 'overline', color: 'text.secondary', lineHeight: 1.5 }}>
                {groupLabel(group)}
              </Box>
              {own.map((entry) => {
                const index = entries.indexOf(entry)
                return (
                  <Option key={entry.id} entry={entry} id={`${listId}-${entry.id}`} active={index === active} onPick={() => onPick(entry.target)} onHover={() => onHover(index)} />
                )
              })}
            </Box>
          </Box>
        )
      })}
    </Box>
  )
}

function Option({ entry, id, active, onPick, onHover }: { entry: Entry; id: string; active: boolean; onPick: () => void; onHover: () => void }) {
  return (
    <Box
      component="li"
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- an option of the listbox above, not of a select
      role="option"
      id={id}
      aria-selected={active}
      aria-label={entry.name}
      // Keep the focus in the field: the click opens the entry, the field is still the combobox.
      onMouseDown={(event) => event.preventDefault()}
      onClick={onPick}
      onMouseMove={active ? undefined : onHover}
      sx={{
        display: 'block',
        px: 1.5,
        py: 0.75,
        borderRadius: 1,
        cursor: 'pointer',
        // The active option: a tint and a bar at the start, not colour alone (WCAG 1.4.1).
        boxShadow: active ? (theme) => `inset 3px 0 0 ${theme.palette.primary.main}` : 'none',
        bgcolor: active ? 'action.selected' : 'transparent',
      }}
    >
      {entry.type === 'all' ? (
        <Typography component="span" variant="body2" color="primary.main" sx={{ fontWeight: 500 }}>
          {entry.name}
        </Typography>
      ) : (
        <HitLines entry={entry} />
      )}
    </Box>
  )
}

function HitLines({ entry }: { entry: Extract<Entry, { type: 'hit' }> }) {
  const { kind, hit } = entry
  const tone = statusTone(kind, hit.status)
  return (
    <Box component="span" aria-hidden sx={{ display: 'block' }}>
      <Box component="span" sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 1, rowGap: 0.25 }}>
        <Box component="span" sx={{ fontWeight: 600 }}>
          <Mono>{identifierOf(kind, hit)}</Mono>
        </Box>
        <Typography component="span" variant="body2" color="text.secondary">
          {hit.lab_code}
        </Typography>
        {tone === undefined ? (
          <Typography component="span" variant="body2" color="text.secondary">
            {statusLabel(kind, hit.status)}
          </Typography>
        ) : (
          <StatusChip tone={tone}>{statusLabel(kind, hit.status)}</StatusChip>
        )}
      </Box>
      <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block', overflowWrap: 'anywhere' }}>
        {detailOf(kind, hit)}
      </Typography>
    </Box>
  )
}

function Message({ children }: { children: ReactNode }) {
  return (
    <Typography variant="body2" sx={{ px: 1.5, py: 1.25 }}>
      {children}
    </Typography>
  )
}

