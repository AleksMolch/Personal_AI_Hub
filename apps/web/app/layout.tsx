import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Personal AI Hub",
  description: "Локальная платформа для работы с LLM и документами",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        {/* Тема применяется до первой отрисовки: иначе при тёмном выборе
            страница успевает мигнуть светлым фоном. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('pah_theme');if(t==='dark'){document.documentElement.classList.add('dark');document.documentElement.style.colorScheme='dark';}}catch(e){}",
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
