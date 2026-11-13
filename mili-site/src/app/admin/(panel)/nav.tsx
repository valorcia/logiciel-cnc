"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Nav({ groups }: { groups: { title: string; items: { href: string; label: string; badge?: number }[] }[] }) {
  const pathname = usePathname();
  return (
    <nav className="adm-nav space-y-6" aria-label="Administration">
      {groups.map((group) => (
        <div key={group.title}>
          <p className="mb-1.5 px-3 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-smoke">{group.title}</p>
          <ul>
            {group.items.map((item) => {
              const current = item.href === "/admin" ? pathname === "/admin" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link href={item.href} aria-current={current ? "page" : undefined} className="!flex items-center justify-between">
                    {item.label}
                    {item.badge ? <span className="adm-badge adm-badge-warn">{item.badge}</span> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
