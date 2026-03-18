import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
});

type Props = {
  contact: string;
  line?: string;
  backgroundSrc?: string;
};

export const CTAScene: React.FC<Props> = ({ contact, line, backgroundSrc }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo: scale up from 0 with elastic bounce
  const logoProgress = interpolate(frame, [0, 0.6 * fps], [0, 1], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(1.4)),
  });
  const logoOpacity = interpolate(frame, [0, 0.3 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });
  const logoScale = interpolate(logoProgress, [0, 1], [0.3, 1]);

  // Logo glow pulse (after entrance)
  const glowPulse = interpolate(frame, [0.8 * fps, 3 * fps], [0, Math.PI * 4], {
    extrapolateRight: "clamp",
  });
  const glowIntensity = 1.3 + 0.15 * Math.sin(glowPulse);

  // Shine sweep across logo
  const shineX = interpolate(frame, [0.5 * fps, 1.2 * fps], [-100, 200], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  // Contact: slide up from bottom with stagger
  const phoneOpacity = interpolate(frame, [0.5 * fps, 0.9 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });
  const phoneY = interpolate(frame, [0.5 * fps, 0.9 * fps], [60, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const lineOpacity = interpolate(frame, [0.7 * fps, 1.1 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });
  const lineY = interpolate(frame, [0.7 * fps, 1.1 * fps], [60, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // Divider line expands from center
  const dividerWidth = interpolate(frame, [0.9 * fps, 1.3 * fps], [0, 300], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const dividerOpacity = interpolate(frame, [0.9 * fps, 1.1 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Background slow zoom
  const bgScale = interpolate(frame, [0, 4 * fps], [1.1, 1.2], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      {/* Background: blurred image or dark gradient fallback */}
      {backgroundSrc ? (
        <>
          <Img
            src={backgroundSrc.startsWith("http") ? backgroundSrc : staticFile(backgroundSrc)}
            style={{
              position: "absolute",
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "blur(20px)",
              transform: `scale(${bgScale})`,
            }}
          />
          <AbsoluteFill style={{ background: "rgba(0,0,0,0.55)" }} />
        </>
      ) : (
        <AbsoluteFill
          style={{ background: "linear-gradient(180deg, #1a1a2e 0%, #0a0a0a 100%)" }}
        />
      )}

      {/* Logo with shine effect */}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          paddingBottom: 800,
        }}
      >
        <div style={{ position: "relative", overflow: "hidden" }}>
          <Img
            src={staticFile("branding/logo.png")}
            style={{
              opacity: logoOpacity,
              transform: `scale(${logoScale})`,
              filter: `brightness(${glowIntensity})`,
              width: 800,
            }}
          />
          {/* Shine sweep overlay */}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: "100%",
              background: `linear-gradient(105deg, transparent 30%, rgba(255,255,255,0.25) 48%, rgba(255,255,255,0.4) 50%, rgba(255,255,255,0.25) 52%, transparent 70%)`,
              transform: `translateX(${shineX}%)`,
              pointerEvents: "none",
              opacity: logoOpacity,
            }}
          />
        </div>
      </AbsoluteFill>

      {/* Contact info */}
      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          alignItems: "center",
          paddingBottom: 200,
          fontFamily,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 24,
          }}
        >
          {/* Phone */}
          <div
            style={{
              opacity: phoneOpacity,
              transform: `translateY(${phoneY}px)`,
              color: "white",
              fontSize: 56,
              fontWeight: 700,
              letterSpacing: 2,
              textShadow: "0 2px 20px rgba(0,0,0,0.5)",
            }}
          >
            電話 {contact}
          </div>

          {/* Divider */}
          <div
            style={{
              opacity: dividerOpacity,
              width: dividerWidth,
              height: 2,
              background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)",
            }}
          />

          {/* LINE */}
          {line && (
            <div
              style={{
                opacity: lineOpacity,
                transform: `translateY(${lineY}px)`,
                color: "rgba(255,255,255,0.8)",
                fontSize: 48,
                fontWeight: 400,
                textShadow: "0 2px 20px rgba(0,0,0,0.5)",
              }}
            >
              LINE：{line}
            </div>
          )}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
