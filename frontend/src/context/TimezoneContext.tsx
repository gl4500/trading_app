import React, { createContext, useContext, useState, useEffect } from 'react'
import { browserTimeZone } from '../utils/time'

const STORAGE_KEY = 'trading_app_timezone'

interface TimezoneContextValue {
  /** The resolved IANA timezone string to use for display (never '__browser__'). */
  timeZone: string
  /** The raw stored preference — '__browser__' means auto-detect. */
  preference: string
  setPreference: (pref: string) => void
}

const TimezoneContext = createContext<TimezoneContextValue>({
  timeZone: 'UTC',
  preference: '__browser__',
  setPreference: () => {},
})

export function TimezoneProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || '__browser__'
    } catch {
      return '__browser__'
    }
  })

  const resolved = preference === '__browser__' ? browserTimeZone() : preference

  const setPreference = (pref: string) => {
    setPreferenceState(pref)
    try {
      localStorage.setItem(STORAGE_KEY, pref)
    } catch {}
  }

  return (
    <TimezoneContext.Provider value={{ timeZone: resolved, preference, setPreference }}>
      {children}
    </TimezoneContext.Provider>
  )
}

export function useTimezone(): TimezoneContextValue {
  return useContext(TimezoneContext)
}
