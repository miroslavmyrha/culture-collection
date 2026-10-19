import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Alert, Box, Button, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { usePublishMta } from '../api/mutations'
import { type MtaForm, type MtaTemplate, mtaSchema } from '../schemas'

type Props = {
  labId: string
  /** The version to start from: its code, title and text. */
  from?: MtaTemplate
  onPublished: (template: MtaTemplate) => void
}

const FIELDS = ['code', 'title', 'text'] as const

/**
 * For managers: publish an MTA version. The server numbers it (1 for a new code), freezes the
 * text and stores its SHA-256. A text with a mistake is replaced by a new version, never edited.
 */
export function PublishMtaForm({ labId, from, onPublished }: Props) {
  const publish = usePublishMta(labId)
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<MtaForm>({
    resolver: zodResolver(mtaSchema),
    defaultValues: { code: from?.code ?? '', title: from?.title ?? '', text: from?.text ?? '' },
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (publish.isPending) return // aria-disabled keeps focus on the button, so guard here
    setFailure(undefined)
    publish.mutate(
      { code: values.code.trim().toUpperCase(), title: values.title.trim(), text: values.text },
      {
        onSuccess: (template) => onPublished(template),
        onError: (error) => {
          if (isApiError(error, 409) && error.code === 'mta_version_taken') setFailure('Another version of this MTA was published at the same moment. Publish again.')
          else if (!applyServerErrors(error, FIELDS, setError)) setFailure(errorMessage(error))
        },
      },
    )
  })
  const message = errors.root?.server?.message ?? failure
  return (
    <Box component="form" onSubmit={onSubmit} noValidate aria-label="Publish an MTA version">
      <Stack spacing={2} sx={{ maxWidth: 720 }}>
        <Typography>
          {from ? `This publishes version ${from.version + 1} of ${from.code}.` : 'A new code starts at version 1; an existing code gets its next version.'} Once
          published, the text never changes.
        </Typography>
        <TextField label="Code" hint="Letters, digits and hyphens, for example STD" autoComplete="off" error={errors.code?.message} {...register('code')} />
        <TextField label="Title" autoComplete="off" error={errors.title?.message} {...register('title')} />
        <TextField label="Text" hint="The agreement as the recipient reads it." multiline minRows={8} error={errors.text?.message} {...register('text')} />
        {message && <Alert severity="error">{message}</Alert>}
        <Box>
          <Button type="submit" variant="contained" aria-disabled={publish.isPending}>
            Publish the version
          </Button>
        </Box>
      </Stack>
    </Box>
  )
}
