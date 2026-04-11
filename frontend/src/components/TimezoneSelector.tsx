import React from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { TIMEZONE_OPTIONS, browserTimeZone } from '../utils/time'

export default function TimezoneSelector() {
  const { preference, timeZone, setPreference } = useTimezone()

  return (
    <div className="flex items-center gap-1.5 text-xs text-gray-400">
      <span className="hidden sm:inline">🕐</span>
      <select
        value={preference}
        onChange={e => setPreference(e.target.value)}
        title={`Display timezone: ${timeZone}`}
        className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 text-xs hover:border-gray-500 transition-colors cursor-pointer"
      >
        {TIMEZONE_OPTIONS.map(opt => (
          <option key={opt.value} value={opt.value}>
            {opt.value === '__browser__' ? `Auto (${browserTimeZone()})` : opt.label}
          </option>
        ))}
      </select>
    </div>
  )
}
