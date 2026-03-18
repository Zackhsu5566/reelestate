import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";

const { fontFamily } = loadFont("normal", {
  weights: ["700"],
});

type Props = {
  src: string;
  label: string;
};

export const StagingScene: React.FC<Props> = ({ src, label }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const opacity = interpolate(frame, [0, Math.round(0.3 * fps)], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <AbsoluteFill style={{ opacity }}>
        <Img
          src={staticFile(src)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />

        {/* Bottom gradient overlay */}
        <AbsoluteFill
          style={{
            background:
              "linear-gradient(to top, rgba(0,0,0,0.65) 0%, transparent 45%)",
          }}
        />

        {/* Room label — top left */}
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

        {/* AI Staging — bottom right */}
        <AbsoluteFill
          style={{
            justifyContent: "flex-end",
            alignItems: "flex-end",
            padding: "0 48px 80px",
            fontFamily,
          }}
        >
          <div
            style={{
              color: "rgba(255,255,255,0.7)",
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: 2,
            }}
          >
            AI Staging
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
