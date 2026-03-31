import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
});

type StatItem = { label: string; value: string };

type Props = {
  price: string;
  size: string;
  layout: string;
  floor: string;
  address?: string;
  backgroundSrc?: string;
};

const ANIM_DURATION = 20; // ~0.67s
const STAGGER_DELAY = 0;  // all items appear simultaneously
const ITEMS_START = 15;   // items start after brief header fade (~0.5s)

const StatRow: React.FC<{ stat: StatItem; index: number }> = ({ stat, index }) => {
  const frame = useCurrentFrame();
  const delay = ITEMS_START + index * STAGGER_DELAY;
  const fromLeft = index % 2 === 0;

  const progress = interpolate(frame, [delay, delay + ANIM_DURATION], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const translateX = (1 - progress) * (fromLeft ? -400 : 400);
  const opacity = progress;

  return (
    <div
      style={{
        opacity,
        transform: `translateX(${translateX}px)`,
        display: "flex",
        alignItems: "center",
        gap: 28,
        padding: "28px 48px",
        background: "rgba(255,255,255,0.08)",
        backdropFilter: "blur(8px)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 20,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 26, fontWeight: 400 }}>
          {stat.label}
        </div>
        <div style={{ color: "white", fontSize: 48, fontWeight: 700, lineHeight: 1.1 }}>
          {stat.value}
        </div>
      </div>
    </div>
  );
};

export const StatsScene: React.FC<Props> = ({ price, size, layout, floor, address, backgroundSrc }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerOpacity = interpolate(frame, [0, 0.3 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });

  const stats: StatItem[] = [
    { label: "開價", value: price },
    { label: "坪數", value: size },
    { label: "格局", value: layout },
    { label: "樓層", value: floor },
    ...(address ? [{ label: "地址", value: address }] : []),
  ];

  return (
    <AbsoluteFill style={{ fontFamily }}>
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
              transform: "scale(1.1)",
            }}
          />
          <AbsoluteFill style={{ background: "rgba(0,0,0,0.55)" }} />
        </>
      ) : (
        <AbsoluteFill
          style={{ background: "linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 100%)" }}
        />
      )}

      {/* Content */}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          padding: "100px 60px 80px",
        }}
      >
        {/* Section header */}
        <div
          style={{
            opacity: headerOpacity,
            color: "rgba(255,255,255,0.6)",
            fontSize: 40,
            letterSpacing: 8,
            marginBottom: 48,
            textAlign: "center",
          }}
        >
          物件資訊
        </div>

        {/* Stats list */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {stats.map((stat, i) => (
            <StatRow key={stat.label} stat={stat} index={i} />
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
