import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { formatDate, formatDateTime, formatElapsed, formatTime, fromSerialDay, grouped, MINUTES_PER_DAY, mod, monthGrid, splitDateTime, toSerialDay } from './time'

type Tab = 'clock' | 'calendar' | 'combined' | 'units'
type UnitTab = 'seconds' | 'minutes' | 'hours' | 'days'
const TABS: { id: Tab; label: string }[] = [
  { id: 'clock', label: '시계' }, { id: 'calendar', label: '달력' },
  { id: 'combined', label: '날짜＋시간' }, { id: 'units', label: '단위 배우기' },
]
const today = new Date()
const TODAY = toSerialDay({ year: today.getFullYear(), month: today.getMonth() + 1, day: today.getDate() })

function readStore<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) as T : fallback } catch { return fallback }
}

function HoldButton({ delta, onStep, children, label, className = '' }: { delta: number; onStep: (n: number) => void; children: React.ReactNode; label: string; className?: string }) {
  const timeout = useRef<number | null>(null)
  const interval = useRef<number | null>(null)
  const repeated = useRef(false)
  const stop = useCallback(() => {
    if (timeout.current !== null) window.clearTimeout(timeout.current)
    if (interval.current !== null) window.clearInterval(interval.current)
    timeout.current = interval.current = null
  }, [])
  useEffect(() => stop, [stop])
  const down = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    repeated.current = false
    timeout.current = window.setTimeout(() => {
      repeated.current = true
      onStep(delta)
      interval.current = window.setInterval(() => onStep(delta), 120)
    }, 500)
  }
  return <button className={className} type="button" aria-label={label} onPointerDown={down} onPointerUp={() => { stop(); if (!repeated.current) onStep(delta) }} onPointerCancel={stop} onLostPointerCapture={stop}>{children}</button>
}

function Info({ label, value, hidden = false }: { label: string; value: string; hidden?: boolean }) {
  return <div className="infoRow"><dt>{label}</dt><dd className={hidden ? 'hiddenAnswer' : ''}>{hidden ? '정답을 생각해 보세요' : value}</dd></div>
}

function AnalogClock({ minute }: { minute: number }) {
  const hourAngle = (minute / 60) * 30
  const minuteAngle = (minute % 60) * 6
  return <div className="analog" role="img" aria-label={`아날로그시계 ${formatTime(minute)}`}>
    {Array.from({ length: 12 }, (_, i) => <span key={i} className="tick" style={{ transform: `rotate(${i * 30}deg)` }} />)}
    <span className="hand hour" style={{ transform: `rotate(${hourAngle}deg)` }} /><span className="hand minute" style={{ transform: `rotate(${minuteAngle}deg)` }} /><i />
  </div>
}

function TimeEditor({ initial, onSave, onClose }: { initial: number; onSave: (minute: number) => void; onClose: () => void }) {
  const hour24 = mod(initial, MINUTES_PER_DAY) / 60
  const [period, setPeriod] = useState(Math.floor(hour24) < 12 ? '오전' : '오후')
  const [hour, setHour] = useState(String(Math.floor(hour24) % 12 || 12))
  const [minute, setMinute] = useState(String(mod(initial, 60)).padStart(2, '0'))
  const save = () => {
    const h = Number(hour), m = Number(minute)
    if (h < 1 || h > 12 || m < 0 || m > 59) return
    onSave((h % 12 + (period === '오후' ? 12 : 0)) * 60 + m)
  }
  return <div className="modalBack" role="presentation" onMouseDown={e => e.target === e.currentTarget && onClose()}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="timeEditorTitle">
    <h2 id="timeEditorTitle">새 시작 시간</h2><p>숫자를 직접 입력하세요.</p>
    <button className="periodButton" onClick={() => setPeriod(period === '오전' ? '오후' : '오전')}>{period}</button>
    <div className="timeInputs"><label>시<input inputMode="numeric" pattern="[0-9]*" value={hour} onChange={e => setHour(e.target.value.replace(/\D/g, '').slice(0, 2))} /></label><b>:</b><label>분<input inputMode="numeric" pattern="[0-9]*" value={minute} onChange={e => setMinute(e.target.value.replace(/\D/g, '').slice(0, 2))} onBlur={() => setMinute(String(Number(minute || 0)).padStart(2, '0'))} /></label></div>
    <div className="modalActions"><button onClick={onClose}>취소</button><button className="primary" onClick={save}>시작하기</button></div>
  </section></div>
}

function makeClockQuiz() {
  const start = Math.floor(Math.random() * 24) * 60 + Math.floor(Math.random() * 6) * 10
  return { start, current: start, target: start + (Math.floor(Math.random() * 8) + 1) * 60 }
}

