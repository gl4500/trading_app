import React, { useRef, useEffect, useState } from 'react'

interface MarketOverviewProps {
  prices: Record<string, number>
  watchlist: string[]
}

interface PriceData {
  symbol: string
  price: number
  prevPrice: number
  change: number
  changePct: number
}

// Color flash duration in ms
const FLASH_DURATION = 1200

export default function MarketOverview({ prices, watchlist }: MarketOverviewProps) {
  const prevPricesRef = useRef<Record<string, number>>({})
  const [flashState, setFlashState] = useState<Record<string, 'up' | 'down' | null>>({})
  const displaySymbols = watchlist.length > 0 ? watchlist : Object.keys(prices)

  // Detect price changes and trigger flash
  useEffect(() => {
    const newFlashes: Record<string, 'up' | 'down'> = {}
    let hasChanges = false

    for (const sym of displaySymbols) {
      const current = prices[sym]
      const prev = prevPricesRef.current[sym]
      if (prev !== undefined && current !== undefined && current !== prev) {
        newFlashes[sym] = current > prev ? 'up' : 'down'
        hasChanges = true
      }
    }

    if (hasChanges) {
      setFlashState(prev => ({ ...prev, ...newFlashes }))
      // Clear flashes after duration
      setTimeout(() => {
        setFlashState(prev => {
          const next = { ...prev }
          Object.keys(newFlashes).forEach(sym => {
            delete next[sym]
          })
          return next
        })
      }, FLASH_DURATION)
    }

    prevPricesRef.current = { ...prices }
  }, [prices, displaySymbols])

  const priceData: PriceData[] = displaySymbols.map(sym => {
    const price = prices[sym] || 0
    const prevPrice = prevPricesRef.current[sym] || price
    const change = price - prevPrice
    const changePct = prevPrice > 0 ? (change / prevPrice) * 100 : 0

    return { symbol: sym, price, prevPrice, change, changePct }
  }).filter(d => d.price > 0)

  if (priceData.length === 0) {
    return (
      <div className="card py-3">
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <div className="w-2 h-2 rounded-full bg-gray-600 animate-pulse" />
          Waiting for market data... (configure Alpaca API keys to enable live prices)
        </div>
      </div>
    )
  }

  return (
    <div className="card overflow-hidden py-3">
      <div className="flex items-center gap-4">
        {/* Label */}
        <div className="flex-shrink-0 text-xs text-gray-400 font-semibold uppercase tracking-wider">
          Live Prices
        </div>

        {/* Scrolling ticker */}
        <div className="flex-1 overflow-x-auto">
          <div className="flex gap-4 min-w-max">
            {priceData.map(({ symbol, price, changePct }) => {
              const flash = flashState[symbol]
              const isPositive = changePct >= 0

              return (
                <div
                  key={symbol}
                  className={`flex items-center gap-2 px-3 py-1 rounded-lg border transition-all duration-300 ${
                    flash === 'up'
                      ? 'bg-green-900/40 border-green-600/60'
                      : flash === 'down'
                      ? 'bg-red-900/40 border-red-600/60'
                      : 'bg-gray-800/40 border-gray-700/30'
                  }`}
                >
                  {/* Symbol */}
                  <span className="font-bold text-sm text-white">{symbol}</span>

                  {/* Price */}
                  <span className={`text-sm font-medium ${
                    flash === 'up' ? 'text-green-300' :
                    flash === 'down' ? 'text-red-300' :
                    'text-gray-200'
                  }`}>
                    ${price.toFixed(2)}
                  </span>

                  {/* Change % */}
                  <span className={`text-xs ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
                    {isPositive ? '▲' : '▼'}
                    {Math.abs(changePct).toFixed(2)}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Timestamp */}
        <div className="flex-shrink-0 text-xs text-gray-600">
          {new Date().toLocaleTimeString()}
        </div>
      </div>
    </div>
  )
}
