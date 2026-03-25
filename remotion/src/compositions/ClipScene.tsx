import { AbsoluteFill, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Video } from "@remotion/media";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";

const { fontFamily } = loadFont("normal", {
  weights: ["700"],
});

type Props = {
  src: string;
  label: string;
  isFirstInGroup?: boolean;
};

export const ClipScene: React.FC<Props> = ({ src, label, isFirstInGroup = true }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const labelOpacity = isFirstInGroup
    ? interpolate(frame, [0.5 * fps, 1 * fps], [0, 1], { extrapolateRight: "clamp" })
    : 1;
  const labelY = isFirstInGroup
    ? interpolate(frame, [0.5 * fps, 1 * fps], [16, 0], { extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* Full-screen video, muted (BGM only) */}
      <Video
        src={staticFile(src)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        playbackRate={1.43}
        muted
      />

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