function ClockMode() {
  const saved = readStore<{ start: number; current: number; target?: number }>('roun.clock', { start: 600, current: 600, target: 960 })
  const [start, setStart] = useState(saved.start)
  const [current, setCurrent] = useState(saved.current)
  const [target, setTarget] = useState(saved.target ?? saved.start + 360)
  const [editing, setEditing] = useState(false)
  const [result, setResult] = useState<'idle' | 'correct' | 'wrong'>('idle')
  const [playTarget, setPlayTarget] = useState<number | null>(null)
  useEffect(() => localStorage.setItem('roun.clock', JSON.stringify({ start, current, target })), [start, current, target])
  useEffect(() => {
    if (playTarget === null) return
    if (current === playTarget) { setPlayTarget(null); return }
    const timer = window.setTimeout(() => setCurrent(value => value + Math.sign(playTarget - value) * Math.min(10, Math.abs(playTarget - value))), 90)
    return () => window.clearTimeout(timer)
  }, [playTarget, current])
  const displayed = mod(current, MINUTES_PER_DAY)
  const h24 = Math.floor(displayed / 60), period = h24 < 12 ? '오전' : '오후', hour = h24 % 12 || 12, minute = displayed % 60
  const move = (amount: number) => { setResult('idle'); setPlayTarget(null); setCurrent(value => value + amount) }
  const switchPeriod = () => move(h24 < 12 ? 720 : -720)
  const targetDay = Math.floor(target / MINUTES_PER_DAY) - Math.floor(start / MINUTES_PER_DAY)
  const targetText = `${targetDay > 0 ? '다음 날 ' : ''}${formatTime(target)}`
  const newQuiz = () => { const quiz = makeClockQuiz(); setStart(quiz.start); setCurrent(quiz.current); setTarget(quiz.target); setResult('idle'); setPlayTarget(null) }
  return <section className="mode"><section className="quizCard" aria-labelledby="clockQuestion"><p>시계 퀴즈</p><h2 id="clockQuestion"><strong>{formatTime(start)}</strong>부터<br /><strong>{targetText}</strong>까지는 몇 시간일까요?</h2><span>아래 시계를 목표 시간까지 직접 움직여 보세요.</span></section><div className="clockLayout"><div className="digitalCard">
    <div className="digitalGrid"><span /><HoldButton delta={60} onStep={move} label="한 시간 증가">＋</HoldButton><span /><HoldButton delta={10} onStep={move} label="십 분 증가">＋</HoldButton>
    <button className="period" onClick={switchPeriod}>{period}</button><button className="digit" onClick={() => setEditing(true)} aria-label={`시 ${hour}`}>{hour}</button><b>:</b><button className="digit" onClick={() => setEditing(true)} aria-label={`분 ${minute}`}>{String(minute).padStart(2, '0')}</button>
    <span /><HoldButton delta={-60} onStep={move} label="한 시간 감소">−</HoldButton><span /><HoldButton delta={-10} onStep={move} label="십 분 감소">−</HoldButton></div>
    <small>{displayed === 720 ? '낮 12시' : displayed === 0 ? '밤 12시' : '버튼을 길게 누르면 계속 움직여요'}</small>
  </div><AnalogClock minute={displayed} /></div>
  <dl className="infoCard"><Info label="시작 시간" value={formatTime(start)} /><Info label="내가 맞춘 시간" value={formatTime(current)} /><Info label="경과 시간" value={formatElapsed(current - start)} hidden={result !== 'correct'} /></dl>
  {result !== 'idle' && <div className={`quizFeedback ${result}`} role="status">{result === 'correct' ? `정답이에요! ${formatElapsed(target - start)}이 지났어요.` : current < target ? '아직 목표 시간 전이에요. 시계를 조금 더 움직여 보세요.' : '목표 시간을 지났어요. 시계를 조금 뒤로 움직여 보세요.'}</div>}
  <div className="actions quizActions"><button onClick={() => { setCurrent(start); setResult('idle'); setPlayTarget(null) }}>처음으로</button><button className="primary" onClick={() => setResult(current === target ? 'correct' : 'wrong')}>정답 확인</button><button onClick={newQuiz}>새 문제</button><button onClick={() => { setPlayTarget(target); setCurrent(start); setResult('idle') }} disabled={playTarget !== null}>{playTarget !== null ? '보는 중…' : '풀이 보기'}</button></div>
  {editing && <TimeEditor initial={current} onClose={() => setEditing(false)} onSave={value => { const duration = target - start; setStart(value); setCurrent(value); setTarget(value + duration); setResult('idle'); setPlayTarget(null); setEditing(false) }} />}</section>
}

