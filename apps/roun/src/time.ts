export const MINUTES_PER_DAY = 1440

export interface DateParts { year: number; month: number; day: number }

export function mod(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor
}

export function formatTime(totalMinutes: number) {
  const minutes = mod(totalMinutes, MINUTES_PER_DAY)
  const hour24 = Math.floor(minutes / 60)
  const minute = minutes % 60
  const period = hour24 < 12 ? '오전' : '오후'
  const hour = hour24 % 12 || 12
  return `${period} ${hour}:${String(minute).padStart(2, '0')}`
}

export function formatElapsed(deltaMinutes: number, includeTotal = false) {
  if (deltaMinutes === 0) return '0분'
  const direction = deltaMinutes < 0 ? '시작보다 ' : ''
  const suffix = deltaMinutes < 0 ? ' 전' : ''
  let value = Math.abs(deltaMinutes)
  const days = Math.floor(value / MINUTES_PER_DAY)
  value %= MINUTES_PER_DAY
  const hours = Math.floor(value / 60)
  const minutes = value % 60
  const parts = [days && `${days}일`, hours && `${hours}시간`, minutes && `${minutes}분`].filter(Boolean)
  if (!includeTotal && parts.length === 0) parts.push('0분')
  return `${direction}${parts.join(' ')}${suffix}`
}

export function toSerialDay(date: DateParts) {
  return Math.floor(Date.UTC(date.year, date.month - 1, date.day) / 86_400_000)
}

export function fromSerialDay(serial: number): DateParts {
  const date = new Date(serial * 86_400_000)
  return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() }
}

export function formatDate(serial: number) {
  const { year, month, day } = fromSerialDay(serial)
  return `${year}년 ${month}월 ${day}일`
}

export function splitDateTime(absoluteMinutes: number) {
  return { day: Math.floor(absoluteMinutes / MINUTES_PER_DAY), minute: mod(absoluteMinutes, MINUTES_PER_DAY) }
}

export function formatDateTime(absoluteMinutes: number) {
  const value = splitDateTime(absoluteMinutes)
  return `${formatDate(value.day)} ${formatTime(value.minute)}`
}

export function monthGrid(year: number, month: number) {
  const first = toSerialDay({ year, month, day: 1 })
  const firstWeekday = new Date(first * 86_400_000).getUTCDay()
  const nextMonth = month === 12 ? { year: year + 1, month: 1, day: 1 } : { year, month: month + 1, day: 1 }
  const days = toSerialDay(nextMonth) - first
  return Array.from({ length: firstWeekday + days }, (_, index) => index < firstWeekday ? null : first + index - firstWeekday)
}

export function grouped(value: number, base: number) {
  const safe = Math.max(0, value)
  return { upper: Math.floor(safe / base), lower: safe % base }
}
