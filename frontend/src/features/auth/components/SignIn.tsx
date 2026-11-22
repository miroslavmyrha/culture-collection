import { useState } from 'react'
import { Alert } from '@/components/ui'
import type { components } from '@/api/schema'
import type { Me, Method } from '../api/factors'
import { EnrolForm } from './EnrolForm'
import { EnrolmentCodeForm } from './EnrolmentCodeForm'
import { LoginForm } from './LoginForm'
import { RecoveryCodes } from './RecoveryCodes'
import { SecondFactorForm } from './SecondFactorForm'

type Stage = { kind: 'password' } | { kind: 'second_factor'; methods: Method[] } | { kind: 'code' } | { kind: 'enrol' } | { kind: 'codes'; codes: string[] }
type Step = components['schemas']['LoginStepOutput']

/** The sign-in in two steps (#176): the password, then a second factor or its enrolment. */
export function SignIn({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [stage, setStage] = useState<Stage>({ kind: 'password' })
  const [expired, setExpired] = useState(false)
  const [me, setMe] = useState<Me | null>(null)
  const restart = () => {
    setExpired(true)
    setStage({ kind: 'password' })
  }
  const afterPassword = (step: Step) => {
    setExpired(false)
    setStage(step.step === 'enrol' ? { kind: 'code' } : { kind: 'second_factor', methods: step.methods })
  }
  if (stage.kind === 'password') {
    return (
      <>
        {expired && <Alert severity="info">The sign-in took too long. Sign in again.</Alert>}
        <LoginForm onSuccess={afterPassword} />
      </>
    )
  }
  if (stage.kind === 'second_factor') return <SecondFactorForm methods={stage.methods} onSignedIn={onSignedIn} onRestart={restart} />
  if (stage.kind === 'codes') return <RecoveryCodes codes={stage.codes} onDone={() => me && onSignedIn(me)} />
  if (stage.kind === 'code') return <EnrolmentCodeForm onAccepted={() => setStage({ kind: 'enrol' })} onRestart={restart} />
  return (
    <EnrolForm
      onEnrolled={(result) => {
        setMe(result.me)
        setStage({ kind: 'codes', codes: result.recovery_codes })
      }}
      onRestart={restart}
    />
  )
}
