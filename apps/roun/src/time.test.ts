import { describe, expect, it } from 'vitest'
import { formatElapsed, formatTime, fromSerialDay, grouped, splitDateTime, toSerialDay } from './time'

describe('시간 계산', () => {
  it('오전 10시에서 6시간 뒤는 오후 4시다', () => expect(formatTime(10 * 60 + 6 * 60)).toBe('오후 4:00'))
  it('오전 11:50에서 10분 뒤는 낮 12시다', () => expect(formatTime(11 * 60 + 50 + 10)).toBe('오후 12:00'))
  it('오후 11:50에서 10분 뒤는 다음 날 자정이다', () => expect(splitDateTime(23 * 60 + 50 + 10)).toEqual({ day: 1, minute: 0 }))
  it('단위 경계를 묶는다', () => {
    expect(grouped(60, 60)).toEqual({ upper: 1, lower: 0 })
    expect(grouped(24, 24)).toEqual({ upper: 1, lower: 0 })
    expect(grouped(7, 7)).toEqual({ upper: 1, lower: 0 })
  })
  it('9월 4일부터 10일까지는 6일이다', () => expect(toSerialDay({ year: 2026, month: 9, day: 10 }) - toSerialDay({ year: 2026, month: 9, day: 4 })).toBe(6))
  it('연말을 정확히 넘긴다', () => {
    const start = toSerialDay({ year: 2026, month: 12, day: 31 }) * 1440 + 23 * 60 + 50
    const result = splitDateTime(start + 10)
    expect(fromSerialDay(result.day)).toEqual({ year: 2027, month: 1, day: 1 })
    expect(result.minute).toBe(0)
  })
  it('시작 이전 방향을 표시한다', () => expect(formatElapsed(-60)).toBe('시작보다 1시간 전'))
})
