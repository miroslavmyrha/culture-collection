import { z } from 'zod'

// Zod 4 compiles object parsers with `new Function` unless jitless. The production CSP has no
// 'unsafe-eval' and enforces Trusted Types, so even its probe is a reported violation.
// main.tsx imports this module first: schemas read the setting when they are created.
z.config({ jitless: true })
