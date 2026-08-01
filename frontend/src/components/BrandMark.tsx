/** EMIOS brand glyph - an abstract three-node graph, echoing the digital
 * twin visualization that is the product's core artifact. Reused by the
 * sidebar, login page and marketing homepage so the mark stays consistent. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <circle cx="5" cy="6" r="2.1" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="19" cy="6" r="2.1" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="18" r="2.1" stroke="currentColor" strokeWidth="1.8" />
      <path d="M6.7 7.3 11 16M17.3 7.3 13 16M7 6h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
