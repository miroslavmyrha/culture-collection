import type { RouterEvents } from '@tanstack/react-router'
import { focusTarget } from '@/lib/focus'

/**
 * Whether a rendered navigation moves focus to the new page. Only when the path changed:
 * - not on the first load (no `fromLocation`): the browser starts at the top already, and a
 *   screen reader reads the page from there;
 * - not on a search-only change (Pager, filters): the user stays where they pressed;
 * - not when the URL has a hash: the browser or the skip link places the focus.
 * pathChanged, fromLocation and the hash come from the router's onRendered event
 * (@tanstack/router-core 1.171.37, router.js getLocationChangeInfo, load-client.js:969).
 */
export function movesFocus({ fromLocation, toLocation, pathChanged }: RouterEvents['onRendered']): boolean {
  return fromLocation !== undefined && pathChanged && toLocation.hash === ''
}

/**
 * Focus the page's h1, which a screen reader then reads, or main when the page has none. Both
 * get tabIndex -1: a focus target, not a stop in the tab order.
 */
export function focusPageStart(main: HTMLElement): void {
  focusTarget(main.querySelector<HTMLElement>('h1') ?? main)
}
