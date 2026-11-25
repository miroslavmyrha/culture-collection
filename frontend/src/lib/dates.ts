/** A date as YYYY-MM-DD in local time (the Swedish locale writes ISO dates). */
export const day = (iso: string): string => new Date(iso).toLocaleDateString('sv')

/** Today as YYYY-MM-DD in local time, the default of a date field. */
export const today = (): string => new Date().toLocaleDateString('sv')
