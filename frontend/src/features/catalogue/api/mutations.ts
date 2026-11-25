import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, isApiError, readProblem, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'

type Schemas = components['schemas']
export type Checked = Schemas['CatalogueCheckOutput']
export type Imported = Schemas['CatalogueImportOutput']
export type RowError = Schemas['CatalogueRowError']

const lab = (labId: string) => ({ params: { path: { lab_public_id: labId } } })

/** The file as multipart/form-data, with the text fields beside it. */
function upload(file: File, fields: Record<string, string> = {}): FormData {
  const data = new FormData()
  for (const [name, value] of Object.entries(fields)) data.append(name, value)
  data.append('file', file)
  return data
}

/** The template's URL: a plain link downloads it with the session cookie. */
export const templateUrl = (labId: string) => `/api/v1/labs/${labId}/deposits/catalogue-template/`

/** Every row tried, every error reported, nothing written. */
export function useCheckCatalogue(labId: string) {
  return useMutation({
    mutationFn: async (file: File) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/deposits/catalogue-check/', {
          ...lab(labId),
          body: { file: file.name },
          bodySerializer: () => upload(file),
        }),
      )
    },
    meta: { handlesError: true },
  })
}

/** The checked file, all rows or none. The new strains change the lab's lists and figures. */
export function useImportCatalogue(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, sha256, reason }: { file: File; sha256: string; reason: string }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/deposits/catalogue-import/', {
          ...lab(labId),
          body: { file: file.name, sha256, reason },
          bodySerializer: () => upload(file, { sha256, reason }),
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: sharedKeys.strains(labId) }),
        qc.invalidateQueries({ queryKey: ['deposits', labId] }),
        qc.invalidateQueries({ queryKey: sharedKeys.overview() }),
      ]),
  })
}

/** The import's own refusals carry a message written for the person (catalogue.py). */
const OWN_CODES = new Set(['catalogue_refused', 'catalogue_changed', 'catalogue_has_errors', 'reason_required'])

export function refusal(error: unknown): string | undefined {
  if (!isApiError(error, 422) || !OWN_CODES.has(error.code ?? '')) return undefined
  return readProblem(error.body)?.detail
}
