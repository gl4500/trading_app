import React from 'react'

const I = (d: string) => (props: React.SVGProps<SVGSVGElement>) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d={d} />
  </svg>
)

export const IconChart    = I('M3 3v18h18 M7 14l4-4 4 4 5-7')
export const IconAgent    = I('M12 12a4 4 0 100-8 4 4 0 000 8z M4 21a8 8 0 0116 0')
export const IconTrades   = I('M3 6h18 M3 12h12 M3 18h6')
export const IconRollup   = I('M5 4h14v6H5z M5 14h14v6H5z')
export const IconSignals  = I('M2 12h3l3-9 4 18 3-9h7')
export const IconScanner  = I('M11 4a7 7 0 105.6 11.2L21 19.6')
export const IconSentinel = I('M13 2L3 14h7l-1 8 10-12h-7l1-8z')
export const IconRegime   = I('M3 18l6-6 4 4 8-10')
export const IconCNN      = I('M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z M10 7h4 M7 10v4 M14 17h6 M17 10v4')
export const IconDrift    = I('M3 12h4l3-8 4 16 3-12 4 4')
export const IconTax      = I('M5 3h11l3 3v15H5z M9 8h6 M9 12h6 M9 16h4')
export const IconTokens   = I('M5 7l7-4 7 4v10l-7 4-7-4z M5 7l7 4 7-4 M12 11v10')
export const IconErrors   = I('M12 2L2 22h20L12 2z M12 9v6 M12 18h.01')
export const IconTelemetry= I('M3 3v18h18 M7 17l4-6 3 4 5-9')