function CalendarMode() {
  const stored = readStore('roun.calendar', { start: TODAY, current: TODAY })
  const [start, setStart] = useState(stored.start), [current, setCurrent] = useState(stored.current)
  const currentParts = fromSerialDay(current)
  const [view, setView] = useState({ year: currentParts.year, month: currentParts.month })
  useEffect(() => localStorage.setItem('roun.calendar', JSON.stringify({ start, current })), [start, current])
  const move = (days: number) => { const next = current + days; setCurrent(next); const p = fromSerialDay(next); setView({ year: p.year, month: p.month }) }
  const cells = monthGrid(view.year, view.month), low = Math.min(start, current), high = Math.max(start, current)
  const shiftMonth = (n: number) => { const index = view.year * 12 + view.month - 1 + n; setView({ year: Math.floor(index / 12), month: mod(index, 12) + 1 }) }
  return <section className="mode"><div className="calendarCard"><header><button aria-label="이전 달" onClick={() => shiftMonth(-1)}>‹</button><h2>{view.year}년 {view.month}월</h2><button aria-label="다음 달" onClick={() => shiftMonth(1)}>›</button></header><div className="weekdays">{'일월화수목금토'.split('').map(x => <b key={x}>{x}</b>)}</div><div className="monthGrid">{cells.map((day, i) => day === null ? <span key={`blank-${i}`} /> : <button key={day} className={`${day >= low && day <= high ? 'passed ' : ''}${day === start ? 'start ' : ''}${day === current ? 'current' : ''}`} aria-label={`${formatDate(day)}${day === start ? ' 시작일' : ''}${day === current ? ' 현재 날짜' : ''}`} onClick={() => { setStart(day); setCurrent(day) }}>{fromSerialDay(day).day}</button>)}</div></div>
  <div className="stepButtons"><HoldButton delta={-7} onStep={move} label="7일 전">−7일</HoldButton><HoldButton delta={-1} onStep={move} label="1일 전">−1일</HoldButton><HoldButton delta={1} onStep={move} label="1일 뒤">＋1일</HoldButton><HoldButton delta={7} onStep={move} label="7일 뒤">＋7일</HoldButton></div>
  <dl className="infoCard"><Info label="시작 날짜" value={formatDate(start)} /><Info label="현재 날짜" value={formatDate(current)} /><Info label="경과 날짜" value={current >= start ? `${current - start}일` : `시작보다 ${start - current}일 전`} /></dl></section>
}

function DateTimeForm({ value, onSave, onClose }: { value: number; onSave: (n: number) => void; onClose: () => void }) {
  const parts = splitDateTime(value), date = fromSerialDay(parts.day)
  const [dateValue, setDateValue] = useState(`${date.year}-${String(date.month).padStart(2, '0')}-${String(date.day).padStart(2, '0')}`)
  const [timeValue, setTimeValue] = useState(`${String(Math.floor(parts.minute / 60)).padStart(2, '0')}:${String(parts.minute % 60).padStart(2, '0')}`)
  const save = () => { const [year, month, day] = dateValue.split('-').map(Number), [hour, minute] = timeValue.split(':').map(Number); onSave(toSerialDay({ year, month, day }) * MINUTES_PER_DAY + hour * 60 + minute) }
  return <div className="modalBack"><section className="modal" role="dialog" aria-modal="true"><h2>시작 날짜와 시간</h2><label>날짜<input type="date" value={dateValue} onChange={e => setDateValue(e.target.value)} /></label><label>시간<input type="time" value={timeValue} onChange={e => setTimeValue(e.target.value)} /></label><div className="modalActions"><button onClick={onClose}>취소</button><button className="primary" onClick={save}>시작하기</button></div></section></div>
}

function CombinedMode() {
  const initial = TODAY * MINUTES_PER_DAY + 600, saved = readStore('roun.combined', { start: initial, current: initial })
  const [start, setStart] = useState(saved.start), [current, setCurrent] = useState(saved.current), [editing, setEditing] = useState(false)
  useEffect(() => localStorage.setItem('roun.combined', JSON.stringify({ start, current })), [start, current])
  const delta = current - start
  return <section className="mode"><div className="combinedHero"><div><span>시작</span><strong>{formatDateTime(start)}</strong></div><div><span>현재</span><strong>{formatDateTime(current)}</strong></div><div className="elapsed"><span>경과</span><strong>{formatElapsed(delta)}</strong></div><div><span>총 시간</span><strong>{delta < 0 ? '−' : ''}{Math.floor(Math.abs(delta) / 60)}시간{Math.abs(delta) % 60 ? ` ${Math.abs(delta) % 60}분` : ''}</strong></div></div>
  <div className="stepButtons six"><HoldButton delta={-MINUTES_PER_DAY} onStep={n => setCurrent(v => v + n)} label="1일 전">−1일</HoldButton><HoldButton delta={MINUTES_PER_DAY} onStep={n => setCurrent(v => v + n)} label="1일 뒤">＋1일</HoldButton><HoldButton delta={-60} onStep={n => setCurrent(v => v + n)} label="1시간 전">−1시간</HoldButton><HoldButton delta={60} onStep={n => setCurrent(v => v + n)} label="1시간 뒤">＋1시간</HoldButton><HoldButton delta={-10} onStep={n => setCurrent(v => v + n)} label="10분 전">−10분</HoldButton><HoldButton delta={10} onStep={n => setCurrent(v => v + n)} label="10분 뒤">＋10분</HoldButton></div>
  <div className="actions"><button onClick={() => setCurrent(start)}>처음으로</button><button className="primary" onClick={() => setEditing(true)}>새 시작 설정</button></div>{editing && <DateTimeForm value={current} onClose={() => setEditing(false)} onSave={n => { setStart(n); setCurrent(n); setEditing(false) }} />}</section>
}

