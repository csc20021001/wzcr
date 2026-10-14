'use client';

import { useEffect, useRef } from 'react';
import Script from 'next/script';
import { ADSENSE_CLIENT, ADSENSE_SLOT } from '@/app/adsense-config';

declare global {
  interface Window {
    adsbygoogle?: Record<string, never>[];
  }
}

const isConfigured = Boolean(ADSENSE_SLOT);

export function AdSenseSlot() {
  const initialized = useRef(false);

  useEffect(() => {
    if (!isConfigured || initialized.current) return;
    initialized.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle ?? []).push({});
    } catch {
      initialized.current = false;
    }
  }, []);

  if (!isConfigured) {
    return (
      <aside className="ad-slot ad-placeholder" aria-label="廣告版位">
        <span>廣告</span>
      </aside>
    );
  }

  return (
    <>
      <Script
        async
        src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`}
        strategy="afterInteractive"
        crossOrigin="anonymous"
      />
      <aside className="ad-slot" aria-label="廣告">
        <span>廣告</span>
        <ins
          className="adsbygoogle"
          style={{ display: 'block' }}
          data-ad-client={ADSENSE_CLIENT}
          data-ad-slot={ADSENSE_SLOT}
          data-ad-format="auto"
          data-full-width-responsive="true"
        />
      </aside>
    </>
  );
}
