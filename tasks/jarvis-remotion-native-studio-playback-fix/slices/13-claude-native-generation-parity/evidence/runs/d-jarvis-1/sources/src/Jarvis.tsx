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

export const SCENE = 300; // 10 s à 30 fps
export const TOTAL = SCENE * 4; // 40 s

const BG = '#0b0d12';
const FG = '#e8ecf3';
const DIM = '#7d8798';
const LINE = '#232a38';
const PANEL = '#10141c';
const ACCENT = '#4de1ff';
const SANS = '"Segoe UI", "Inter", system-ui, sans-serif';
const MONO = '"Cascadia Code", Consolas, "SFMono-Regular", monospace';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// Entrée échelonnée : progression 0..1 (spring) à partir d'un délai.
const useIn = (delay: number) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping: 200}});
};

const Reveal: React.FC<{
  delay: number;
  y?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({delay, y = 28, style, children}) => {
  const p = useIn(delay);
  return (
    <div style={{opacity: p, transform: `translateY(${(1 - p) * y}px)`, ...style}}>
      {children}
    </div>
  );
};

const Scene: React.FC<{children: React.ReactNode}> = ({children}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 14, SCENE - 14, SCENE], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{opacity, padding: '90px 100px', fontFamily: SANS, color: FG}}>
      {children}
    </AbsoluteFill>
  );
};

const Kicker: React.FC<{children: string}> = ({children}) => (
  <Reveal delay={0} y={14}>
    <div style={{fontFamily: MONO, fontSize: 26, letterSpacing: 6, color: ACCENT, textTransform: 'uppercase'}}>
      {children}
    </div>
  </Reveal>
);

const Title: React.FC<{children: React.ReactNode}> = ({children}) => (
  <Reveal delay={4}>
    <div style={{fontSize: 76, fontWeight: 700, letterSpacing: -2, marginTop: 18, lineHeight: 1.05}}>
      {children}
    </div>
  </Reveal>
);

