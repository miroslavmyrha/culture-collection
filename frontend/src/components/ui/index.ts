// The one place feature code gets MUI from (ADR 0004). Components are re-exported unchanged;
// wrap one here only when it carries a project decision (labels, errors, confirmation).
export {
  Alert,
  AppBar,
  Box,
  Button,
  Container,
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
export { ConfirmDialog } from './ConfirmDialog'
export { Link } from './Link'
export { SelectField } from './SelectField'
export { SkipLink } from './SkipLink'
export { TextField } from './TextField'
