/** Focus an element that is not focusable by itself (a heading, main) without adding it to the tab order. */
export function focusTarget(element: HTMLElement): void {
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus()
}
