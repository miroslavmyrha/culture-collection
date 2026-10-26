/** The lab's permits (#82): one list per lab, read by managers only. */
export const permitKeys = {
  all: ['permits'] as const,
  list: (labId: string) => [...permitKeys.all, labId] as const,
}
