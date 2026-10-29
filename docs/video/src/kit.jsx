// The explainer look: paper, highlighter, cut-out clippings, rubber stamp. Scenes compose these; none of them knows about the story.
import {AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {loadFont as loadSans} from '@remotion/google-fonts/LibreFranklin';
import {loadFont as loadMono} from '@remotion/google-fonts/IBMPlexMono';

export const SANS = loadSans('normal', {weights: ['400', '600', '800', '900'], subsets: ['latin']}).fontFamily;
export const MONO = loadMono('normal', {weights: ['400', '600'], subsets: ['latin']}).fontFamily;

export const INK = '#1c1a17';
export const PAPER = '#efe8da';
export const HIGHLIGHT = '#ffd84a';
export const RED = '#d6402f';
export const MUTED = '#6f675c';

// One design unit: 1px on a 1080-high frame, scaled to whatever the composition is.
export const useUnit = () => {
  const {width, height} = useVideoConfig();
  return {u: Math.min(width, height) / 1080, wide: width / height > 1.3, width, height};
};

const NOISE = `url("data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0.35 0 0 0 0 0.3 0 0 0 0 0.22 0 0 0 0.55 0"/></filter><rect width="100%" height="100%" filter="url(#n)"/></svg>',
)}")`;

export const Paper = ({children}) => (
  <AbsoluteFill style={{background: PAPER, fontFamily: SANS, color: INK}}>
    <AbsoluteFill style={{backgroundImage: NOISE, opacity: 0.35, mixBlendMode: 'multiply'}} />
    <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, transparent 55%, rgba(60,45,20,0.18) 100%)'}} />
    {children}
  </AbsoluteFill>
);

// A highlighter stroke drawn left to right behind the text, starting at `at` (frames into the scene).
export const Mark = ({at, dur = 12, color = HIGHLIGHT, children}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [at, at + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.quad)});
  return (
    <span style={{position: 'relative', display: 'inline-block', zIndex: 0}}>
      <span
        style={{
          position: 'absolute', left: '-0.12em', right: '-0.12em', top: '0.18em', bottom: '0.02em',
          background: color, zIndex: -1, transform: `scaleX(${p}) rotate(-1deg)`, transformOrigin: 'left center',
          borderRadius: '0.12em 0.3em 0.18em 0.35em', opacity: 0.92,
        }}
      />
      {children}
    </span>
  );
};

// Pops in with a spring from `at`; `tilt` in degrees. Jagged bottom edge like paper torn from a page.
export const Clipping = ({at = 0, tilt = 0, seed = 'c', torn = true, style, children}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - at, fps, config: {damping: 14, stiffness: 160}});
  const teeth = 28;
  const edge = Array.from({length: teeth + 1}, (_, i) => `${(i / teeth) * 100}% ${100 - random(`${seed}${i}`) * 3.2}%`).join(', ');
  return (
    <div
      style={{
        background: '#fffdf8', boxShadow: '0 0.6em 1.4em rgba(40,30,15,0.22)',
        transform: `translateY(${(1 - s) * 40}px) scale(${0.85 + s * 0.15}) rotate(${tilt}deg)`, opacity: Math.min(1, s * 1.6),
        clipPath: torn ? `polygon(0 0, 100% 0, ${edge.split(', ').reverse().join(', ')})` : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Typed = ({text, at = 0, cps = 38}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = Math.max(0, Math.floor(((frame - at) / fps) * cps));
  const caret = n < text.length || Math.floor(frame / 15) % 2 === 0;
  return (
    <span>
      {text.slice(0, n)}
      <span style={{opacity: caret ? 1 : 0}}>▍</span>
    </span>
  );
};

export const Stamp = ({at, children}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [at, at + 7], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  return (
    <div
      style={{
        display: 'inline-block', border: `0.09em solid ${RED}`, color: RED, padding: '0.05em 0.35em', fontWeight: 900,
        letterSpacing: '0.04em', borderRadius: '0.08em', transform: `rotate(-9deg) scale(${2.4 - p * 1.4})`, opacity: p,
        mixBlendMode: 'multiply',
      }}
    >
      {children}
    </div>
  );
};

// Scene wrapper: slides in from the right like a whip pan, fades out at the end.
export const Scene = ({duration, children}) => {
  const frame = useCurrentFrame();
  const x = interpolate(frame, [0, 10], [100, 0], {extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const out = interpolate(frame, [duration - 8, duration], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <AbsoluteFill style={{transform: `translateX(${x}%)`, opacity: out}}>{children}</AbsoluteFill>;
};

export const ease = (frame, from, to, a, b) =>
  interpolate(frame, [from, to], [a, b], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
