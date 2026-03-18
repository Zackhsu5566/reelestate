import { AbsoluteFill, staticFile, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { wipe } from "@remotion/transitions/wipe";
import { OpeningScene } from "./compositions/OpeningScene";
import { ClipScene } from "./compositions/ClipScene";
import { StagingScene } from "./compositions/StagingScene";
import { StatsScene } from "./compositions/StatsScene";
import { CTAScene } from "./compositions/CTAScene";
import type { VideoInput, SceneInput, StatsSceneInput } from "./types";

export const TRANSITION_FRAMES = 15; // 0.5s fade/wipe
export const STAGING_FRAMES = 60;    // 2s

/** 計算兩個相鄰 scene 之間是否需要轉場（不含 stagingImage 的特殊轉場） */
function needsFadeBetween(curr: SceneInput, next: SceneInput): boolean {
  // 同空間 clip → 無轉場（直接接）
  if (
    curr.type === "clip" &&
    next.type === "clip" &&
    curr.label === next.label
  ) {
    return false;
  }
  // 其餘都 fade
  return true;
}

/** 根據 scenes 陣列計算總 frames（含轉場扣除） */
export function calcTotalFrames(scenes: SceneInput[]): number {
  let total = 0;
  let transitionCount = 0;

  for (let i = 0; i < scenes.length; i++) {
    const scene = scenes[i];
    const next = scenes[i + 1] ?? null;

    total += scene.durationInFrames;

    if (scene.type === "clip" && scene.stagingImage) {
      // clip → wipe → staging → fade → next
      total += STAGING_FRAMES;
      transitionCount += 1; // wipe
      if (next) transitionCount += 1; // fade after staging
    } else if (next) {
      if (needsFadeBetween(scene, next)) {
        transitionCount += 1;
      }
    }
  }

  return total - transitionCount * TRANSITION_FRAMES;
}

const fadePresentation = fade();
const wipePresentation = wipe({ direction: "from-left" });
const fadeTiming = linearTiming({ durationInFrames: TRANSITION_FRAMES });

export const ReelEstateVideo: React.FC<VideoInput> = (props) => {
  const {
    title, location, address, size, layout, floor,
    price, contact, line, agentName, scenes, bgm,
  } = props;

  const seriesItems: React.ReactNode[] = [];

  for (let i = 0; i < scenes.length; i++) {
    const scene = scenes[i];
    const next = scenes[i + 1] ?? null;

    // Render scene
    switch (scene.type) {
      case "opening":
        seriesItems.push(
          <TransitionSeries.Sequence key={`s-${i}`} durationInFrames={scene.durationInFrames}>
            <OpeningScene
              title={title}
              location={location}
              address={address}
              community={props.community}
              propertyType={props.propertyType}
              buildingAge={props.buildingAge}
              floor={props.floor}
              mapboxToken={props.mapboxToken}
              lat={props.lat}
              lng={props.lng}
              exteriorVideo={scene.exteriorVideo}
              pois={scene.pois}
            />
          </TransitionSeries.Sequence>
        );
        break;

      case "clip": {
        const prev = scenes[i - 1] ?? null;
        const isFirstInGroup = !(
          prev?.type === "clip" && prev.label === scene.label
        );
        seriesItems.push(
          <TransitionSeries.Sequence key={`s-${i}`} durationInFrames={scene.durationInFrames}>
            <ClipScene src={scene.src} label={scene.label} isFirstInGroup={isFirstInGroup} />
          </TransitionSeries.Sequence>
        );
        break;
      }

      case "stats": {
        // Background: use scene.backgroundSrc, or fallback to last clip's src
        let statsBg = scene.backgroundSrc;
        if (!statsBg) {
          for (let j = i - 1; j >= 0; j--) {
            const prev = props.scenes[j];
            if (prev.type === "clip") {
              statsBg = prev.src;
              break;
            }
          }
        }
        seriesItems.push(
          <TransitionSeries.Sequence key={`s-${i}`} durationInFrames={scene.durationInFrames}>
            <StatsScene price={price} size={size} layout={layout} floor={floor} backgroundSrc={statsBg} />
          </TransitionSeries.Sequence>
        );
        break;
      }

      case "cta": {
        // Reuse same background logic as stats
        const statsScene = props.scenes.find((s): s is StatsSceneInput => s.type === "stats");
        let ctaBg = statsScene?.backgroundSrc;
        if (!ctaBg) {
          for (let j = i - 1; j >= 0; j--) {
            const prev = props.scenes[j];
            if (prev.type === "clip") {
              ctaBg = prev.src;
              break;
            }
          }
        }
        seriesItems.push(
          <TransitionSeries.Sequence key={`s-${i}`} durationInFrames={scene.durationInFrames}>
            <CTAScene contact={contact} line={line} backgroundSrc={ctaBg} />
          </TransitionSeries.Sequence>
        );
        break;
      }
    }

    // Post-scene transitions
    if (scene.type === "clip" && scene.stagingImage) {
      // Wipe → Staging → Fade
      seriesItems.push(
        <TransitionSeries.Transition key={`t-wipe-${i}`} presentation={wipePresentation} timing={fadeTiming} />
      );
      seriesItems.push(
        <TransitionSeries.Sequence key={`z-${i}`} durationInFrames={STAGING_FRAMES}>
          <StagingScene src={scene.stagingImage} label={scene.label} />
        </TransitionSeries.Sequence>
      );
      if (next) {
        seriesItems.push(
          <TransitionSeries.Transition key={`t-zfade-${i}`} presentation={fadePresentation} timing={fadeTiming} />
        );
      }
    } else if (next) {
      if (needsFadeBetween(scene, next)) {
        seriesItems.push(
          <TransitionSeries.Transition key={`t-fade-${i}`} presentation={fadePresentation} timing={fadeTiming} />
        );
      }
    }
  }

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* Scenes */}
      <TransitionSeries>{seriesItems}</TransitionSeries>

      {/* Background music — low volume, loops */}
      {bgm && <Audio src={staticFile(bgm)} volume={0.15} loop />}
    </AbsoluteFill>
  );
};
