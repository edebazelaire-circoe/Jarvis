import React from 'react';
import {useCurrentFrame} from 'remotion';
import {ACCENT, Chip, LINE, MONO, MUTED, PANEL, Reveal, Scene, TEXT, useProgress} from '../ui';

const NODES = [
  {t: 'Corpus Windows', s: 'Crawl récursif + INDEX.md', chips: ['PDF', 'Word', 'Excel', 'OCR']},
  {t: 'Indexation', s: 'Exclusivement manuelle', chips: ['Indexer', 'Reprendre']},
  {t: 'Recherche hybride', s: 'Full-text + pgvector', chips: ['RRF', 'Reranking optionnel']},
  {t: 'Réponse', s: 'Citations validées', chips: ['Preuve']},
];

const W = 360;
const GAP = 90;
const X0 = 120;
const Y = 400;

const Link: React.FC<{i: number}> = ({i}) => {
  const frame = useCurrentFrame();
  const x1 = X0 + i * (W + GAP) + W;
  const x2 = x1 + GAP;
  const p = useProgress(40 + i * 30, 24);
  const t = ((frame - 100 - i * 20) % 60 + 60) % 60 / 60;
  return (
    <g>
      <line x1={x1} y1={Y + 110} x2={x1 + GAP * p} y2={Y + 110} stroke={i === 0 ? ACCENT : LINE} strokeWidth={3} />
      {frame > 100 && <circle cx={x1 + GAP * t} cy={Y + 110} r={6} fill={ACCENT} />}
    </g>
  );
};

export const Pipeline: React.FC<{dur: number}> = ({dur}) => (
  <Scene dur={dur} kicker="01 · Du corpus à la preuve" title="Un pipeline, une décision humaine">
    <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
      {[0, 1, 2].map((i) => <Link key={i} i={i} />)}
    </svg>
    {NODES.map((n, i) => {
      const manual = i === 1;
      return (
        <Reveal key={n.t} delay={24 + i * 22} y={40} style={{position: 'absolute', left: X0 + i * (W + GAP), top: Y, width: W}}>
          <div
            style={{
              height: 220,
              borderRadius: 24,
              background: PANEL,
              border: `2px solid ${manual ? ACCENT : LINE}`,
              padding: '30px 28px',
              boxSizing: 'border-box',
            }}
          >
            <div style={{fontFamily: MONO, fontSize: 22, color: manual ? ACCENT : MUTED}}>0{i + 1}</div>
            <div style={{fontSize: 32, fontWeight: 600, marginTop: 10, color: TEXT}}>{n.t}</div>
            <div style={{fontSize: 24, color: MUTED, marginTop: 10}}>{n.s}</div>
          </div>
          <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 24}}>
            {n.chips.map((c, j) => (
              <Reveal key={c} delay={70 + i * 22 + j * 8} y={14}>
                <Chip label={c} accent={manual} size={22} />
              </Reveal>
            ))}
          </div>
        </Reveal>
      );
    })}
    <Reveal delay={190} style={{position: 'absolute', left: 120, bottom: 110}}>
      <div style={{fontSize: 34, color: MUTED}}>
        L’indexation ne démarre que par <span style={{color: ACCENT, fontWeight: 600}}>Indexer</span> ou{' '}
        <span style={{color: ACCENT, fontWeight: 600}}>Reprendre</span>.
      </div>
    </Reveal>
  </Scene>
);
