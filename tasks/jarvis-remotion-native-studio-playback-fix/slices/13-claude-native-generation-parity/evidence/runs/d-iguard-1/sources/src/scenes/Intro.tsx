import React from 'react';
import {useCurrentFrame} from 'remotion';
import {ACCENT, BG, FONT, LINE, MONO, MUTED, PANEL, Reveal, TEXT, useIn, useProgress, useSceneOpacity} from '../ui';

const FORMATS = ['PDF', 'DOCX', 'XLSX', 'PPTX', 'CSV', 'JSON', 'XML', 'EML', 'MSG', 'ZIP'];
const CX = 1340;
const CY = 540;
const R = 330;

const angle = (i: number) => (i / FORMATS.length) * Math.PI * 2 - Math.PI / 2;

const Spoke: React.FC<{i: number}> = ({i}) => {
  const frame = useCurrentFrame();
  const d = 30 + i * 6;
  const p = useProgress(d, 30);
  const x = CX + Math.cos(angle(i)) * R;
  const y = CY + Math.sin(angle(i)) * R;
  const t = ((frame - d - 40 + i * 9) % 70 + 70) % 70 / 70;
  const on = frame > d + 40;
  return (
    <g>
      <line x1={CX} y1={CY} x2={CX + (x - CX) * p} y2={CY + (y - CY) * p} stroke={LINE} strokeWidth={2} />
      {on && <circle cx={x + (CX - x) * t} cy={y + (CY - y) * t} r={5} fill={ACCENT} opacity={1 - Math.abs(t - 0.5) * 1.2} />}
    </g>
  );
};

const FileChip: React.FC<{i: number; f: string}> = ({i, f}) => {
  const p = useIn(34 + i * 6);
  return (
    <div
      style={{
        position: 'absolute',
        left: CX + Math.cos(angle(i)) * R - 56,
        top: CY + Math.sin(angle(i)) * R - 26,
        width: 112,
        height: 52,
        borderRadius: 12,
        background: PANEL,
        border: `1.5px solid ${LINE}`,
        color: TEXT,
        fontFamily: MONO,
        fontSize: 22,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: p,
        transform: `scale(${0.7 + 0.3 * p})`,
      }}
    >
      {f}
    </div>
  );
};

export const Intro: React.FC<{dur: number}> = ({dur}) => {
  const frame = useCurrentFrame();
  const o = useSceneOpacity(dur);
  const core = useIn(14);
  const pulse = 1 + 0.04 * Math.sin(frame / 8);

  return (
    <div style={{position: 'absolute', inset: 0, background: BG, fontFamily: FONT, color: TEXT, opacity: o, overflow: 'hidden'}}>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <circle cx={CX} cy={CY} r={R} fill="none" stroke={LINE} strokeWidth={1.5} strokeDasharray="4 12" opacity={core} />
        {FORMATS.map((f, i) => <Spoke key={f} i={i} />)}
        <circle cx={CX} cy={CY} r={110 * core * pulse} fill={`${ACCENT}10`} stroke={ACCENT} strokeWidth={2} />
        <circle cx={CX} cy={CY} r={70 * core} fill={ACCENT} opacity={0.9} />
        <path
          d={`M ${CX} ${CY - 30} l 26 10 v 20 q 0 20 -26 32 q -26 -12 -26 -32 v -20 z`}
          fill="none"
          stroke={BG}
          strokeWidth={6}
          strokeLinejoin="round"
          opacity={core}
        />
      </svg>
      {FORMATS.map((f, i) => <FileChip key={f} i={i} f={f} />)}
      <div style={{position: 'absolute', left: 120, top: 330}}>
        <Reveal delay={6} y={12}>
          <div style={{fontFamily: MONO, fontSize: 24, letterSpacing: 4, color: ACCENT}}>AGENT DOCUMENTAIRE SOUVERAIN</div>
        </Reveal>
        <Reveal delay={12}>
          <div style={{fontSize: 190, fontWeight: 700, letterSpacing: -6, lineHeight: 1.05, marginTop: 10}}>
            IA<span style={{color: ACCENT}}>Guard</span>
          </div>
        </Reveal>
        <Reveal delay={24}>
          <div style={{fontSize: 40, color: MUTED, marginTop: 20, maxWidth: 760, lineHeight: 1.3}}>
            Cartographier, rechercher, répondre avec citations.
          </div>
        </Reveal>
        <Reveal delay={40}>
          <div style={{display: 'flex', gap: 14, marginTop: 40}}>
            {['Locale', 'Mono-utilisateur', 'Windows'].map((t) => (
              <div key={t} style={{padding: '10px 22px', borderRadius: 999, border: `1.5px solid ${LINE}`, fontSize: 26, background: PANEL}}>{t}</div>
            ))}
          </div>
        </Reveal>
      </div>
    </div>
  );
};
