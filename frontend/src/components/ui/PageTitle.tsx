export const APP_NAME = 'Culture collection'

/**
 * The document title, as "Page | Culture collection" (WCAG 2.4.2). React 19 hoists a <title>
 * rendered anywhere into <head>, before the static one of index.html, so the page that owns the
 * h1 renders it, including loading, error and not-found states. One page, one PageTitle: two
 * mounted at once leave two <title> elements and the first one wins.
 */
export function PageTitle({ children }: { children: string }) {
  // One string child: React warns for a <title> with several children.
  return <title>{`${children} | ${APP_NAME}`}</title>
}
