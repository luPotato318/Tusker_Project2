import { injectSpeedInsights } from './vendor/vercel-speed-insights.mjs';

// Public pages only. Query strings can contain search terms or personal data.
export function sanitizeMetric(event) {
  try {
    const url = new URL(event.url);
    if (!['/', '/cursos/', '/vitrine/'].includes(url.pathname)) return null;
    url.search = '';
    url.hash = '';
    url.username = '';
    url.password = '';
    return { ...event, url: url.toString() };
  } catch {
    return null;
  }
}

if (typeof document !== 'undefined') {
  const config = document.getElementById('piem-speed-insights-config');
  if (config) {
    injectSpeedInsights({ ...JSON.parse(config.textContent), beforeSend: sanitizeMetric });
  }
}
