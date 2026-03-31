import { AbsoluteFill, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Video } from "@remotion/media";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";

const { fontFamily } = loadFont("normal", {
  weights: ["700"],
});

// Speed ramp: 前段快、後段慢，總消耗 source 時長 = 原本 2x 等速
const FAST_RATE = 2.5;
const SLOW_RATE = 1.4;
const ORIGINAL_RATE = 2;
// 前段佔比：由 FAST_RATE * r + SLOW_RATE * (1-r) = ORIGINAL_RATE 解出
const FAST_RATIO = (ORIGINAL_RATE - SLOW_RATE) / (FAST_RATE - SLOW_RATE);

type Props = {
  src: string;
  label: string;
  isFirstInGroup?: boolean;
};

export const ClipScene: React.FC<Props> = ({ src, label, isFirstInGroup = true }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const fastFrames = Math.round(durationInFrames * FAST_RATIO);
  const slowFrames = durationInFrames - fastFrames;
  // 後段影片起點 = 前段消耗的 source frames
  const slowStartFrom = Math.round(fastFrames * FAST_RATE);

  const labelOpacity = isFirstInGroup
    ? interpolate(frame, [0.5 * fps, 1 * fps], [0, 1], { extrapolateRight: "clamp" })
    : 1;
  const labelY = isFirstInGroup
    ? interpolate(frame, [0.5 * fps, 1 * fps], [16, 0], { extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* 前段快速 */}
      <Sequence from={0} durationInFrames={fastFrames} layout="none">
        <Video
          src={staticFile(src)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          playbackRate={FAST_RATE}
          muted
        />
      </Sequence>
      {/* 後段減速 */}
      <Sequence from={fastFrames} durationInFrames={slowFrames} layout="none">
        <Video
          src={staticFile(src)}
          startFrom={slowStartFrom}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          playbackRate={SLOW_RATE}
          muted
        />
      </Sequence>

      {/* Bottom gradient overlay */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to top, rgba(0,0,0,0.65) 0%, transparent 45%)",
        }}
      />

      {/* Room label — bottom left (hidden if label is empty) */}
      {label && (
        <AbsoluteFill
          style={{
            justifyContent: "flex-start",
            alignItems: "flex-start",
            padding: "80px 48px 0",
            fontFamily,
          }}
        >
          <div
            style={{
              opacity: labelOpacity,
              transform: `translateY(${labelY}px)`,
              background: "rgba(0,0,0,0.45)",
              backdropFilter: "blur(10px)",
              border: "1px solid rgba(255,255,255,0.18)",
              borderRadius: 14,
              padding: "12px 32px",
              color: "white",
              fontSize: 44,
              fontWeight: 700,
            }}
          >
            {label}
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
