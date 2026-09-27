"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "Home" },
  { href: "/mine/", label: "Mine" },
  { href: "/whitepaper/", label: "Whitepaper" },
];

export function MenuBar() {
  const pathname = usePathname();
  const path = pathname === "/" ? "/" : `${pathname.replace(/\/$/, "")}/`;
  return (
    <header className="hb-raised border-b">
      <div className="max-w-4xl mx-auto px-2 py-1 flex items-center gap-4">
        <span className="font-bold px-2">Hyburn</span>
        <nav aria-label="Main" className="hb-menu flex flex-wrap gap-1 text-sm">
          {items.map((it) => {
            const active = path === it.href || (it.href !== "/" && path.startsWith(it.href));
            return (
              <Link key={it.href} href={it.href} aria-current={active ? "page" : undefined}>
                {it.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
