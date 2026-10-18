import { useEffect, useRef } from 'react'

const CONTROLS = 'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/** Focus an element that is not focusable by itself (a heading, main) without adding it to the tab order. */
export function focusTarget(element: HTMLElement): void {
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus()
}

/** Where focus can go back to once the control that had it may be gone. */
export type FocusReturn = { restore: () => HTMLElement | null }

/**
 * Remembers a control before an action that may remove it (a removal dialog, a retry that
 * replaces the error, a button that replaces itself). `restore()` then focuses, in this order:
 * the control itself while it is still in the document; the control at the same place in the
 * next row, else in the previous row (when it sat in a table row); the first heading of its
 * section; the page's h1 (when the section went too, as an error screen replaced by the page);
 * the page's main. Rows and the section are taken now, while the control is in the
 * document: a removed row has no siblings any more. The heading is looked up at restore time,
 * because the section may only get it after the action (a lab that loaded on retry).
 * Without this, focus on a removed element falls to the body and a keyboard user starts again
 * from the top of the page (WCAG 2.4.3).
 */
export function rememberFocus(control: HTMLElement): FocusReturn {
  const row = control.closest('tr')
  const index = row ? [...row.querySelectorAll<HTMLElement>(CONTROLS)].indexOf(control) : -1
  const neighbours = row ? [row.nextElementSibling, row.previousElementSibling] : []
  const section = control.closest('section')
  const doc = control.ownerDocument
  return {
    restore: () => {
      const candidates: (HTMLElement | null | undefined)[] = [
        control,
        ...neighbours.map((neighbour) => (index < 0 ? null : neighbour?.querySelectorAll<HTMLElement>(CONTROLS)[index])),
        section?.querySelector<HTMLElement>('h1, h2, h3, h4, h5, h6'),
        // The layout owns the one main, with tabIndex -1 for the skip link.
        doc.querySelector<HTMLElement>('main h1'),
        doc.querySelector<HTMLElement>('main'),
      ]
      const target = candidates.find((candidate) => candidate?.isConnected) ?? null
      if (target === control) target.focus()
      else if (target) focusTarget(target)
      return target
    },
  }
}

/** Whether focus fell to the body, as it does when the focused element is removed. */
export function focusLost(doc: Document = document): boolean {
  return doc.activeElement === null || doc.activeElement === doc.body
}

/**
 * For a component whose own control removes it (a retry that loads the data, "Go to the first
 * page"): call `remember(control)` in the click handler. When the component unmounts while
 * focus fell to the body, focus goes where `rememberFocus` says. A cleanup of a passive effect
 * runs after React removed the elements, so the body check sees the dropped focus.
 */
export function useFocusReturnOnUnmount(): (control: HTMLElement) => void {
  const spot = useRef<FocusReturn | null>(null)
  useEffect(
    () => () => {
      if (spot.current && focusLost()) spot.current.restore()
    },
    [],
  )
  return (control) => {
    spot.current = rememberFocus(control)
  }
}
