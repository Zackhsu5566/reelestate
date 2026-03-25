import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";
import type { NarrationSubtitle } from "../types";

const { fontFamily } = loadFont("normal", { weights: ["700"] });

const FADE_FRAMES = 5;

type Props = {
  subtitles: NarrationSubtitle[];
};

export const SubtitleOverlay: React.FC<Props> = ({ subtitles }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeMs = (frame / fps) * 1000;

  const active = subtitles.find(
    (s) => timeMs >= s.time_begin && timeMs <= s.time_end,
  );

  if (!active) return null;

  const startFrame = (active.time_begin / 1000) * fps;
  const endFrame = (active.time_end / 1000) * fps;

  const fadeIn = interpolate(frame, [startFrame, startFrame + FADE_FRAMES], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [endFrame - FADE_FRAMES, endFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        bottom: 120,
        left: 40,
        right: 40,
        display: "flex",
        justifyContent: "center",
        opacity: Math.min(fadeIn, fadeOut),
      }}
    >
      <div
        style={{
          background: "rgba(0, 0, 0, 0.7)",
          backdropFilter: "blur(8px)",
          borderRadius: 12,
          padding: "16px 28px",
          maxWidth: 900,
        }}
      >
        <div
          style={{
            color: "#fff",
            fontSize: 36,
            fontWeight: 700,
            fontFamily,
            textAlign: "center",
            lineHeight: 1.4,
          }}
        >
          {active.text}
        </div>
      </div>
    </div>
  );
};
