// The link card GitHub shows on X, Discord and HN (Settings → Social preview, 1280×640).
import {AbsoluteFill} from 'remotion';
import scenes from './scenes.json';
import {Chart} from './Demo';
import {HIGHLIGHT, MONO, MUTED, Paper, useUnit} from './kit';

export const SocialCard = () => {
  const {u} = useUnit();
  const top = scenes.categories.filter((c) => c.key !== 'G').slice(0, 4);
  return (
    <Paper>
      <AbsoluteFill style={{flexDirection: 'row', alignItems: 'center', padding: `${60 * u}px ${80 * u}px`, gap: 70 * u}}>
        <div style={{flex: 1.1}}>
          <div style={{fontSize: 104 * u, fontWeight: 900, letterSpacing: '-0.02em', lineHeight: 1}}>Agentic SNS</div>
          <div style={{fontSize: 44 * u, fontWeight: 600, marginTop: 26 * u, lineHeight: 1.2}}>
            Claude Code reads X, Threads, Reddit, Facebook &amp; Naver Blog through <span style={{background: HIGHLIGHT, padding: '0 0.1em'}}>your own browser</span>.
          </div>
          <div style={{fontFamily: MONO, fontSize: 28 * u, marginTop: 34 * u, color: MUTED}}>npx skills add tjdwls101010/Agentic-SNS</div>
        </div>
        <div style={{flex: 1, background: '#fffdf8', padding: `${34 * u}px ${38 * u}px`, boxShadow: '0 10px 24px rgba(40,30,15,0.2)', transform: 'rotate(1.5deg)'}}>
          <div style={{fontSize: 24 * u, fontWeight: 800, color: MUTED, marginBottom: 18 * u}}>
            {scenes.subreddit} · {scenes.labeled} comments · {scenes.requests} requests
          </div>
          <Chart settled rows={top} barWidth={420} />
        </div>
      </AbsoluteFill>
    </Paper>
  );
};
