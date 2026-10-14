import type { Metadata } from 'next';
import { Noto_Sans_TC, Noto_Serif_TC } from 'next/font/google';
import { ADSENSE_CLIENT } from '@/app/adsense-config';
import './globals.css';

const notoSans = Noto_Sans_TC({ variable: '--font-noto-sans-tc', subsets: ['latin'], display: 'swap' });
const notoSerif = Noto_Serif_TC({ variable: '--font-noto-serif-tc', subsets: ['latin'], display: 'swap' });
export const metadata: Metadata = {
  metadataBase: new URL('https://map.scmwcscr.com'),
  title: 'WZUNAA｜大學課程評分',
  description: '查詢臺灣各大學公開課程資訊，以及五項 0–100 課程評分。',
  openGraph: {
    type: 'website',
    locale: 'zh_TW',
    url: 'https://map.scmwcscr.com',
    siteName: 'WZUNAA',
    title: 'WZUNAA｜大學課程評分',
    description: '查詢臺灣各大學公開課程資訊，以及五項 0–100 課程評分。',
  },
  twitter: {
    card: 'summary',
    title: 'WZUNAA｜大學課程評分',
    description: '查詢臺灣各大學公開課程資訊，以及五項 0–100 課程評分。',
  },
  other: { 'google-adsense-account': ADSENSE_CLIENT },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-Hant-TW">
      <body className={`${notoSans.variable} ${notoSerif.variable}`}>
        {children}
      </body>
    </html>
  );
}
