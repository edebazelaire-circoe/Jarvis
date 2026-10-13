import React from 'react';
import {AbsoluteFill, Easing, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const DURATION = 1200; // 40 s à 30 i/s
const SCENE = 300;
const FADE = 14;

const ACCENT = '#4fd1ff';
const BG = '#0b0e13';
const PANEL = '#131821';
const LINE = '#262e3b';
const TEXT = '#eef2f7';
const MUTED = '#8a94a6';
const SANS = '"Segoe UI", "Helvetica Neue", Arial, sans-serif';
const MONO = 'Consolas, "SF Mono", monospace';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.out(Easing.cubic);

/** Entrée : fondu + glissement, décalée de `delay` images. */
const useIn = (delay: number, dur = 22) => {
  const f = useCurrentFrame();
  const p = interpolate(f, [delay, delay + dur], [0, 1], {...clamp, easing: ease});
  return {opacity: p, transform: `translateY(${(1 - p) * 28}px)`};
};

const Pop: React.FC<{delay: number; style?: React.CSSProperties; children: React.ReactNode}> = ({delay, style, children}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f - delay, fps, config: {damping: 16, stiffness: 120}});
  return <div style={{opacity: Math.min(1, s * 1.5), transform: `scale(${0.88 + 0.12 * s})`, ...style}}>{children}</div>;
};

const Scene: React.FC<{children: React.ReactNode}> = ({children}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, FADE, SCENE - FADE, SCENE], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{opacity: o, fontFamily: SANS, color: TEXT, padding: '110px 140px'}}>{children}</AbsoluteFill>
  );
};

const Kicker: React.FC<{n: string; label: string}> = ({n, label}) => (
  <div style={{...useIn(0), fontFamily: MONO, fontSize: 26, letterSpacing: 4, color: ACCENT, textTransform: 'uppercase'}}>
    {n} — {label}
  </div>
);

const Title: React.FC<{children: React.ReactNode; delay?: number}> = ({children, delay = 6}) => (
  <h1 style={{...useIn(delay), fontSize: 84, fontWeight: 600, margin: '24px 0 0', letterSpacing: -2, lineHeight: 1.05}}>{children}</h1>
);

/* ───────── Scène 1 : présentation ───────── */
const Waveform: React.FC = () => {
  const f = useCurrentFrame();
  const bars = 41;
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 9, height: 200}}>
      {Array.from({length: bars}).map((_, i) => {
        const env = Math.exp(-Math.pow((i - 20) / 9, 2));
        const grow = interpolate(f, [30 + i * 0.8, 52 + i * 0.8], [0, 1], {...clamp, easing: ease});
        const wob = 0.55 + 0.45 * Math.sin(f / 5 + i * 0.7) * Math.sin(f / 11 + i * 0.3);
        const h = 10 + 180 * env * Math.abs(wob) * grow;
        return <div key={i} style={{width: 9, height: h, borderRadius: 5, background: ACCENT, opacity: 0.35 + 0.65 * env}} />;
      })}
    </div>
  );
};

