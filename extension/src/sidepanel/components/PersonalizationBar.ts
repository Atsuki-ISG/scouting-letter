import type { PersonalizationStats } from '../../shared/types';

/** Render a compact personalization-ratio bar as HTML string.
 *
 * Used both by the developer-mode 新パーソナライズ results card and
 * (optionally) the candidate list rows in the send tab. The bar
 * shows the overall ratio plus a per-block breakdown on hover.
 */
export function renderPersonalizationBar(
  stats: PersonalizationStats,
  options: { compact?: boolean } = {},
): string {
  const ratio = Math.max(0, Math.min(1, stats.ratio || 0));
  const pct = Math.round(ratio * 100);

  // Stack the per-block percentages into colored segments so the bar
  // shows not just "how much" but "which block contributed".
  const totalChars = stats.total_chars || 1;
  const blockOrder = [
    'opening',
    'bridge',
    'facility_intro',
    'job_framing',
    'closing_cta',
  ];
  const colors: Record<string, string> = {
    opening: '#22c55e',
    bridge: '#3b82f6',
    facility_intro: '#8b5cf6',
    job_framing: '#ec4899',
    closing_cta: '#f59e0b',
  };
  const blockLabels: Record<string, string> = {
    opening: '冒頭',
    bridge: '橋渡し',
    facility_intro: '施設紹介',
    job_framing: 'フレーミング',
    closing_cta: 'CTA',
  };

  const segments: string[] = [];
  for (const name of blockOrder) {
    const chars = stats.per_block_chars?.[name] || 0;
    if (chars <= 0) continue;
    const segPct = (chars / totalChars) * 100;
    segments.push(
      `<div style="width:${segPct.toFixed(2)}%;background:${colors[name]};" title="${blockLabels[name]}: ${chars}字"></div>`,
    );
  }
  // The fixed portion fills the rest
  const fixedPct = Math.max(0, 100 - pct);
  if (fixedPct > 0) {
    segments.push(
      `<div style="width:${fixedPct.toFixed(2)}%;background:#e5e7eb;" title="固定: ${stats.fixed_chars}字"></div>`,
    );
  }

  const breakdown = options.compact
    ? ''
    : `<div style="display:flex;gap:8px;font-size:10px;color:#6b7280;margin-top:2px;flex-wrap:wrap;">
         ${blockOrder
           .filter((n) => (stats.per_block_chars?.[n] || 0) > 0)
           .map(
             (n) =>
               `<span><span style="display:inline-block;width:8px;height:8px;background:${colors[n]};border-radius:2px;vertical-align:middle;"></span> ${blockLabels[n]} ${stats.per_block_chars[n]}字</span>`,
           )
           .join('')}
       </div>`;

  return `
    <div class="personalization-bar" style="margin:4px 0;">
      <div style="display:flex;align-items:center;gap:8px;">
        <div style="display:flex;height:8px;flex:1;border-radius:4px;overflow:hidden;background:#e5e7eb;">
          ${segments.join('')}
        </div>
        <span style="font-size:11px;font-weight:600;color:#374151;min-width:36px;text-align:right;">${pct}%</span>
      </div>
      ${breakdown}
    </div>
  `;
}
