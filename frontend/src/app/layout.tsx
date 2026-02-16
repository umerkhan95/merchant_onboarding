import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Nav } from "@/components/nav";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Merchant Onboarding - OneUp",
  description: "Onboard merchant stores and extract product data",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <ThemeProvider>
          <div className="flex min-h-screen">
            <Nav />
            <main className="flex-1 p-6">{children}</main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