const Scene1: React.FC = () => {
  const f = useCurrentFrame();
  const press = interpolate(f, [120, 130, 150, 160], [0, 1, 1, 0], clamp);
  return (
    <Scene>
      <Kicker n="01" label="Présentation" />
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 90}}>
        <div>
          <div style={{...useIn(8), fontSize: 190, fontWeight: 700, letterSpacing: -6, lineHeight: 1}}>
            JARVIS<span style={{color: ACCENT}}>.</span>
          </div>
          <div style={{...useIn(26), fontSize: 46, color: MUTED, marginTop: 28}}>L’assistant vocal local-first.</div>
          <div style={{...useIn(44), fontSize: 46, marginTop: 14}}>Vous parlez. Il écoute, répond, retient.</div>
        </div>
        <div style={{...useIn(70), display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 26}}>
          <div
            style={{
              width: 200, height: 200, borderRadius: 32, background: PANEL,
              border: `2px solid ${press > 0.5 ? ACCENT : LINE}`,
              boxShadow: press > 0.5 ? `0 0 70px ${ACCENT}55` : `0 10px 0 ${LINE}`,
              transform: `translateY(${press * 8}px)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: MONO, fontSize: 88, fontWeight: 700, color: press > 0.5 ? ACCENT : TEXT,
            }}
          >
            F9
          </div>
          <div style={{fontSize: 30, color: MUTED}}>Appuyer pour parler</div>
        </div>
      </div>
      <div style={{position: 'absolute', left: 140, right: 140, bottom: 110, ...useIn(60)}}>
        <Waveform />
      </div>
    </Scene>
  );
};

/* ───────── Scène 2 : pipeline ───────── */
const STEPS = [
  {k: 'PTT', t: 'Push-to-talk'},
  {k: 'AudioCapture', t: 'Capture audio'},
  {k: 'Transcription', t: 'Transcription'},
  {k: 'Agent', t: 'Agent'},
  {k: 'TTS', t: 'Voix'},
];

const Scene2: React.FC = () => {
  const f = useCurrentFrame();
  const W = 1640;
  const nodeW = 260;
  const gap = (W - nodeW * STEPS.length) / (STEPS.length - 1);
  const cx = (i: number) => i * (nodeW + gap) + nodeW / 2;
  const lineIn = interpolate(f, [30, 130], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
  const pulse = interpolate((f - 150) % 120, [0, 100], [0, 1], clamp);
  const pulseOn = f >= 150;
  return (
    <Scene>
      <Kicker n="02" label="Le parcours d’une phrase" />
      <Title>De la voix à la réponse.</Title>
      <div style={{position: 'relative', width: W, height: 260, marginTop: 100}}>
        <div style={{position: 'absolute', top: 130, left: cx(0), width: (cx(4) - cx(0)) * lineIn, height: 3, background: LINE}} />
        {pulseOn && (
          <div style={{position: 'absolute', top: 120, left: cx(0) + (cx(4) - cx(0)) * pulse - 11, width: 22, height: 22, borderRadius: 11, background: ACCENT, boxShadow: `0 0 36px ${ACCENT}`, opacity: interpolate(pulse, [0, 0.05, 0.95, 1], [0, 1, 1, 0])}} />
        )}
        {STEPS.map((s, i) => {
          const active = pulseOn && Math.abs(pulse * 4 - i) < 0.35;
          return (
            <Pop key={s.k} delay={14 + i * 16} style={{position: 'absolute', left: cx(i) - nodeW / 2, top: 50, width: nodeW}}>
              <div style={{background: PANEL, border: `2px solid ${active ? ACCENT : LINE}`, borderRadius: 22, padding: '34px 0', textAlign: 'center', boxShadow: active ? `0 0 40px ${ACCENT}33` : 'none'}}>
                <div style={{fontSize: 38, fontWeight: 600}}>{s.t}</div>
                <div style={{fontFamily: MONO, fontSize: 20, color: MUTED, marginTop: 10}}>{s.k}</div>
              </div>
            </Pop>
          );
        })}
      </div>
      <div style={{display: 'flex', gap: 24, marginTop: 70}}>
        {['Chaque service est remplaçable', 'Aucun fichier audio conservé', 'Le cœur ne dépend d’aucun fournisseur'].map((t, i) => (
          <Pop key={t} delay={150 + i * 14}>
            <div style={{fontSize: 30, padding: '16px 28px', border: `1px solid ${LINE}`, borderRadius: 40, color: TEXT}}>
              <span style={{color: ACCENT}}>● </span>{t}
            </div>
          </Pop>
        ))}
      </div>
    </Scene>
  );
};

/* ───────── Scène 3 : outils, confirmation, mémoire ───────── */
const TOOLS = ['memory_search', 'memory_append', 'board_present'];

const Scene3: React.FC = () => {
  const f = useCurrentFrame();
  const gate = interpolate(f, [150, 175], [0, 1], {...clamp, easing: ease});
  const yes = f > 215;
  return (
    <Scene>
      <Kicker n="03" label="Sobre et sûr" />
      <Title>Trois outils. Rien d’autre.</Title>
      <div style={{display: 'flex', alignItems: 'center', marginTop: 80, gap: 0}}>
        <div style={{display: 'flex', flexDirection: 'column', gap: 22}}>
          {TOOLS.map((t, i) => (
            <Pop key={t} delay={20 + i * 14}>
              <div style={{width: 470, background: PANEL, border: `2px solid ${t === 'memory_append' && gate > 0.5 ? ACCENT : LINE}`, borderRadius: 18, padding: '26px 34px', fontFamily: MONO, fontSize: 36}}>
                {t}
              </div>
            </Pop>
          ))}
        </div>
        <div style={{width: 120, height: 3, background: LINE, opacity: interpolate(f, [70, 90], [0, 1], clamp)}} />
        <Pop delay={76}>
          <div style={{width: 400, textAlign: 'center', background: PANEL, border: `2px solid ${ACCENT}`, borderRadius: 24, padding: '34px 20px', boxShadow: `0 0 50px ${ACCENT}22`}}>
            <div style={{fontFamily: MONO, fontSize: 34, color: ACCENT}}>ActionBroker</div>
            <div style={{fontSize: 30, color: MUTED, marginTop: 10}}>refus par défaut</div>
          </div>
        </Pop>
        <div style={{width: 120, height: 3, background: LINE, opacity: interpolate(f, [90, 110], [0, 1], clamp)}} />
        <Pop delay={96}>
          <div style={{width: 420, textAlign: 'center', background: PANEL, border: `2px solid ${LINE}`, borderRadius: 24, padding: '34px 20px'}}>
            <div style={{fontSize: 36, fontWeight: 600}}>Mémoire Markdown</div>
            <div style={{fontSize: 28, color: MUTED, marginTop: 10}}>index SQLite reconstructible</div>
          </div>
        </Pop>
      </div>
      <div style={{marginTop: 70, display: 'flex', alignItems: 'center', gap: 30, opacity: gate, transform: `translateY(${(1 - gate) * 20}px)`}}>
        <div style={{fontSize: 38}}>Écrire en mémoire demande une confirmation :</div>
        <div style={{fontFamily: MONO, fontSize: 38, padding: '8px 28px', borderRadius: 14, border: `2px solid ${yes ? ACCENT : LINE}`, color: yes ? ACCENT : TEXT, background: yes ? `${ACCENT}1a` : 'transparent'}}>oui</div>
        <div style={{fontSize: 30, color: MUTED}}>ou</div>
        <div style={{fontFamily: MONO, fontSize: 38, padding: '8px 28px', borderRadius: 14, border: `2px solid ${LINE}`, color: MUTED}}>non</div>
      </div>
    </Scene>
  );
};

/* ───────── Scène 4 : modes et démarrage ───────── */
const MODES = [
  {n: 'SIMPLE', d: 'Il répond quand on lui parle.', st: 'Par défaut'},
  {n: 'PRESENTATION', d: 'Il écoute la salle, reste discret, répond quand on l’interpelle.', st: 'Changement en direct'},
  {n: 'REUNION', d: 'Réservé.', st: 'Pas encore implémenté'},
];

const Scene4: React.FC = () => {
  const f = useCurrentFrame();
  const typed = (s: string, start: number) => s.slice(0, Math.max(0, Math.floor((f - start) * 1.6)));
  const cmd1 = 'python -m jarvis health';
  const cmd2 = 'python scripts/dev_start.py';
  return (
    <Scene>
      <Kicker n="04" label="Modes et démarrage" />
      <Title>Un assistant, plusieurs comportements.</Title>
      <div style={{display: 'flex', gap: 28, marginTop: 70}}>
        {MODES.map((m, i) => {
          const reserved = m.n === 'REUNION';
          return (
            <Pop key={m.n} delay={20 + i * 14} style={{flex: 1}}>
              <div style={{height: 250, background: PANEL, border: `2px solid ${i === 1 ? ACCENT : LINE}`, borderRadius: 22, padding: '32px 36px', opacity: reserved ? 0.55 : 1}}>
                <div style={{fontFamily: MONO, fontSize: 34, color: i === 1 ? ACCENT : TEXT, letterSpacing: 1}}>{m.n}</div>
                <div style={{fontSize: 30, marginTop: 18, lineHeight: 1.3}}>{m.d}</div>
                <div style={{fontSize: 22, color: MUTED, marginTop: 18, fontFamily: MONO}}>{m.st}</div>
              </div>
            </Pop>
          );
        })}
      </div>
      <div style={{marginTop: 50, background: '#080a0e', border: `1px solid ${LINE}`, borderRadius: 18, padding: '30px 40px', fontFamily: MONO, fontSize: 34, lineHeight: 1.7, opacity: interpolate(f, [110, 130], [0, 1], clamp)}}>
        <div><span style={{color: ACCENT}}>$ </span>{typed(cmd1, 120)}</div>
        <div><span style={{color: ACCENT}}>$ </span>{typed(cmd2, 150)}{f % 30 < 16 && f > 150 ? '▍' : ''}</div>
      </div>
      <div style={{...useIn(200), marginTop: 28, fontSize: 26, color: MUTED}}>
        Version candidate · la validation physique sur poste reste à faire.
      </div>
    </Scene>
  );
};

export const Jarvis: React.FC = () => {
  const f = useCurrentFrame();
  const drift = interpolate(f, [0, DURATION], [0, 1]);
  return (
    <AbsoluteFill style={{background: BG}}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(900px 600px at ${20 + drift * 60}% ${30 + drift * 30}%, ${ACCENT}14, transparent 70%)`,
        }}
      />
      {[Scene1, Scene2, Scene3, Scene4].map((S, i) => (
        <Sequence key={i} from={i * SCENE} durationInFrames={SCENE}>
          <S />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
