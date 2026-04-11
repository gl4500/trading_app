/**
 * Timezone-aware time formatting utilities.
 *
 * All ISO strings coming from the backend are UTC (have a "+00:00" or "Z" suffix,
 * or are naive-UTC strings that JavaScript's Date constructor treats as UTC).
 * Pass them through these helpers so display respects the user's selected timezone.
 */

/**
 * Format an ISO timestamp string for display.
 * Falls back gracefully if the string is malformed.
 *
 * @param iso       ISO 8601 string from backend (UTC)
 * @param timeZone  IANA timezone name, e.g. "America/New_York"
 * @param options   Additional Intl.DateTimeFormatOptions overrides
 */
export function formatTs(
  iso: string | undefined | null,
  timeZone: string,
  options: Intl.DateTimeFormatOptions = {}
): string {
  if (!iso) return '—'
  // Normalise: backend may store naive-UTC strings without the Z suffix
  const normalised = iso.endsWith('Z') || iso.includes('+') || iso.includes('-', 10)
    ? iso
    : iso + 'Z'
  const d = new Date(normalised)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, { timeZone, ...options })
}

/** Format just the date portion (YYYY-MM-DD style) in the user's timezone. */
export function formatDate(iso: string | undefined | null, timeZone: string): string {
  if (!iso) return '—'
  return formatTs(iso, timeZone, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

/** Format just the time portion (HH:MM:SS) in the user's timezone. */
export function formatTime(iso: string | undefined | null, timeZone: string): string {
  if (!iso) return '—'
  return formatTs(iso, timeZone, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

/** Return the browser's IANA timezone string, e.g. "America/Chicago". */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** Common IANA timezone options for the selector dropdown. */
export const TIMEZONE_OPTIONS: { label: string; value: string }[] = [
  { label: 'Browser default', value: '__browser__' },
  { label: 'UTC',             value: 'UTC' },
  { label: 'ET (New York)',   value: 'America/New_York' },
  { label: 'CT (Chicago)',    value: 'America/Chicago' },
  { label: 'MT (Denver)',     value: 'America/Denver' },
  { label: 'PT (Los Angeles)',value: 'America/Los_Angeles' },
  { label: 'GMT (London)',    value: 'Europe/London' },
  { label: 'CET (Paris)',     value: 'Europe/Paris' },
  { label: 'IST (Kolkata)',   value: 'Asia/Kolkata' },
  { label: 'JST (Tokyo)',     value: 'Asia/Tokyo' },
  { label: 'AEST (Sydney)',   value: 'Australia/Sydney' },
]