const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = (frame / TOTAL) * 120;
  const mask = 'radial-gradient(ellipse at 50% 50%, black 20%, transparent 75%)';
  return (
    <AbsoluteFill style={{background: BG}}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${LINE}88 1px, transparent 1px), linear-gradient(90deg, ${LINE}88 1px, transparent 1px)`,
          backgroundSize: '80px 80px',
          backgroundPosition: `${-drift}px ${-drift / 2}px`,
          maskImage: mask,
          WebkitMaskImage: mask,
        }}
      />
    </AbsoluteFill>
  );
};

/* ---------------- Scène 1 : présentation ---------------- */

const Bar: React.FC<{i: number; bars: number}> = ({i, bars}) => {
  const frame = useCurrentFrame();
  const p = useIn(20 + i * 1.5);
  const center = 1 - Math.abs(i - (bars - 1) / 2) / ((bars - 1) / 2);
  const h = 14 + (0.25 + 0.75 * center) * 170 * (0.5 + 0.5 * Math.sin(frame / 5 + i * 0.7)) * p;
  return <div style={{width: 12, height: h, borderRadius: 6, background: ACCENT, opacity: 0.35 + 0.65 * center}} />;
};

const Scene1: React.FC = () => {
  const frame = useCurrentFrame();
  const underline = interpolate(frame, [30, 70], [0, 1], {easing: Easing.out(Easing.cubic), ...clamp});
  const bars = 33;
  return (
    <Scene>
      <div style={{display: 'flex', flexDirection: 'column', justifyContent: 'center', height: '100%'}}>
        <Kicker>Assistant vocal local</Kicker>
        <Reveal delay={6}>
          <div style={{fontSize: 230, fontWeight: 800, letterSpacing: -8, lineHeight: 1, marginTop: 10}}>JARVIS</div>
        </Reveal>
        <div style={{height: 6, width: 560 * underline, background: ACCENT, borderRadius: 3, margin: '14px 0 36px'}} />
        <Reveal delay={40}>
          <div style={{fontSize: 44, color: DIM, maxWidth: 1100, lineHeight: 1.3}}>
            Un assistant « push-to-talk » : vous parlez, il répond.
          </div>
        </Reveal>
        <div style={{marginTop: 70, display: 'flex', alignItems: 'center', gap: 12, height: 200}}>
          {Array.from({length: bars}).map((_, i) => (
            <Bar key={i} i={i} bars={bars} />
          ))}
        </div>
        <Reveal delay={90} style={{position: 'absolute', right: 100, bottom: 90}}>
          <div style={{fontFamily: MONO, fontSize: 28, color: DIM}}>
            Prototype · touche{' '}
            <span style={{color: ACCENT, border: `2px solid ${ACCENT}`, padding: '4px 14px', borderRadius: 8}}>F9</span>
          </div>
        </Reveal>
      </div>
    </Scene>
  );
};

/* ---------------- Scène 2 : le circuit d'une demande ---------------- */

const STEPS = ['Touche F9', 'Capture', 'Transcription', 'Orchestrateur', 'Agent', 'Voix'];
const NODE_W = 220;
const GAP = 80;
const TOOLS = ['memory_search', 'memory_append', 'board_present'];

const Node: React.FC<{label: string; i: number; dotX: number}> = ({label, i, dotX}) => {
  const p = useIn(18 + i * 8);
  const reached = dotX >= i * (NODE_W + GAP) + NODE_W / 2 - 1;
  return (
    <div
      style={{
        width: NODE_W,
        height: 120,
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: 18,
        fontSize: 30,
        fontWeight: 600,
        border: `2px solid ${reached ? ACCENT : LINE}`,
        background: reached ? '#0e2a33' : PANEL,
        color: reached ? FG : DIM,
        opacity: p,
        transform: `translateY(${(1 - p) * 30}px) scale(${0.92 + 0.08 * p})`,
        position: 'relative',
        zIndex: 1,
      }}
    >
      {label}
    </div>
  );
};

const Scene2: React.FC = () => {
  const frame = useCurrentFrame();
  const total = STEPS.length * NODE_W + (STEPS.length - 1) * GAP;
  const t = interpolate(frame, [40, 200], [0, 1], {easing: Easing.inOut(Easing.cubic), ...clamp});
  const dotX = t * (total - NODE_W) + NODE_W / 2;
  const conf = useIn(190);
  const yes = Math.sin(frame / 12) > 0;
  return (
    <Scene>
      <Kicker>Le circuit</Kicker>
      <Title>De votre voix à la réponse.</Title>
      <div style={{position: 'relative', marginTop: 90, width: total}}>
        <div style={{position: 'absolute', left: 0, top: 59, height: 2, width: total, background: LINE}} />
        <div style={{position: 'absolute', left: NODE_W / 2, top: 59, height: 2, width: (total - NODE_W) * t, background: ACCENT}} />
        <div
          style={{
            position: 'absolute',
            left: dotX - 11,
            top: 49,
            width: 22,
            height: 22,
            borderRadius: 11,
            background: ACCENT,
            boxShadow: `0 0 30px 6px ${ACCENT}99`,
            zIndex: 0,
            opacity: interpolate(frame, [40, 50], [0, 1], clamp),
          }}
        />
        <div style={{display: 'flex', gap: GAP}}>
          {STEPS.map((s, i) => (
            <Node key={s} label={s} i={i} dotX={dotX} />
          ))}
        </div>
      </div>

      <div style={{display: 'flex', gap: 60, marginTop: 100}}>
        <div style={{flex: 1}}>
          <Reveal delay={120} y={14}>
            <div style={{fontSize: 30, color: DIM, marginBottom: 22}}>Trois outils seulement</div>
          </Reveal>
          <div style={{display: 'flex', gap: 20}}>
            {TOOLS.map((n, i) => (
              <Reveal key={n} delay={130 + i * 10}>
                <div style={{fontFamily: MONO, fontSize: 30, padding: '16px 26px', borderRadius: 12, border: `2px solid ${LINE}`, background: PANEL}}>
                  {n}
                </div>
              </Reveal>
            ))}
          </div>
        </div>
        <div style={{width: 700, opacity: conf, transform: `translateY(${(1 - conf) * 24}px)`}}>
          <div style={{fontSize: 30, color: DIM, marginBottom: 22}}>Écrire en mémoire ? Il faut confirmer.</div>
          <div style={{display: 'flex', gap: 20, fontFamily: MONO, fontSize: 34}}>
            {['oui', 'non'].map((w, i) => {
              const on = (i === 0) === yes;
              return (
                <div
                  key={w}
                  style={{
                    padding: '14px 44px',
                    borderRadius: 12,
                    border: `2px solid ${on ? ACCENT : LINE}`,
                    color: on ? ACCENT : DIM,
                    background: on ? '#0e2a33' : 'transparent',
                  }}
                >
                  {w}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Scene>
  );
};

/* ---------------- Scène 3 : trois processus, des modes ---------------- */

const PROCS = [
  {cmd: 'jarvis core', desc: 'Le démon : conversations, outils, cerveau'},
  {cmd: 'jarvis voice', desc: 'Réveil et session vocale'},
  {cmd: 'jarvis control-center', desc: 'Panneau navigateur et agent local'},
];
const MODES = [
  {name: 'SIMPLE', note: 'par défaut'},
  {name: 'PRESENTATION', note: 'écoute la salle'},
  {name: 'REUNION', note: 'réservé'},
];

const Proc: React.FC<{p: (typeof PROCS)[number]; i: number}> = ({p, i}) => {
  const frame = useCurrentFrame();
  const a = useIn(20 + i * 14);
  const l = interpolate(frame, [50 + i * 14, 75 + i * 14], [0, 1], clamp);
  return (
    <>
      {i > 0 && (
        <div style={{width: 110, height: 2, background: LINE, position: 'relative'}}>
          <div style={{position: 'absolute', inset: 0, background: ACCENT, transformOrigin: 'left', transform: `scaleX(${l})`}} />
        </div>
      )}
      <div
        style={{
          flex: 1,
          padding: '34px 36px',
          borderRadius: 20,
          border: `2px solid ${i === 0 ? ACCENT : LINE}`,
          background: i === 0 ? '#0e2a33' : PANEL,
          opacity: a,
          transform: `translateY(${(1 - a) * 36}px)`,
        }}
      >
        <div style={{fontFamily: MONO, fontSize: 32, color: ACCENT}}>{p.cmd}</div>
        <div style={{fontSize: 30, color: DIM, marginTop: 14, lineHeight: 1.3}}>{p.desc}</div>
      </div>
    </>
  );
};

const Scene3: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sel = spring({frame: frame - 170, fps, config: {damping: 200}});
  const quote = useIn(235);
  return (
    <Scene>
      <Kicker>Sous le capot</Kicker>
      <Title>Trois processus, un cerveau.</Title>
      <div style={{display: 'flex', alignItems: 'center', marginTop: 80}}>
        {PROCS.map((p, i) => (
          <Proc key={p.cmd} p={p} i={i} />
        ))}
      </div>

      <Reveal delay={120} style={{marginTop: 80}} y={14}>
        <div style={{fontSize: 30, color: DIM, marginBottom: 22}}>Un comportement, modifiable en direct</div>
      </Reveal>
      <Reveal delay={128}>
        <div style={{position: 'relative', display: 'flex', width: 1300, border: `2px solid ${LINE}`, borderRadius: 18, background: PANEL}}>
          <div
            style={{
              position: 'absolute',
              top: 6,
              bottom: 6,
              left: 6,
              width: 'calc((100% - 12px) / 3)',
              borderRadius: 13,
              background: '#0e2a33',
              border: `2px solid ${ACCENT}`,
              boxSizing: 'border-box',
              transform: `translateX(${sel * 100}%)`,
            }}
          />
          {MODES.map((m, i) => {
            const active = i === 0 ? sel < 0.5 : i === 1 && sel >= 0.5;
            return (
              <div key={m.name} style={{flex: 1, textAlign: 'center', padding: '22px 0', position: 'relative', opacity: i === 2 ? 0.5 : 1}}>
                <div style={{fontFamily: MONO, fontSize: 32, color: active ? ACCENT : FG}}>{m.name}</div>
                <div style={{fontSize: 24, color: DIM, marginTop: 6}}>{m.note}</div>
              </div>
            );
          })}
        </div>
      </Reveal>
      <div style={{position: 'absolute', left: 100, right: 100, bottom: 80, opacity: quote, transform: `translateY(${(1 - quote) * 20}px)`}}>
        <div style={{fontSize: 40, color: FG, borderLeft: `6px solid ${ACCENT}`, paddingLeft: 28}}>
          La surface a les réflexes, le cerveau a la vérité.
        </div>
      </div>
    </Scene>
  );
};

/* ---------------- Scène 4 : confiance et démarrage ---------------- */

const FACTS = [
  {big: 'Refus par défaut', small: 'Aucune action sans autorisation'},
  {big: 'Mémoire Markdown', small: 'Index SQLite jetable, reconstructible'},
  {big: 'Pas de shell', small: 'Ni navigateur, envoi ou suppression'},
];
const CMDS = ['.\\setup.ps1', 'python -m jarvis health', 'python scripts\\dev_start.py'];

const Fact: React.FC<{f: (typeof FACTS)[number]; i: number}> = ({f, i}) => {
  const frame = useCurrentFrame();
  const p = useIn(20 + i * 16);
  const bar = interpolate(frame, [35 + i * 16, 65 + i * 16], [0, 1], {easing: Easing.out(Easing.cubic), ...clamp});
  return (
    <div
      style={{
        display: 'flex',
        gap: 28,
        padding: '26px 32px',
        borderRadius: 18,
        background: PANEL,
        border: `2px solid ${LINE}`,
        opacity: p,
        transform: `translateX(${(1 - p) * -50}px)`,
      }}
    >
      <div style={{width: 6, borderRadius: 3, background: ACCENT, transformOrigin: 'top', transform: `scaleY(${bar})`}} />
      <div>
        <div style={{fontSize: 40, fontWeight: 700}}>{f.big}</div>
        <div style={{fontSize: 27, color: DIM, marginTop: 8}}>{f.small}</div>
      </div>
    </div>
  );
};

const Scene4: React.FC = () => {
  const frame = useCurrentFrame();
  const note = useIn(215);
  return (
    <Scene>
      <Kicker>Prêt à essayer</Kicker>
      <Title>Sobre, vérifiable, local.</Title>
      <div style={{display: 'flex', gap: 70, marginTop: 70}}>
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 24}}>
          {FACTS.map((f, i) => (
            <Fact key={f.big} f={f} i={i} />
          ))}
        </div>
        <div style={{width: 800}}>
          <Reveal delay={60}>
            <div style={{borderRadius: 18, border: `2px solid ${LINE}`, background: '#07090d', padding: '28px 34px', fontFamily: MONO, fontSize: 30}}>
              <div style={{display: 'flex', gap: 10, marginBottom: 26}}>
                {[0, 1, 2].map((d) => (
                  <div key={d} style={{width: 14, height: 14, borderRadius: 7, background: LINE}} />
                ))}
              </div>
              {CMDS.map((c, i) => {
                const start = 80 + i * 40;
                const n = Math.max(0, Math.min(c.length, Math.floor((frame - start) * 1.2)));
                const typing = n > 0 && n < c.length;
                return (
                  <div key={c} style={{height: 56, color: FG, whiteSpace: 'pre'}}>
                    {frame >= start && <span style={{color: ACCENT}}>{'> '}</span>}
                    {c.slice(0, n)}
                    {typing && <span style={{background: ACCENT, color: ACCENT}}>_</span>}
                  </div>
                );
              })}
            </div>
          </Reveal>
          <Reveal delay={150} style={{marginTop: 24}} y={14}>
            <div style={{fontSize: 26, color: DIM}}>Python 3.11+, micro, clé OpenAI.</div>
          </Reveal>
        </div>
      </div>
      <div style={{position: 'absolute', left: 100, bottom: 80, opacity: note, transform: `translateY(${(1 - note) * 16}px)`, fontSize: 28, color: DIM}}>
        <span style={{color: ACCENT}}>●</span> Version candidate : la validation sur poste reste à faire.
      </div>
    </Scene>
  );
};

export const Jarvis: React.FC = () => (
  <AbsoluteFill>
    <Background />
    <Sequence from={0} durationInFrames={SCENE}><Scene1 /></Sequence>
    <Sequence from={SCENE} durationInFrames={SCENE}><Scene2 /></Sequence>
    <Sequence from={SCENE * 2} durationInFrames={SCENE}><Scene3 /></Sequence>
    <Sequence from={SCENE * 3} durationInFrames={SCENE}><Scene4 /></Sequence>
  </AbsoluteFill>
);
