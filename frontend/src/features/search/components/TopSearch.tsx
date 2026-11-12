import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { type KeyboardEvent, type RefObject, useEffect, useId, useRef, useState } from 'react'
import { Box, Button, TextField } from '@/components/ui'
import { searchOptions, useSearch } from '../api/queries'
import { DEBOUNCE_MS, type Entry, entriesOf, exactHit, normalise, SHORTEST, type Target, targetOf } from '../schemas'
import { SearchPopup, visuallyHidden } from './SearchResults'

type Props = {
  /** Below `sm`: the field is an icon button that opens a full-width search under the bar. */
  compact: boolean
}

const FIELD_WIDTH = { sm: '16rem', md: '22rem' }
const HANDLED_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Enter', 'Escape'])

/** Typing into these is typing, not a shortcut. */
const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select, [contenteditable="true"]') !== null)

const isSlash = (event: globalThis.KeyboardEvent) => event.key === '/' && !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.altKey

/** A modal dialog owns the keyboard: MUI marks the page behind it aria-hidden. */
const modalIsOpen = () => document.querySelector('[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]') !== null

/** The text, a moment after it stopped changing: the search runs on it. It can also be set at once. */
function useDebounced(value: string) {
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [value])
  return [debounced, setDebounced] as const
}

/** The groups the search found, none while the text is too short to search. */
const groupsOf = (searching: boolean, data: ReturnType<typeof useSearch>['data']) => (searching ? (data?.groups ?? []) : [])

/** `/` from anywhere but a field goes to the search, as on many sites (aria-keyshortcuts says so). */
function useSlashShortcut(compact: boolean, input: RefObject<HTMLInputElement | null>, setExpanded: (expanded: boolean) => void) {
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (!isSlash(event) || isTyping(event.target) || modalIsOpen()) return
      event.preventDefault()
      if (compact) setExpanded(true)
      // The compact field mounts with the next render: the effect there focuses it then.
      input.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [compact, input, setExpanded])
}

/** The attributes that make the input a combobox over the listbox below it. */
function comboboxProps(listed: boolean, listId: string, activeEntry: Entry | undefined) {
  return {
    role: 'combobox',
    'aria-autocomplete': 'list',
    'aria-expanded': listed,
    'aria-controls': listed ? listId : undefined,
    'aria-activedescendant': listed && activeEntry ? `${listId}-${activeEntry.id}` : undefined,
    'aria-keyshortcuts': '/',
    'aria-describedby': `${listId}-help`,
    spellCheck: false,
  } as const
}

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
  const folded = normalise(text)
  const [debounced, setDebounced] = useDebounced(folded)
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

  const searching = debounced.length >= SHORTEST
  const query = useSearch(debounced, searching)
  const shown = open && folded.length >= SHORTEST
  const groups = groupsOf(searching, query.data)
  const sections = entriesOf(groups, debounced)
  const entries = sections.flatMap((section) => section.entries)
  const activeEntry = active >= 0 ? entries[active] : undefined
  // The listbox exists only with results; a message alone (searching, none, failed) is no list.
  const listed = shown && query.data !== undefined && sections.length > 0

  useSlashShortcut(compact, input, setExpanded)

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

  const escape = () => {
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
  const press = (key: string) => {
    switch (key) {
      case 'ArrowDown':
        setOpen(true)
        setActive((current) => Math.min(current + 1, entries.length - 1))
        break
      case 'ArrowUp':
        setActive((current) => Math.max(current - 1, -1))
        break
      case 'Enter':
        if (listed && activeEntry !== undefined) go(activeEntry.target)
        else void enter()
        break
      default:
        escape()
    }
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!HANDLED_KEYS.has(event.key)) return
    event.preventDefault()
    press(event.key)
  }

  const field = (
    <Box sx={{ position: 'relative', width: compact ? '100%' : FIELD_WIDTH }}>
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
        slotProps={{ htmlInput: comboboxProps(listed, listId, activeEntry) }}
      />
      <Box id={`${listId}-help`} sx={visuallyHidden}>
        Strains, vials, deposits and requests of your labs. Results appear as you type.
      </Box>
      <SearchPopup
        shown={shown}
        compact={compact}
        query={query}
        groups={groups}
        sections={sections}
        entries={entries}
        active={active}
        listId={listId}
        text={folded}
        answered={debounced}
        onPick={go}
        onHover={setActive}
      />
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

function SearchIcon() {
  return (
    <Box component="svg" viewBox="0 0 24 24" aria-hidden focusable="false" sx={{ width: 20, height: 20, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' }}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </Box>
  )
}
