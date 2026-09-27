import type { ReactNode } from "react";

export function Panel({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`mb-4 ${className}`} aria-label={title}>
      {title && <h2 className="text-sm font-bold mb-1">{title}</h2>}
      <div className="hb-sunken p-3">{children}</div>
    </section>
  );
}
