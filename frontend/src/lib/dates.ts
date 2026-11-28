/**
 * Dates as YYYY-MM-DD in the Czech day (Europe/Prague), the day the server and the database
 * guards date losses, destructions and permits by (#317). The browser's own zone does not count:
 * a lab in Brno dates by Prague even when the machine runs in UTC. The Swedish locale writes ISO.
 */
export const LAB_TIME_ZONE = 'Europe/Prague'

const format = (at: Date): string => at.toLocaleDateString('sv', { timeZone: LAB_TIME_ZONE })

/** A timestamp as its Czech day. */
export const day = (iso: string): string => format(new Date(iso))

/** Today as its Czech day, the default of a date field. */
export const today = (): string => format(new Date())
