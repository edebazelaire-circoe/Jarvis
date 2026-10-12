import React from 'react';
import {useCurrentFrame} from 'remotion';
import {ACCENT, BG, Chip, LINE, MONO, MUTED, PANEL, Reveal, Scene, TEXT, useIn, useProgress} from '../ui';

const STEPS = ['Proposition', 'Validation humaine', 'Application', 'Rollback'];
const FILES = [[60, 110], [140, 190], [90, 270], [230, 130]];

export const Guardrails: React.FC<{dur: number}> = ({dur}) => {
  const frame = useCurrentFrame();
  const box = useIn(20);
  // un fichier tente de sortir de la racine : il est bloqué au bord
  const t = Math.min(1, Math.max(0, (frame - 90) / 40));
  const px = 330 + t * 230;
  const blocked = frame > 130;
  const active = Math.min(3, Math.max(0, Math.floor((frame - 120) / 40)));
  const lineP = useProgress(60, 90);
  return (
    <Scene dur={dur} kicker="03 · Garde-fous" title="Rien ne bouge sans vous">
      <div style={{position: 'absolute', left: 120, top: 340, width: 620, height: 400, opacity: box}}>
        <div style={{position: 'absolute', inset: 0, border: `2.5px dashed ${ACCENT}`, borderRadius: 28, background: `${ACCENT}08`}} />
        <div style={{position: 'absolute', left: 28, top: 22, fontFamily: MONO, fontSize: 22, color: ACCENT}}>Racine autorisée</div>
        {FILES.map(([x, y], i) => (
          <Reveal key={i} delay={40 + i * 8} y={0} style={{position: 'absolute', left: x, top: y}}>
            <div style={{width: 56, height: 70, borderRadius: 10, background: PANEL, border: `1.5px solid ${LINE}`}} />
          </Reveal>
        ))}
        <div style={{position: 'absolute', left: px - 56, top: 250, width: 56, height: 70, borderRadius: 10, background: PANEL, border: `2px solid ${blocked ? MUTED : ACCENT}`}} />
        {blocked && (
          <svg width={60} height={60} style={{position: 'absolute', left: 620 - 30, top: 285 - 30}}>
            <circle cx={30} cy={30} r={28} fill={BG} stroke={ACCENT} strokeWidth={3} />
            <path d="M19 19 L41 41 M41 19 L19 41" stroke={ACCENT} strokeWidth={5} strokeLinecap="round" />
          </svg>
        )}
      </div>
      <Reveal delay={150} style={{position: 'absolute', left: 120, top: 770, width: 620}}>
        <div style={{fontSize: 30, color: MUTED}}>Aucune écriture hors de la racine</div>
      </Reveal>

      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <line x1={990} y1={470} x2={990 + 720 * lineP} y2={470} stroke={LINE} strokeWidth={3} />
      </svg>
      {STEPS.map((s, i) => {
        const on = frame > 120 && i <= active;
        return (
          <Reveal key={s} delay={50 + i * 20} y={30} style={{position: 'absolute', left: 900 + i * 240, top: 380}}>
            <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', width: 180}}>
              <div
                style={{
                  width: 180, height: 180, borderRadius: '50%', background: on ? ACCENT : PANEL,
                  border: `2px solid ${on ? ACCENT : LINE}`, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: MONO, fontSize: 44, color: on ? BG : MUTED,
                }}
              >
                {i + 1}
              </div>
              <div style={{fontSize: 28, marginTop: 20, textAlign: 'center', color: on ? TEXT : MUTED}}>{s}</div>
            </div>
          </Reveal>
        );
      })}

      <div style={{position: 'absolute', left: 900, top: 700, display: 'flex', flexWrap: 'wrap', gap: 14, width: 900}}>
        {['Aucune suppression définitive automatique', 'Aucun écrasement silencieux', 'Liaison 127.0.0.1 par défaut'].map((c, i) => (
          <Reveal key={c} delay={170 + i * 14} y={16}><Chip label={c} accent={i === 0} size={24} /></Reveal>
        ))}
      </div>

      <Reveal delay={230} style={{position: 'absolute', left: 120, bottom: 70}}>
        <div style={{fontSize: 44, fontWeight: 700, letterSpacing: -1}}>
          IA<span style={{color: ACCENT}}>Guard</span>
          <span style={{fontWeight: 400, color: MUTED, fontSize: 30, marginLeft: 16}}>Agent documentaire souverain</span>
        </div>
      </Reveal>
    </Scene>
  );
};
