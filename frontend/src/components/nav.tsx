"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

const links = [
  { href: "/", label: "Onboard", icon: "+" },
  { href: "/jobs", label: "Jobs", icon: "#" },
  { href: "/products", label: "Products", icon: "=" },
  { href: "/analytics", label: "Analytics", icon: "~" },
];

export function Nav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();

  return (
    <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
      <div className="mb-8">
        <h1 className="text-lg font-bold text-[hsl(var(--foreground))]">
          Merchant Onboarding
        </h1>
        <p className="text-xs text-[hsl(var(--muted-foreground))]">OneUp.com</p>
      </div>

      <nav className="flex flex-1 flex-col gap-1">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              pathname === link.href
                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
            )}
          >
            <span className="font-mono text-base">{link.icon}</span>
            {link.label}
          </Link>
        ))}
      </nav>

      <button
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        className="mt-auto rounded-md border border-[hsl(var(--border))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
      >
        Toggle {theme === "dark" ? "Light" : "Dark"}
      </button>
    </aside>
  );
}
