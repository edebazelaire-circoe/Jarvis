import React from 'react';
import {ACCENT, BG, LINE, MONO, MUTED, PANEL, Reveal, Scene, TEXT, useIn, useProgress} from '../ui';

const ALPHA = ['22', '3a', '55', '88', 'ff'];

const Bar: React.FC<{i: number}> = ({i}) => {
  const p = useProgress(30 + i * 12, 30);
  const h = 70 + i * 62;
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14}}>
      <div style={{width: 92, height: 400, display: 'flex', alignItems: 'flex-end'}}>
        <div
          style={{
            width: '100%',
            height: h * p,
            borderRadius: 14,
            background: `${ACCENT}${ALPHA[i]}`,
            border: `1.5px solid ${ACCENT}`,
          }}
        />
      </div>
      <div style={{fontFamily: MONO, fontSize: 26, color: i === 4 ? ACCENT : MUTED}}>{i + 1}</div>
    </div>
  );
};

export const Proof: React.FC<{dur: number}> = ({dur}) => {
  const check = useProgress(170, 20);
  const refuse = useIn(215);
  return (
    <Scene dur={dur} kicker="02 · Contrat de preuve" title="Pas de preuve, pas de réponse">
      <div style={{position: 'absolute', left: 120, top: 330}}>
        <Reveal delay={20} y={10}>
          <div style={{fontSize: 32, color: MUTED, marginBottom: 30}}>Cinq niveaux de justification</div>
        </Reveal>
        <div style={{display: 'flex', gap: 28}}>
          {[0, 1, 2, 3, 4].map((i) => <Bar key={i} i={i} />)}
        </div>
      </div>

      <Reveal delay={110} x={60} y={0} style={{position: 'absolute', left: 900, top: 330, width: 900}}>
        <div style={{background: PANEL, border: `2px solid ${ACCENT}`, borderRadius: 24, padding: '32px 38px'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 18}}>
            <svg width={44} height={44} viewBox="0 0 44 44">
              <circle cx={22} cy={22} r={20} fill="none" stroke={ACCENT} strokeWidth={3} />
              <path d="M12 23 l7 7 l13 -15" fill="none" stroke={ACCENT} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={40} strokeDashoffset={40 * (1 - check)} />
            </svg>
            <div style={{fontSize: 38, fontWeight: 600}}>Réponse avec citations</div>
          </div>
          <div style={{display: 'flex', flexDirection: 'column', gap: 14, marginTop: 28}}>
            {[0.95, 0.8, 0.6].map((w, i) => (
              <div key={i} style={{height: 14, width: `${w * 100}%`, borderRadius: 7, background: LINE}} />
            ))}
          </div>
          <div style={{marginTop: 26, fontSize: 26, color: ACCENT, fontFamily: MONO}}>Validation stricte des citations</div>
        </div>
      </Reveal>

      <div
        style={{
          position: 'absolute',
          left: 900,
          top: 690,
          width: 900,
          boxSizing: 'border-box',
          background: BG,
          border: `2px dashed ${MUTED}`,
          borderRadius: 24,
          padding: '28px 38px',
          opacity: refuse,
          transform: `translateY(${(1 - refuse) * 30}px)`,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
        }}
      >
        <svg width={44} height={44} viewBox="0 0 44 44">
          <circle cx={22} cy={22} r={20} fill="none" stroke={MUTED} strokeWidth={3} />
          <path d="M14 14 L30 30 M30 14 L14 30" stroke={MUTED} strokeWidth={4} strokeLinecap="round" />
        </svg>
        <div style={{fontSize: 34, color: TEXT}}>Preuve insuffisante : <span style={{color: ACCENT}}>refus</span></div>
      </div>
    </Scene>
  );
};
