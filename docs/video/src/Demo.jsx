import {AbsoluteFill, Sequence, random, useCurrentFrame} from 'remotion';
import scenes from './scenes.json';
import {Clipping, ease, HIGHLIGHT, INK, Mark, MONO, MUTED, Paper, RED, Scene, Stamp, Typed, useUnit} from './kit';

export const FPS = 30;
const PLAN = [
  ['pile', 180],
  ['ask', 240],
  ['how', 300],
  ['result', 360],
  ['safety', 150],
  ['end', 120],
];
export const DEMO_FRAMES = PLAN.reduce((n, [, d]) => n + d, 0);

const REPO = 'tjdwls101010/Agentic-SNS';
const PLATFORMS = ['X', 'Threads', 'Reddit', 'Facebook', 'Naver Blog'];

const Caption = ({children, size = 92, style}) => {
  const {u} = useUnit();
  return <div style={{fontSize: size * u, fontWeight: 900, lineHeight: 1.05, letterSpacing: '-0.02em', ...style}}>{children}</div>;
};

// Placeholder lines, not real comments: the pile shows volume, never anyone's words.
const Lines = ({n = 3, seed, color = '#d9d2c4'}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: '0.45em'}}>
    {Array.from({length: n}, (_, i) => (
      <div key={i} style={{height: '0.42em', width: `${55 + random(`${seed}-${i}`) * 45}%`, background: color, borderRadius: 4}} />
    ))}
  </div>
);

const Pile = () => {
  const frame = useCurrentFrame();
  const {u, width, height, wide} = useUnit();
  const total = scenes.commentsRead;
  const shown = Math.round(ease(frame, 8, 100, 0, total));
  return (
    <AbsoluteFill>
      {Array.from({length: total}, (_, i) => {
        const at = 8 + (i / total) * 92;
        const drop = ease(frame, at, at + 10, -0.25, 0);
        if (frame < at) return null;
        const x = random(`x${i}`) * (width - 300 * u);
        const y = random(`y${i}`) * (height - 140 * u);
        return (
          <div
            key={i}
            style={{
              position: 'absolute', left: x, top: y + drop * height, width: 280 * u, padding: 18 * u, fontSize: 22 * u,
              background: '#fffdf8', boxShadow: '0 4px 10px rgba(40,30,15,0.15)', transform: `rotate(${(random(`r${i}`) - 0.5) * 24}deg)`,
            }}
          >
            <Lines seed={`p${i}`} />
          </div>
        );
      })}
      <AbsoluteFill style={{justifyContent: 'center', alignItems: wide ? 'flex-start' : 'center', padding: 110 * u}}>
        <Clipping at={20} tilt={-2} seed="count" style={{padding: `${36 * u}px ${56 * u}px`}}>
          <div style={{fontSize: 30 * u, fontWeight: 600, color: MUTED}}>{scenes.subreddit} · “{scenes.title}”</div>
          <Caption size={150} style={{marginTop: 10 * u}}>
            {shown} comments.
          </Caption>
          <Caption size={96} style={{marginTop: 12 * u, opacity: ease(frame, 104, 116, 0, 1)}}>
            <Mark at={118}>Nobody</Mark> reads them all.
          </Caption>
        </Clipping>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Terminal = ({children, at = 0, style}) => {
  const {u} = useUnit();
  return (
    <Clipping at={at} tilt={-1} torn={false} seed="term" style={{background: '#1f1d1a', color: '#efe8da', borderRadius: 14 * u, overflow: 'hidden', ...style}}>
      <div style={{display: 'flex', gap: 10 * u, padding: `${16 * u}px ${20 * u}px`, background: '#2b2925'}}>
        {['#e0614f', '#e8b84a', '#78b35a'].map((c) => (
          <div key={c} style={{width: 16 * u, height: 16 * u, borderRadius: '50%', background: c}} />
        ))}
        <div style={{marginLeft: 16 * u, fontFamily: MONO, fontSize: 20 * u, color: '#a39a8c'}}>claude</div>
      </div>
      <div style={{padding: `${28 * u}px ${34 * u}px`, fontFamily: MONO, fontSize: 30 * u, lineHeight: 1.5}}>{children}</div>
    </Clipping>
  );
};

const Ask = () => {
  const frame = useCurrentFrame();
  const {u, wide} = useUnit();
  const ask = `What does ${scenes.subreddit} think of the new Walkman prices? Read the whole thread.`;
  const [head, tail] = scenes.summaryLine.split(' · limit')[0].split(' · stopped=');
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: 90 * u, gap: 50 * u, flexDirection: 'column'}}>
      <Caption size={84}>
        <Mark at={12}>One sentence</Mark> in Claude Code.
      </Caption>
      <Terminal at={6} style={{width: wide ? 1500 * u : '100%'}}>
        <div>
          <span style={{color: HIGHLIGHT}}>&gt; </span>
          <Typed text={ask} at={20} cps={42} />
        </div>
        <div style={{color: '#a39a8c', marginTop: 22 * u, opacity: ease(frame, 112, 120, 0, 1)}}>⏺ sns · reading through your Aside browser…</div>
        <div style={{marginTop: 18 * u, fontSize: 25 * u, color: '#cfc6b6', opacity: ease(frame, 150, 158, 0, 1)}}>
          {head} · <Mark at={168} color="rgba(255,216,74,0.35)">stopped={tail}</Mark>
        </div>
      </Terminal>
    </AbsoluteFill>
  );
};

