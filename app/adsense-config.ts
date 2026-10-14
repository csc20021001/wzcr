const configuredClient = process.env.NEXT_PUBLIC_ADSENSE_CLIENT?.trim() ?? '';
const configuredSlot = process.env.NEXT_PUBLIC_ADSENSE_SLOT?.trim() ?? '';

// AdSense publisher IDs are intentionally public and appear in page source and ads.txt.
export const ADSENSE_CLIENT = /^ca-pub-\d+$/.test(configuredClient)
  ? configuredClient
  : 'ca-pub-7452457835531443';
export const ADSENSE_PUBLISHER_ID = ADSENSE_CLIENT.replace(/^ca-/, '');
export const ADSENSE_SLOT = /^\d+$/.test(configuredSlot) ? configuredSlot : '1381740675';
