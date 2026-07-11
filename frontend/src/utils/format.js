// Shared time/duration formatters.

// "3:07" or "--" when unknown. For durations shown in lists/tables.
export function formatDuration(seconds) {
  if (!seconds) return '--'
  const m = Math.floor(seconds / 60)
  const s = String(Math.floor(seconds % 60)).padStart(2, '0')
  return `${m}:${s}`
}

// "3:07" or "0:00" when unknown. For live elapsed/remaining tickers.
export function formatClock(seconds) {
  if (!seconds || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = String(Math.floor(seconds % 60)).padStart(2, '0')
  return `${m}:${s}`
}

// Full local date + time, e.g. "7/10/2026, 3:07:12 PM".
export function formatTimestamp(value) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleString()
}

// Local time of day only, e.g. "3:07:12 PM".
export function formatTimeOfDay(value) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}