const unitConfigs = {
  seconds: { tab: '초 → 분', lower: '초', upper: '분', base: 60, equation: '60초 = 1분', initial: 59 },
  minutes: { tab: '분 → 시간', lower: '분', upper: '시간', base: 60, equation: '60분 = 1시간', initial: 50 },
  hours: { tab: '시간 → 하루', lower: '시간', upper: '일', base: 24, equation: '24시간 = 1일', initial: 23 },
  days: { tab: '일 → 일주일', lower: '일', upper: '주일', base: 7, equation: '7일 = 1주일', initial: 6 },
} as const

function UnitsMode() {
  const [tab, setTab] = useState<UnitTab>(readStore('roun.unitTab', 'seconds'))
  const config = unitConfigs[tab], [value, setValue] = useState<number>(config.initial), [pulse, setPulse] = useState(false)
  useEffect(() => { setValue(unitConfigs[tab].initial); localStorage.setItem('roun.unitTab', JSON.stringify(tab)) }, [tab])
  const change = (delta: number) => setValue(old => { const next = Math.max(0, old + delta); if (Math.floor(old / config.base) !== Math.floor(next / config.base)) { setPulse(false); requestAnimationFrame(() => setPulse(true)); window.setTimeout(() => setPulse(false), 800) } return next })
  const result = grouped(value, config.base)
  return <section className="mode"><div className="subTabs" role="tablist">{Object.entries(unitConfigs).map(([id, item]) => <button role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id as UnitTab)} key={id}>{item.tab}</button>)}</div><div className={`unitCard ${pulse ? 'boundary' : ''}`} aria-live="polite"><p className="equation">{config.equation}</p><div className="rawValue">{value}{config.lower}</div><div className="conversion" aria-label={`${result.upper}${config.upper} ${result.lower}${config.lower}`}><span><strong>{result.upper}</strong>{config.upper}</span><i>＋</i><span><strong>{result.lower}</strong>{config.lower}</span></div><div className="unitButtons"><HoldButton delta={-1} onStep={change} label={`${config.lower} 감소`}>−</HoldButton><HoldButton delta={1} onStep={change} label={`${config.lower} 증가`}>＋</HoldButton></div><p className="hint">{result.lower === 0 && result.upper > 0 ? `${config.lower}이 모여 ${config.upper} 1개가 되었어요!` : `${config.base}${config.lower}이 모이면 ${config.upper} 1개가 돼요.`}</p></div></section>
}

export default function App() {
  const [tab, setTab] = useState<Tab>(readStore('roun.tab', 'clock'))
  const [update, setUpdate] = useState<((reloadPage?: boolean) => Promise<void>) | null>(null)
  useEffect(() => { localStorage.setItem('roun.tab', JSON.stringify(tab)) }, [tab])
  useEffect(() => { const listener = (event: Event) => setUpdate(() => (event as CustomEvent<(reloadPage?: boolean) => Promise<void>>).detail); window.addEventListener('roun-update', listener); return () => window.removeEventListener('roun-update', listener) }, [])
  const view = useMemo(() => tab === 'clock' ? <ClockMode /> : tab === 'calendar' ? <CalendarMode /> : tab === 'combined' ? <CombinedMode /> : <UnitsMode />, [tab])
  return <><header className="appHeader"><div><span>차근차근 배우는</span><h1>시간 탐험</h1></div><nav role="tablist" aria-label="학습 모드">{TABS.map(item => <button role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)} key={item.id}>{item.label}</button>)}</nav></header><main>{view}</main>{update && <aside className="updateToast" role="status">새 버전이 준비됐어요.<button onClick={() => void update(true)}>업데이트</button><button onClick={() => setUpdate(null)}>나중에</button></aside>}</>
}
