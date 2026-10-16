// Slice 09 — parcours navigateur réel : Chat du Control Center isolé, vrai Brain (CLI claude).
// node journey.mjs '<info json>'   info = {cc, out, pdf, png}
// Trois étapes : question simple ; PDF + PNG joints par le bouton Joindre ; sous-agent lancé depuis le chat,
// résultat tardif attendu comme bulle. Lit le DOM, jamais la trace ; captures sous info.out.
import {launch, sleep} from './cdp.mjs';
import {writeFileSync} from 'node:fs';
import {join} from 'node:path';

const info = JSON.parse(process.argv[2]);
const R = {steps: {}};
const save = () => writeFileSync(join(info.out, 'journey.json'), JSON.stringify(R, null, 1));
const bubbles = `[...document.querySelectorAll('#chatLog .chat-msg')].map(li=>({brain:li.classList.contains('brain'),text:li.textContent.slice(0,400)}))`;
const brainCount = `document.querySelectorAll('#chatLog .chat-msg.brain').length`;
const writable = `JarvisChat.instance.snapshot().state?.chat_writable===true`;

async function send(p, text) {
  await p.eval(`document.querySelector('#chatInput').focus()`);
  await p.type(text);
  await p.press('Enter');
}

async function waitBrain(p, after, test, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const all = await p.eval(bubbles);
    const brain = all.filter(b => b.brain).slice(after);
    if (brain.some(b => test(b.text))) return {ok: true, brain, ms: ms - (end - Date.now())};
    await sleep(1000);
  }
  return {ok: false, brain: (await p.eval(bubbles)).filter(b => b.brain).slice(after)};
}

const B = await launch();
try {
  const p = await B.newPage(info.cc + '/', {width: 1440, height: 900});
  await p.eval(`JarvisChat.open()`);
  R.hydrated = await p.until(`JarvisChat.instance.snapshot().feed.hydrated`, 15000);
  R.writable = await p.until(writable, 30000);
  await p.shot(join(info.out, '2026-10-15-s09-real-01-chat-open-1440x900.png'));

  // 1. Une question simple, réponse du vrai Brain en bulle.
  let n = await p.eval(brainCount), t0 = Date.now();
  await send(p, 'Combien font 17 fois 23 ? Réponds seulement le nombre.');
  R.steps.question = await waitBrain(p, n, t => t.includes('391'), 240000);
  R.steps.question.wall_ms = Date.now() - t0;
  await p.shot(join(info.out, '2026-10-15-s09-real-02-answer-1440x900.png'));
  save();

  // 2. PDF + PNG par le bouton Joindre (sélecteur natif intercepté), puis la question.
  await p.click('#chatAttach');
  R.steps.chooser = await p.answerChooser([info.pdf, info.png]);
  R.steps.attachments_ready = await p.until(
    `JarvisChat.instance.snapshot().attachments.uploading===0&&document.querySelectorAll('#chatFiles .chat-file').length===2`, 20000);
  R.steps.rows = await p.eval(`[...document.querySelectorAll('#chatFiles .chat-file')].map(li=>li.dataset.status+' · '+li.querySelector('.chat-file-text').textContent)`);
  await p.shot(join(info.out, '2026-10-15-s09-real-03-attachments-ready-1440x900.png'));
  n = await p.eval(brainCount); t0 = Date.now();
  await send(p, 'Lis les deux pièces jointes. Donne la phrase secrète du PDF, puis le texte visible sur l\'image.');
  R.steps.attachments = await waitBrain(p, n, t => /licorne violette/i.test(t) && /47/.test(t), 300000);
  R.steps.attachments.wall_ms = Date.now() - t0;
  R.steps.attachment_line = await p.eval(`[...document.querySelectorAll('#chatLog .chat-att')].map(x=>x.textContent)`);
  await p.shot(join(info.out, '2026-10-15-s09-real-04-attachments-answer-1440x900.png'));
  save();

  // 3. Sous-agent lancé depuis le chat : réponse immédiate, puis son résultat en bulle, sans parole.
  n = await p.eval(brainCount); t0 = Date.now();
  await send(p, 'Lance un sous-agent en arrière-plan qui compte les fichiers .md placés directement dans le dossier docs '
    + 'du dépôt (pas les sous-dossiers). Réponds-moi tout de suite en une phrase que c\'est lancé ; '
    + 'quand il aura fini, donne-moi le nombre.');
  R.steps.subagent_ack = await waitBrain(p, n, () => true, 240000);
  R.steps.subagent_ack.wall_ms = Date.now() - t0;
  const acked = await p.eval(brainCount);
  R.steps.subagent_late = await waitBrain(p, acked, t => /\d/.test(t), 480000);  // une bulle de plus, après l'accusé
  R.steps.subagent_late.wall_ms = Date.now() - t0;
  await p.shot(join(info.out, '2026-10-15-s09-real-05-subagent-result-1440x900.png'));
  R.final = await p.eval(bubbles);
  R.console_errors = p.console.filter(c => c.type === 'error').map(c => c.text.slice(0, 200));
  R.page_errors = p.errors.slice(0, 10);
  R.forbidden_calls = p.requests.filter(r => /\/api\/agent\/(ask|send)/.test(r.url)).length;
  R.chat_log_lines = p.console.filter(c => c.text.startsWith('[chat]')).map(c => c.text.slice(0, 160)).slice(-40);
} catch (e) {
  R.error = String(e.stack || e).slice(0, 1500);
} finally {
  save();
  await B.close();
}
