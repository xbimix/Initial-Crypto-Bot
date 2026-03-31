import type { Metadata } from "next";
import "./globals.css";
import TableEnhancer from "./components/TableEnhancer";

export const metadata: Metadata = {
  title: "RevBot Portfolio Monitor",
  description: "A live paper-trading dashboard for the RevBot workspace.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <TableEnhancer />
        {children}
      </body>
    </html>
  );
}
