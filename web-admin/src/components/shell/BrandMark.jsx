// The product mark: the NGY initial drawn as two solid uprights plus a
// diagonal that fades out, so the letter also reads as work flowing out of the
// agent. The glyph is currentColor - the tile behind it owns the gradient.

import { useId } from "react"

const LEFT_UPRIGHT = "M5.2 18.8V5.2"
const DIAGONAL = "M5.2 5.2L18.8 18.8"
const RIGHT_UPRIGHT = "M18.8 18.8V5.2"

export default function BrandMark({ className }) {
  // Colons are legal in an id but awkward inside url(#...), and the mark can be
  // rendered more than once per page, so every instance needs its own gradient.
  const gradientId = `brand-fade-${useId().replace(/:/g, "")}`

  return (
    <span className={`brand-mark ${className || ""}`.trim()} aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="currentColor" stopOpacity="1" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0.3" />
          </linearGradient>
        </defs>
        <path d={LEFT_UPRIGHT} stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
        <path d={DIAGONAL} stroke={`url(#${gradientId})`} strokeWidth="2.6" strokeLinecap="round" />
        <path d={RIGHT_UPRIGHT} stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      </svg>
    </span>
  )
}
