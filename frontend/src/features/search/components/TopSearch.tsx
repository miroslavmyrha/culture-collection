import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { Box, Button, Mono, Paper, StatusChip, TextField, Typography } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { searchOptions, useSearch } from '../api/queries'
import {
  DEBOUNCE_MS,
  detailOf,
  type Entry,
  entriesOf,
  exactHit,
  groupLabel,
  identifierOf,
  normalise,
  resultsSummary,
  SHORTEST,
  statusLabel,
  statusTone,
  type Target,
  targetOf,
} from '../schemas'

type Props = {
  /** Below `sm`: the field is an icon button that opens a full-width search under the bar. */
  compact: boolean
}

/** Typing into these is typing, not a shortcut. */
const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select, [contenteditable="true"]') !== null)

/**
 * The top bar's search (#76): one field on every page, `/` to get there. It finds strains,
 * vials, deposits and requests of the person's labs as they type, grouped by kind, in a
 * WAI-ARIA combobox with a listbox popup (APG "Editable Combobox With List Autocomplete",
 * grouped like its "Listbox with grouped options"): focus stays in the field, ArrowDown and
 * ArrowUp move the active option (aria-activedescendant), Enter opens it, Escape closes the
 * list, then clears the field, then (compact) closes the search. Enter with no active option is
 * the scanner's key: the hit the text names exactly, when it is the only one, opens at once.
 */
export function TopSearch({ compact }: Props) {
  const [text, setText] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  // Compact only: the full-width search is out.
  const [expanded, setExpanded] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const toggle = useRef<HTMLButtonElement>(null)
  const listId = useId()
  const panelId = useId()
  const navigate = useNavigate()
  const client = useQueryClient()
  const folded = normalise(text)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(folded), DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [folded])

  const searching = debounced.length >= SHORTEST
  const query = useSearch(debounced, searching)
  const shown = open && folded.length >= SHORTEST
  const groups = searching ? (query.data?.groups ?? []) : []
  const sections = entriesOf(groups, debounced)
  const entries = sections.flatMap((section) => section.entries)
  const activeEntry = active >= 0 ? entries[active] : undefined
  // The listbox exists only with results; a message alone (searching, none, failed) is no list.
  const listed = shown && query.data !== undefined && sections.length > 0

  // `/` from anywhere but a field: to the search, as on many sites (aria-keyshortcuts says so).
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== '/' || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return
      if (isTyping(event.target)) return
      // A modal dialog owns the keyboard: MUI marks the page behind it aria-hidden.
      if (document.querySelector('[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]')) return
      event.preventDefault()
      if (compact) setExpanded(true)
      // The compact field mounts with the next render: the effect below focuses it then.
      input.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [compact])

  // Opening the compact search puts the focus in its field, which mounts with it.
  useEffect(() => {
    if (expanded) input.current?.focus()
  }, [expanded])

  const finish = () => {
    setText('')
    setDebounced('')
    setOpen(false)
    setActive(-1)
    setExpanded(false)
  }
  const go = (target: Target | null) => {
    if (target === null) return
    finish()
    // The page's h1 takes focus after the navigation (Layout); the field is empty for the next one.
    void navigate(target)
  }

  // Enter with no active option: what the text names, once the answer for exactly this text is in.
  const enter = async () => {
    if (folded.length < SHORTEST) return
    setOpen(true)
    setDebounced(folded)
    try {
      const answer = await client.fetchQuery(searchOptions(folded))
      const exact = exactHit(answer.groups)
      if (exact !== null) go(targetOf(exact.kind, exact.hit))
    } catch {
      // The popup shows the failure from the query's own state.
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActive((current) => Math.min(current + 1, entries.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((current) => Math.max(current - 1, -1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (listed && activeEntry !== undefined) go(activeEntry.target)
      else void enter()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      if (shown) {
        setOpen(false)
        setActive(-1)
      } else if (text !== '') {
        setText('')
      } else if (compact) {
        setExpanded(false)
        toggle.current?.focus()
      }
    }
  }

  const field = (
    <Box sx={{ position: 'relative', width: compact ? '100%' : { sm: '16rem', md: '22rem' } }}>
      <TextField
        ref={input}
        label="Search"
        size="small"
        fullWidth
        autoComplete="off"
        value={text}
        placeholder="Number, name, label or barcode"
        onChange={(event) => {
          setText(event.target.value)
          setOpen(true)
          setActive(-1)
        }}
        onKeyDown={onKeyDown}
        onBlur={() => {
          setOpen(false)
          setActive(-1)
        }}
        slotProps={{
          htmlInput: {
            role: 'combobox',
            'aria-autocomplete': 'list',
            'aria-expanded': listed,
            'aria-controls': listed ? listId : undefined,
            'aria-activedescendant': listed && activeEntry ? `${listId}-${activeEntry.id}` : undefined,
            'aria-keyshortcuts': '/',
            'aria-describedby': `${listId}-help`,
            spellCheck: false,
          },
        }}
      />
      <Box id={`${listId}-help`} sx={visuallyHidden}>
        Strains, vials, deposits and requests of your labs. Results appear as you type.
      </Box>
      {shown && (
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
          <Results query={query} sections={sections} entries={entries} active={active} listId={listId} text={folded} onPick={go} onHover={setActive} />
        </Paper>
      )}
      {/* Mounted with the popup, before its content changes, so the counts are read out. */}
      {shown && (
        <Box component="output" sx={visuallyHidden}>
          {debounced !== folded || (query.isFetching && query.data === undefined)
            ? ''
            : query.isError
              ? `Search failed. ${errorMessage(query.error)}`
              : query.data
                ? resultsSummary(groups)
                : ''}
        </Box>
      )}
    </Box>
  )

  if (!compact) return field
  return (
    <>
      <Button
        ref={toggle}
        variant="outlined"
        aria-label="Search"
        aria-expanded={expanded}
        aria-controls={panelId}
        aria-keyshortcuts="/"
        onClick={() => setExpanded((current) => !current)}
        sx={{ minWidth: 40, px: 1 }}
      >
        <SearchIcon />
      </Button>
      {/* The bar wraps: the panel takes a row of its own under the bar's controls. */}
      <Box id={panelId} hidden={!expanded} sx={{ flexBasis: '100%', order: 1 }}>
        {expanded && field}
      </Box>
    </>
  )
}

type ResultsProps = {
  query: ReturnType<typeof useSearch>
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

function SearchIcon() {
  return (
    <Box component="svg" viewBox="0 0 24 24" aria-hidden focusable="false" sx={{ width: 20, height: 20, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' }}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </Box>
  )
}

// In px: sx reads a width of 1 as 100 % and a margin of 1 as one spacing unit.
const visuallyHidden = {
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
