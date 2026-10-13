import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

// Source de vérité : README.md du dépôt IAGuard. Aucun chiffre ni nom hors README.
const ACCENT = '#F5B544';
const BG = '#0A0C10';
const FG = '#E9ECF1';
const MUTED = '#7C8696';
const LINE = '#232832';
const FONT = '"Segoe UI", "Helvetica Neue", Arial, sans-serif';
const MONO = '"Cascadia Mono", Consolas, monospace';

const SCENES = [270, 330, 330, 270];
export const TOTAL = SCENES.reduce((a, b) => a + b, 0);

// ---------- helpers ----------
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

const useIn = (delay: number, damping = 18) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping, stiffness: 120}});
};

const Reveal: React.FC<{
  delay: number;
  y?: number;
  x?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({delay, y = 28, x = 0, style, children}) => {
  const p = useIn(delay);
  return (
    <div
      style={{
        opacity: interpolate(p, [0, 1], [0, 1], clamp),
        transform: `translate(${(1 - p) * x}px, ${(1 - p) * y}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

const Scene: React.FC<{children: React.ReactNode}> = ({children}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const opacity = interpolate(
    frame,
    [0, 12, durationInFrames - 14, durationInFrames],
    [0, 1, 1, 0],
    clamp,
  );
  return <AbsoluteFill style={{opacity}}>{children}</AbsoluteFill>;
};

const Backdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = (frame * 0.15) % 80;
  return (
    <AbsoluteFill style={{background: BG}}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${LINE} 1px, transparent 1px), linear-gradient(90deg, ${LINE} 1px, transparent 1px)`,
          backgroundSize: '80px 80px',
          backgroundPosition: `${drift}px ${drift}px`,
          opacity: 0.35,
          maskImage: 'radial-gradient(ellipse at center, #000 20%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, #000 20%, transparent 75%)',
        }}
      />
    </AbsoluteFill>
  );
};

const Eyebrow: React.FC<{children: string; delay?: number}> = ({children, delay = 0}) => (
  <Reveal delay={delay} y={12}>
    <div
      style={{
        fontFamily: MONO,
        fontSize: 24,
        letterSpacing: 6,
        textTransform: 'uppercase',
        color: ACCENT,
      }}
    >
      {children}
    </div>
  </Reveal>
);

const Title: React.FC<{children: React.ReactNode; delay?: number}> = ({children, delay = 6}) => (
  <Reveal delay={delay}>
    <div
      style={{
        fontFamily: FONT,
        fontSize: 76,
        fontWeight: 600,
        color: FG,
        letterSpacing: -1.5,
        marginTop: 18,
      }}
    >
      {children}
    </div>
  </Reveal>
);

const Chip: React.FC<{label: string; delay: number; accent?: boolean}> = ({label, delay, accent}) => (
  <Reveal delay={delay} y={16}>
    <div
      style={{
        fontFamily: MONO,
        fontSize: 26,
        padding: '10px 22px',
        borderRadius: 999,
        border: `1.5px solid ${accent ? ACCENT : LINE}`,
        color: accent ? ACCENT : MUTED,
        background: accent ? 'rgba(245,181,68,0.08)' : 'rgba(255,255,255,0.02)',
      }}
    >
      {label}
    </div>
  </Reveal>
);

// ---------- Scène 1 : présentation ----------
const Scene1: React.FC = () => {
  const frame = useCurrentFrame();
  const ring = interpolate(frame, [4, 70], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const C = 2 * Math.PI * 150;
  const letters = 'IAGuard'.split('');
  const scan = interpolate(frame % 120, [0, 120], [-78, 78]);
  return (
    <Scene>
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 120}}>
        <svg width={380} height={380} viewBox="-190 -190 380 380">
          <circle r={150} fill="none" stroke={LINE} strokeWidth={2} />
          <circle
            r={150}
            fill="none"
            stroke={ACCENT}
            strokeWidth={4}
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - ring)}
            transform="rotate(-90)"
          />
          <g opacity={interpolate(frame, [30, 60], [0, 1], clamp)}>
            <path
              d="M-52 -78 H30 L62 -46 V78 H-52 Z"
              fill="rgba(245,181,68,0.06)"
              stroke={FG}
              strokeWidth={4}
              strokeLinejoin="round"
            />
            <path d="M30 -78 V-46 H62" fill="none" stroke={FG} strokeWidth={4} strokeLinejoin="round" />
            {[-30, -6, 18, 42].map((y, i) => (
              <line key={y} x1={-30} x2={i === 3 ? 10 : 38} y1={y} y2={y} stroke={MUTED} strokeWidth={5} strokeLinecap="round" />
            ))}
            <line x1={-52} x2={62} y1={scan} y2={scan} stroke={ACCENT} strokeWidth={3} opacity={0.9} />
          </g>
        </svg>
        <div>
          <div style={{display: 'flex', fontFamily: FONT, fontSize: 168, fontWeight: 700, color: FG, letterSpacing: -4, lineHeight: 1}}>
            {letters.map((l, i) => (
              <Reveal key={i} delay={14 + i * 4} y={40}>
                <span style={{color: i < 2 ? ACCENT : FG}}>{l}</span>
              </Reveal>
            ))}
          </div>
          <Reveal delay={50} style={{marginTop: 22}}>
            <div style={{fontFamily: FONT, fontSize: 48, color: FG, fontWeight: 400}}>Agent documentaire souverain</div>
          </Reveal>
          <div style={{display: 'flex', gap: 16, marginTop: 44}}>
            <Chip label="Locale" delay={78} accent />
            <Chip label="Mono-utilisateur" delay={86} />
            <Chip label="Windows" delay={94} />
          </div>
        </div>
      </AbsoluteFill>
    </Scene>
  );
};