const Browser = ({u, wide}) => {
  const frame = useCurrentFrame();
  const scroll = (frame * 3.2) % 600;
  return (
    <Clipping at={4} tilt={1.5} torn={false} seed="browser" style={{width: '100%', borderRadius: 14 * u, overflow: 'hidden'}}>
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 8 * u, padding: `${14 * u}px ${18 * u}px 0`, background: '#e2dbcc', fontSize: 22 * u}}>
        <div style={{padding: `${10 * u}px ${18 * u}px`, background: '#fffdf8', borderRadius: `${10 * u}px ${10 * u}px 0 0`, fontWeight: 800}}>reddit · sns tab</div>
        <div style={{padding: `${10 * u}px ${18 * u}px`, color: MUTED}}>your tabs — untouched</div>
      </div>
      <div style={{height: (wide ? 520 : 300) * u, overflow: 'hidden', padding: `0 ${30 * u}px`, fontSize: 24 * u}}>
        <div style={{transform: `translateY(${-scroll * u}px)`}}>
          {Array.from({length: 30}, (_, i) => (
            <div key={i} style={{display: 'flex', gap: 16 * u, padding: `${18 * u}px 0`, marginLeft: (i % 3) * 36 * u, borderBottom: '1px solid #eee6d6'}}>
              <div style={{width: 34 * u, height: 34 * u, borderRadius: '50%', background: '#d9d2c4', flex: 'none'}} />
              <div style={{flex: 1}}>
                <Lines n={2} seed={`b${i}`} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </Clipping>
  );
};

const How = () => {
  const {u, wide} = useUnit();
  const points = [
    ['Your own logged-in browser', 'Aside, in a tab of its own'],
    ['Read-only', 'never posts, likes or follows'],
    ['No API keys', 'it reads what you can see'],
  ];
  return (
    <AbsoluteFill style={{flexDirection: wide ? 'row' : 'column', alignItems: 'center', justifyContent: 'center', padding: 90 * u, gap: 70 * u}}>
      <div style={{width: wide ? 900 * u : '100%'}}>
        <Browser u={u} wide={wide} />
      </div>
      <div style={{display: 'flex', flexDirection: 'column', gap: (wide ? 44 : 26) * u}}>
        {points.map(([big, small], i) => (
          <Clipping key={big} at={40 + i * 55} tilt={i % 2 ? 1.5 : -1.5} seed={`pt${i}`} style={{padding: `${22 * u}px ${34 * u}px`}}>
            <Caption size={wide ? 58 : 48}>
              <Mark at={52 + i * 55}>{big}</Mark>
            </Caption>
            <div style={{fontSize: 28 * u, color: MUTED, marginTop: 6 * u}}>{small}</div>
          </Clipping>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// Shared with SocialCard; `settled` draws the final state without animation.
export const Chart = ({at = 0, settled = false, rows = scenes.categories, barWidth, compact = false}) => {
  const frame = useCurrentFrame();
  const {u} = useUnit();
  const max = Math.max(...rows.map((c) => c.count));
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: (compact ? 8 : 16) * u}}>
      {rows.map((c, i) => {
        const p = settled ? 1 : ease(frame, at + i * 9, at + i * 9 + 22, 0, 1);
        const joke = c.key === 'G';
        return (
          <div key={c.key} style={{opacity: settled ? 1 : ease(frame, at + i * 9, at + i * 9 + 6, 0, 1)}}>
            <div style={{fontSize: (compact ? 23 : 27) * u, fontWeight: 600, color: joke ? MUTED : INK, marginBottom: 4 * u}}>{c.label}</div>
            <div style={{display: 'flex', alignItems: 'center', gap: 14 * u}}>
              <div style={{height: (compact ? 24 : 34) * u, width: (barWidth ?? 640) * u * (c.count / max) * p, background: i === 0 ? RED : joke ? '#bdb4a5' : INK}} />
              <div style={{fontSize: 30 * u, fontWeight: 900, fontVariantNumeric: 'tabular-nums'}}>{Math.round(c.count * p)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Result = () => {
  const {u, wide} = useUnit();
  const quoted = scenes.categories.filter((c) => c.quote).slice(0, wide ? 3 : 1);
  return (
    <AbsoluteFill style={{padding: `${70 * u}px ${(wide ? 100 : 70) * u}px`, gap: (wide ? 34 : 24) * u}}>
      <Caption size={wide ? 84 : 66}>
        What {scenes.labeled} comments <Mark at={14}>actually</Mark> said
      </Caption>
      <div style={{display: 'flex', flexDirection: wide ? 'row' : 'column', gap: (wide ? 60 : 30) * u, flex: 1}}>
        <Chart at={30} barWidth={wide ? 640 : 600} compact={!wide} />
        <div style={{display: 'flex', flexDirection: 'column', gap: 30 * u, flex: 1, justifyContent: 'center'}}>
          {quoted.map((c, i) => (
            <Clipping key={c.key} at={150 + i * 40} tilt={[-2.5, 2, -1.2][i]} seed={`q${i}`} style={{padding: `${26 * u}px ${32 * u}px ${34 * u}px`}}>
              <div style={{fontSize: 21 * u, fontWeight: 800, color: i === 0 ? RED : MUTED, textTransform: 'uppercase', letterSpacing: '0.06em'}}>{c.label}</div>
              <div style={{fontSize: (wide ? 33 : 28) * u, fontWeight: 600, marginTop: 8 * u, lineHeight: 1.25}}>“{c.quote}”</div>
            </Clipping>
          ))}
        </div>
      </div>
      <div style={{fontSize: 22 * u, color: MUTED}}>
        {scenes.commentsRead} comments read · {scenes.deleted} deleted · {scenes.requests} requests · grouped by Claude · usernames left out
      </div>
    </AbsoluteFill>
  );
};

const Safety = () => {
  const {u} = useUnit();
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', flexDirection: 'column', gap: 46 * u, padding: 90 * u}}>
      <div style={{position: 'relative'}}>
        <Clipping at={0} tilt={-1.5} seed="cp" style={{padding: `${34 * u}px ${48 * u}px`, width: 760 * u}}>
          <div style={{fontSize: 24 * u, fontWeight: 800, color: RED, letterSpacing: '0.06em'}}>CHECKPOINT</div>
          <div style={{fontSize: 38 * u, fontWeight: 800, marginTop: 8 * u}}>Confirm it’s you to continue</div>
          <div style={{marginTop: 18 * u, fontSize: 26 * u}}>
            <Lines n={2} seed="cpl" />
          </div>
        </Clipping>
        <div style={{position: 'absolute', right: -70 * u, top: 10 * u, fontSize: 96 * u}}>
          <Stamp at={34}>STOPPED</Stamp>
        </div>
      </div>
      <Caption size={70} style={{textAlign: 'center'}}>
        It stops and <Mark at={56}>waits for you</Mark>.
      </Caption>
      <div style={{fontSize: 32 * u, color: MUTED, textAlign: 'center'}}>Rate limits respected · every request logged · nothing is written to your account</div>
    </AbsoluteFill>
  );
};

const End = () => {
  const {u} = useUnit();
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', flexDirection: 'column', gap: 34 * u, padding: 80 * u, textAlign: 'center'}}>
      <Caption size={130}>Agentic SNS</Caption>
      <div style={{fontSize: 40 * u, fontWeight: 600}}>Claude Code reads social media through your own browser.</div>
      <Clipping at={10} tilt={-1} torn={false} seed="npx" style={{background: '#1f1d1a', color: '#efe8da', padding: `${22 * u}px ${36 * u}px`, borderRadius: 12 * u}}>
        <div style={{fontFamily: MONO, fontSize: 36 * u}}>
          <span style={{color: HIGHLIGHT}}>$ </span>npx skills add {REPO}
        </div>
      </Clipping>
      <div style={{display: 'flex', gap: 14 * u, flexWrap: 'wrap', justifyContent: 'center'}}>
        {PLATFORMS.map((p, i) => (
          <Clipping key={p} at={24 + i * 5} tilt={(i % 2 ? 1 : -1) * 2} torn={false} seed={p} style={{padding: `${10 * u}px ${22 * u}px`, fontSize: 30 * u, fontWeight: 800}}>
            {p}
          </Clipping>
        ))}
      </div>
      <div style={{fontSize: 26 * u, color: MUTED}}>Requires the Aside browser · github.com/{REPO}</div>
    </AbsoluteFill>
  );
};

const SCENES = {pile: Pile, ask: Ask, how: How, result: Result, safety: Safety, end: End};

export const Demo = () => {
  let from = 0;
  return (
    <Paper>
      {PLAN.map(([name, duration]) => {
        const Body = SCENES[name];
        const start = from;
        from += duration;
        return (
          <Sequence key={name} name={name} from={start} durationInFrames={duration}>
            <Scene duration={duration}>
              <Body />
            </Scene>
          </Sequence>
        );
      })}
    </Paper>
  );
};
