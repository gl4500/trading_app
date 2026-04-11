import React, { useState, useMemo } from 'react'
import { Trade, Agent } from '../App'
import { useTimezone } from '../context/TimezoneContext'
import { formatTs } from '../utils/time'

interface TradeLogProps {
  trades: Trade[]
  agents: Agent[]
}

const AGENT_COLORS: Record<string, string> = {
  TechAgent: 'text-blue-400',
  MomentumAgent: 'text-purple-400',
  MeanReversionAgent: 'text-yellow-400',
  SentimentAgent: 'text-green-400',
  ClaudeAgent: 'text-red-400',
  EnsembleAgent: 'text-slate-400',
}

const PAGE_SIZE = 20

export default function TradeLog({ trades, agents }: TradeLogProps) {
  const { timeZone } = useTimezone()
  const [page, setPage] = useState(0)
  const [filterAgent, setFilterAgent] = useState<string>('all')
  const [filterAction, setFilterAction] = useState<string>('all')

  const agentNames = useMemo(() => {
    const names = new Set(trades.map(t => t.agent_name).filter(Boolean))
    return Array.from(names) as string[]
  }, [trades])

  const filtered = useMemo(() => {
    return trades.filter(t => {
      if (filterAgent !== 'all' && t.agent_name !== filterAgent) return false
      if (filterAction !== 'all' && t.action !== filterAction) return false
      return true
    })
  }, [trades, filterAgent, filterAction])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const pageData = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  function handleFilterChange(type: 'agent' | 'action', value: string) {
    setPage(0)
    if (type === 'agent') setFilterAgent(value)
    else setFilterAction(value)
  }

  const totalBuys = filtered.filter(t => t.action === 'BUY').length
  const totalSells = filtered.filter(t => t.action === 'SELL').length
  const winningTrades = filtered.filter(t => t.action === 'SELL' && t.pnl > 0).length
  const totalPnl = filtered.reduce((s, t) => s + (t.pnl || 0), 0)

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="card-header mb-0">
          📋 Trade Log
          <span className="ml-2 text-gray-500 font-normal text-xs">
            ({filtered.length} trades)
          </span>
        </div>

        {/* Filters */}
        <div className="flex gap-2">
          <select
            value={filterAgent}
            onChange={e => handleFilterChange('agent', e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Agents</option>
            {agentNames.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <select
            value={filterAction}
            onChange={e => handleFilterChange('action', e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Actions</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div className="bg-gray-900/50 rounded-lg p-2 border border-gray-700/30 text-center">
          <div className="text-green-400 font-bold text-lg">{totalBuys}</div>
          <div className="text-xs text-gray-500">Buys</div>
        </div>
        <div className="bg-gray-900/50 rounded-lg p-2 border border-gray-700/30 text-center">
          <div className="text-red-400 font-bold text-lg">{totalSells}</div>
          <div className="text-xs text-gray-500">Sells</div>
        </div>
        <div className="bg-gray-900/50 rounded-lg p-2 border border-gray-700/30 text-center">
          <div className="text-blue-400 font-bold text-lg">
            {totalSells > 0 ? `${((winningTrades / totalSells) * 100).toFixed(0)}%` : 'N/A'}
          </div>
          <div className="text-xs text-gray-500">Win Rate</div>
        </div>
        <div className="bg-gray-900/50 rounded-lg p-2 border border-gray-700/30 text-center">
          <div className={`font-bold text-lg ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totalPnl >= 0 ? '+' : ''}${Math.abs(totalPnl).toFixed(0)}
          </div>
          <div className="text-xs text-gray-500">Total P&L</div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        {pageData.length === 0 ? (
          <div className="text-center py-8 text-gray-500 text-sm">
            No trades yet. Start the competition to see activity!
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="table-header text-left">Time</th>
                <th className="table-header text-left">Agent</th>
                <th className="table-header text-center">Symbol</th>
                <th className="table-header text-center">Action</th>
                <th className="table-header text-right">Shares</th>
                <th className="table-header text-right">Price</th>
                <th className="table-header text-right">P&L</th>
                <th className="table-header text-left">Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {pageData.map((trade, idx) => (
                <tr key={idx} className="table-row group">
                  <td className="table-cell text-gray-500 whitespace-nowrap">
                    {formatTs(trade.timestamp, timeZone, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                  </td>
                  <td className={`table-cell font-medium ${AGENT_COLORS[trade.agent_name || ''] || 'text-gray-300'}`}>
                    {trade.agent_name || '—'}
                  </td>
                  <td className="table-cell text-center">
                    <span className="font-bold text-white">{trade.symbol}</span>
                  </td>
                  <td className="table-cell text-center">
                    <span className={`badge text-xs ${trade.action === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                      {trade.action}
                    </span>
                  </td>
                  <td className="table-cell text-right text-gray-300">{trade.shares.toFixed(2)}</td>
                  <td className="table-cell text-right text-gray-300">${trade.price.toFixed(2)}</td>
                  <td className={`table-cell text-right font-medium ${
                    trade.action === 'SELL'
                      ? (trade.pnl ?? 0) > 0 ? 'text-green-400' : (trade.pnl ?? 0) < 0 ? 'text-red-400' : 'text-gray-400'
                      : 'text-gray-500'
                  }`}>
                    {trade.action === 'SELL'
                      ? `${(trade.pnl ?? 0) >= 0 ? '+' : ''}$${(trade.pnl ?? 0).toFixed(2)}`
                      : '—'
                    }
                  </td>
                  <td className="table-cell text-gray-400 max-w-xs">
                    <span className="line-clamp-1 group-hover:line-clamp-none transition-all" title={trade.reasoning}>
                      {trade.reasoning || '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-700/50">
          <span className="text-xs text-gray-500">
            Page {page + 1} of {totalPages} ({filtered.length} total)
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1 text-xs bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ← Prev
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-3 py-1 text-xs bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