// ---------- Scène 2 : du corpus à l'action ----------
const NODES = [
  {t: 'Cartographier', s: 'crawl récursif · INDEX.md'},
  {t: 'Rechercher', s: 'des preuves'},
  {t: 'Répondre', s: 'avec citations'},
  {t: 'Classer', s: 'les nouveaux fichiers'},
  {t: 'Restructurer', s: 'réversible'},
];
const FORMATS = ['PDF', 'Word', 'Excel', 'PowerPoint', 'Images OCR', 'EML', 'MSG', 'ZIP sécurisé'];

const Scene2: React.FC = () => {
  const frame = useCurrentFrame();
  const W = 1600;
  const gap = W / (NODES.length - 1);
  const draw = interpolate(frame, [30, 150], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
  const pulse = interpolate(frame, [150, 270], [0, 1], clamp);
  const px = ((pulse * 1.6) % 1) * W;
  return (
    <Scene>
      <AbsoluteFill style={{padding: '110px 160px'}}>
        <Eyebrow>Ce que fait l'agent</Eyebrow>
        <Title>Du corpus à l'action</Title>
        <div style={{position: 'relative', marginTop: 150, width: W}}>
          <svg width={W} height={4} style={{position: 'absolute', top: 36, left: 0, overflow: 'visible'}}>
            <line x1={0} x2={W} y1={2} y2={2} stroke={LINE} strokeWidth={3} />
            <line x1={0} x2={W * draw} y1={2} y2={2} stroke={ACCENT} strokeWidth={3} />
            {pulse > 0 && pulse < 0.65 && <circle cx={px} cy={2} r={8} fill={ACCENT} />}
          </svg>
          {NODES.map((n, i) => {
            const lit = draw >= i / (NODES.length - 1) - 0.001;
            return (
              <div key={n.t} style={{position: 'absolute', left: i * gap - 130, width: 260, top: 0, textAlign: 'center'}}>
                <Reveal delay={24 + i * 22} y={20}>
                  <div
                    style={{
                      width: 76,
                      height: 76,
                      margin: '0 auto',
                      borderRadius: 22,
                      background: lit ? ACCENT : BG,
                      border: `2px solid ${lit ? ACCENT : LINE}`,
                      color: lit ? BG : MUTED,
                      fontFamily: MONO,
                      fontSize: 32,
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    {i + 1}
                  </div>
                  <div style={{fontFamily: FONT, fontSize: 36, fontWeight: 600, color: FG, marginTop: 28}}>{n.t}</div>
                  <div style={{fontFamily: FONT, fontSize: 24, color: MUTED, marginTop: 8}}>{n.s}</div>
                </Reveal>
              </div>
            );
          })}
        </div>
        <div style={{position: 'absolute', left: 160, right: 160, bottom: 120}}>
          <Reveal delay={170} y={10}>
            <div style={{fontFamily: MONO, fontSize: 22, letterSpacing: 4, color: MUTED, textTransform: 'uppercase', marginBottom: 22}}>
              Extraction de
            </div>
          </Reveal>
          <div style={{display: 'flex', flexWrap: 'wrap', gap: 14}}>
            {FORMATS.map((f, i) => (
              <Chip key={f} label={f} delay={180 + i * 6} />
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </Scene>
  );
};

// ---------- Scène 3 : la preuve ----------
const Box: React.FC<{x: number; y: number; w: number; h: number; label: string; sub?: string; delay: number; accent?: boolean}> = ({
  x, y, w, h, label, sub, delay, accent,
}) => (
  <div style={{position: 'absolute', left: x, top: y, width: w, height: h}}>
    <Reveal delay={delay} y={14} style={{height: '100%'}}>
      <div
        style={{
          height: '100%',
          boxSizing: 'border-box',
          borderRadius: 18,
          border: `2px solid ${accent ? ACCENT : LINE}`,
          background: accent ? 'rgba(245,181,68,0.08)' : 'rgba(255,255,255,0.03)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: FONT,
        }}
      >
        <div style={{fontSize: 30, fontWeight: 600, color: accent ? ACCENT : FG}}>{label}</div>
        {sub && <div style={{fontSize: 21, color: MUTED, marginTop: 6}}>{sub}</div>}
      </div>
    </Reveal>
  </div>
);

const Scene3: React.FC = () => {
  const frame = useCurrentFrame();
  // coordonnées dans un repère 1600 x 300
  const link = (d: string, start: number, len = 400) => {
    const p = interpolate(frame, [start, start + 28], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
    return <path d={d} fill="none" stroke={ACCENT} strokeWidth={3} strokeDasharray={len} strokeDashoffset={len * (1 - p)} />;
  };
  const bars = [0, 1, 2, 3, 4];
  const refuse = useIn(250);
  return (
    <Scene>
      <AbsoluteFill style={{padding: '110px 160px'}}>
        <Eyebrow>Recherche et justification</Eyebrow>
        <Title>Pas de preuve, pas de réponse</Title>

        <div style={{position: 'relative', marginTop: 70, width: 1600, height: 300}}>
          <svg width={1600} height={300} style={{position: 'absolute', inset: 0}}>
            {link('M270 150 C330 150 330 75 390 75', 40, 160)}
            {link('M270 150 C330 150 330 225 390 225', 40, 160)}
            {link('M740 75 C800 75 800 150 860 150', 70, 160)}
            {link('M740 225 C800 225 800 150 860 150', 70, 160)}
            {link('M1050 150 H1100', 100, 60)}
            {link('M1330 150 H1380', 125, 60)}
          </svg>
          <Box x={0} y={105} w={270} h={90} label="Question" sub="réécrite pour la recherche" delay={20} />
          <Box x={390} y={30} w={350} h={90} label="Plein texte" sub="PostgreSQL" delay={50} />
          <Box x={390} y={180} w={350} h={90} label="Vectoriel" sub="pgvector" delay={56} />
          <Box x={860} y={105} w={190} h={90} label="RRF" delay={80} />
          <Box x={1100} y={105} w={230} h={90} label="Reranking" sub="optionnel" delay={105} />
          <Box x={1380} y={105} w={220} h={90} label="Citations" sub="validées" delay={130} accent />
        </div>

        <div style={{display: 'flex', alignItems: 'flex-end', gap: 100, marginTop: 40}}>
          <div>
            <Reveal delay={170} y={10}>
              <div style={{fontFamily: FONT, fontSize: 32, color: FG, fontWeight: 600}}>5 niveaux de justification</div>
            </Reveal>
            <div style={{display: 'flex', alignItems: 'flex-end', gap: 14, marginTop: 22, height: 120}}>
              {bars.map((b) => {
                const p = spring({frame: frame - (185 + b * 8), fps: 30, config: {damping: 16}});
                return (
                  <div
                    key={b}
                    style={{
                      width: 56,
                      height: 30 + b * 22,
                      borderRadius: 10,
                      background: b === 4 ? ACCENT : 'rgba(245,181,68,0.35)',
                      transformOrigin: 'bottom',
                      transform: `scaleY(${p})`,
                    }}
                  />
                );
              })}
            </div>
          </div>
          <div
            style={{
              opacity: refuse,
              transform: `translateY(${(1 - refuse) * 20}px)`,
              border: `2px dashed ${ACCENT}`,
              borderRadius: 18,
              padding: '22px 34px',
              fontFamily: FONT,
              fontSize: 34,
              color: FG,
            }}
          >
            Preuve insuffisante : <span style={{color: ACCENT, fontWeight: 600}}>refus</span>
          </div>
        </div>
      </AbsoluteFill>
    </Scene>
  );
};

// ---------- Scène 4 : garde-fous + clôture ----------
const GUARDS = [
  'Indexation uniquement sur demande',
  'Liaison sur 127.0.0.1 par défaut',
  'Aucune suppression définitive automatique',
  'Aucune écriture hors de la racine autorisée',
  'Validation humaine avant restructuration',
  'Aucun écrasement silencieux',
];

const Scene4: React.FC = () => {
  const frame = useCurrentFrame();
  const cardsOut = interpolate(frame, [185, 210], [1, 0], clamp);
  const outro = useIn(205);
  return (
    <Scene>
      <AbsoluteFill style={{padding: '110px 160px', opacity: cardsOut}}>
        <Eyebrow>Sécurité et mutation</Eyebrow>
        <Title>Vous gardez la main</Title>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28, marginTop: 80}}>
          {GUARDS.map((g, i) => {
            const p = spring({frame: frame - (28 + i * 14), fps: 30, config: {damping: 18}});
            const tick = interpolate(frame, [40 + i * 14, 58 + i * 14], [0, 1], clamp);
            return (
              <div
                key={g}
                style={{
                  opacity: p,
                  transform: `translateY(${(1 - p) * 30}px)`,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 28,
                  padding: '30px 34px',
                  borderRadius: 20,
                  border: `2px solid ${LINE}`,
                  background: 'rgba(255,255,255,0.03)',
                }}
              >
                <svg width={52} height={52} viewBox="0 0 52 52" style={{flexShrink: 0}}>
                  <circle cx={26} cy={26} r={23} fill="none" stroke={ACCENT} strokeWidth={3} />
                  <path d="M15 27 L23 35 L38 18" fill="none" stroke={ACCENT} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={40} strokeDashoffset={40 * (1 - tick)} />
                </svg>
                <div style={{fontFamily: FONT, fontSize: 34, color: FG, lineHeight: 1.2}}>{g}</div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: outro, transform: `scale(${0.96 + 0.04 * outro})`}}>
        <div style={{fontFamily: FONT, fontSize: 150, fontWeight: 700, color: FG, letterSpacing: -4}}>
          <span style={{color: ACCENT}}>IA</span>Guard
        </div>
        <div style={{fontFamily: FONT, fontSize: 44, color: FG, marginTop: 14}}>Agent documentaire souverain</div>
        <div style={{width: 160 * outro, height: 3, background: ACCENT, margin: '36px 0 30px'}} />
        <div style={{fontFamily: MONO, fontSize: 26, color: MUTED}}>Infomaniak, seul fournisseur IA prévu</div>
      </AbsoluteFill>
    </Scene>
  );
};

export const IAGuard: React.FC = () => {
  let from = 0;
  const comps = [Scene1, Scene2, Scene3, Scene4];
  return (
    <AbsoluteFill>
      <Backdrop />
      {comps.map((C, i) => {
        const f = from;
        from += SCENES[i];
        return (
          <Sequence key={i} from={f} durationInFrames={SCENES[i]}>
            <C />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
