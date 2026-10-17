// The one place feature code gets MUI from (ADR 0004). Components are re-exported unchanged;
// wrap one here only when it carries a project decision (labels, errors, confirmation).
export { Alert, AppBar, Box, Button, Container, Paper, Stack, Toolbar, Typography } from '@mui/material'
export { Link } from './Link'
export { SkipLink } from './SkipLink'
export { TextField } from './TextField'
