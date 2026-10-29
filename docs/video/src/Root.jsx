import {Composition} from 'remotion';
import {Demo, DEMO_FRAMES, FPS} from './Demo';
import {SocialCard} from './SocialCard';

export const Root = () => (
  <>
    <Composition id="Demo" component={Demo} durationInFrames={DEMO_FRAMES} fps={FPS} width={1920} height={1080} />
    <Composition id="DemoSquare" component={Demo} durationInFrames={DEMO_FRAMES} fps={FPS} width={1080} height={1080} />
    <Composition id="SocialCard" component={SocialCard} durationInFrames={1} fps={FPS} width={1280} height={640} />
  </>
);
