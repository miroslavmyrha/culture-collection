// The one place feature code gets MUI from (ADR 0004). Components are re-exported unchanged;
// wrap one here only when it carries a project decision (labels, errors, confirmation).
export {
  Alert,
  AppBar,
  Box,
  Button,
  Container,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Toolbar,
  Typography,
} from '@mui/material'
export { ActionMenu, type ActionItem } from './ActionMenu'
export { AutocompleteField } from './AutocompleteField'
export { CheckboxField } from './CheckboxField'
export { ConfirmDialog } from './ConfirmDialog'
export { Link } from './Link'
export { Mono } from './Mono'
export { gridLabel, type GridCell, PositionGrid, type PositionGridHandle } from './PositionGrid'
export { SelectField } from './SelectField'
export { StatusChip, type Tone } from './StatusChip'
export { SkipLink } from './SkipLink'
export { TextField } from './TextField'
export { APP_NAME, PageTitle } from './PageTitle'
