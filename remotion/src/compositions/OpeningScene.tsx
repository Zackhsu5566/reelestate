import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";
import { loadFont as loadSerifFont } from "@remotion/google-fonts/NotoSerifTC";
import { MapboxFlyIn, FLY_DURATION_FRAMES, POI_START_FRAME } from "./MapboxFlyIn";
import type { POI } from "../types";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
});

const { fontFamily: serifFontFamily } = loadSerifFont("normal", {
  weights: ["700", "900"],
});

type Props = {
  title: string;
  location: string;
  address: string;
  community?: string;
  propertyType?: string;
  buildingAge?: string;
  floor?: string;
  mapboxToken?: string;
  lat?: number;
  lng?: number;
  pois?: POI[];
};

export const OpeningScene: React.FC<Props> = ({
  title,
  location,
  address,
  community,
  propertyType,
  buildingAge,
  floor,
  mapboxToken,
  lat,
  lng,
  pois,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const hasCoords = lat !== undefined && lng !== undefined;
  const showMapbox = !!(mapboxToken && hasCoords);
  const showPois = !!(pois && pois.length > 0);

  // Text fades out after fly-in when POIs follow
  const textOpacity = showPois
    ? interpolate(frame, [FLY_DURATION_FRAMES, FLY_DURATION_FRAMES + 30], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;

  // "生活機能" header — fades in when POIs start
  const poiHeaderOpacity = showPois
    ? interpolate(frame, [POI_START_FRAME, POI_START_FRAME + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 0;

  const locationOpacity = interpolate(frame, [0.3 * fps, 1 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });
  const locationY = interpolate(frame, [0.3 * fps, 1 * fps], [24, 0], {
    extrapolateRight: "clamp",
  });

  const titleOpacity = interpolate(frame, [0.6 * fps, 1.4 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(frame, [0.6 * fps, 1.4 * fps], [32, 0], {
    extrapolateRight: "clamp",
  });

  const addressOpacity = interpolate(frame, [1 * fps, 1.8 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });

  const tagsOpacity = interpolate(frame, [1.3 * fps, 2.1 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });
  const tagsY = interpolate(frame, [1.3 * fps, 2.1 * fps], [16, 0], {
    extrapolateRight: "clamp",
  });

  const tags = [
    community && { label: community },
    propertyType && { label: propertyType },
    buildingAge && { label: buildingAge },
    floor && { label: floor },
  ].filter(Boolean) as { label: string }[];

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* Mapbox */}
      {showMapbox && (
        <AbsoluteFill>
          <MapboxFlyIn lat={lat!} lng={lng!} token={mapboxToken!} pois={showPois ? pois : undefined} />
        </AbsoluteFill>
      )}

      {/* Fallback dark gradient when no map */}
      {!showMapbox && (
        <AbsoluteFill
          style={{ background: "linear-gradient(180deg, #0a0a0a 0%, #1a1a2e 100%)" }}
        />
      )}

      {/* Gradient overlay — dark at bottom for white text */}
      <AbsoluteFill
        style={{
          opacity: textOpacity,
          background:
            "linear-gradient(to top, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.3) 55%, transparent 100%)",
        }}
      />

      {/* Text content */}
      <AbsoluteFill
        style={{
          opacity: textOpacity,
          justifyContent: "flex-end",
          alignItems: "center",
          flexDirection: "column",
          gap: 28,
          padding: "0 80px 320px",
          fontFamily,
        }}
      >
        <div
          style={{
            opacity: locationOpacity,
            transform: `translateY(${locationY}px)`,
            background: "rgba(255,255,255,0.12)",
            backdropFilter: "blur(8px)",
            border: "1px solid rgba(255,255,255,0.25)",
            borderRadius: 100,
            padding: "10px 36px",
            color: "rgba(255,255,255,0.85)",
            fontSize: 32,
            letterSpacing: 6,
          }}
        >
          {location}
        </div>

        <div
          style={{
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
            fontFamily: serifFontFamily,
            color: "white",
            fontSize: 80,
            fontWeight: 900,
            textAlign: "center",
            lineHeight: 1.25,
            textShadow: "0 2px 24px rgba(0,0,0,0.55)",
          }}
        >
          {title}
        </div>

        <div
          style={{
            opacity: addressOpacity,
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "rgba(0,0,0,0.45)",
            backdropFilter: "blur(10px)",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: 12,
            padding: "10px 28px",
            color: "rgba(255,255,255,0.8)",
            fontSize: 26,
          }}
        >
          <span style={{ fontSize: 22, opacity: 0.6 }}>📍</span>
          {address}
        </div>

        {/* Info tags — 社區 / 型態 / 屋齡 / 樓層 */}
        {tags.length > 0 && (
          <div
            style={{
              opacity: tagsOpacity,
              transform: `translateY(${tagsY}px)`,
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "center",
              gap: 16,
              marginTop: 8,
            }}
          >
            {tags.map(({ label }) => (
              <div
                key={label}
                style={{
                  background: "rgba(255,255,255,0.12)",
                  backdropFilter: "blur(8px)",
                  border: "1px solid rgba(255,255,255,0.25)",
                  borderRadius: 10,
                  padding: "10px 28px",
                  color: "rgba(255,255,255,0.85)",
                  fontSize: 26,
                  fontWeight: 700,
                  letterSpacing: 1,
                }}
              >
                {label}
              </div>
            ))}
          </div>
        )}
      </AbsoluteFill>

      {/* Bottom gradient + "生活機能" header — shown during POI phase */}
      {showPois && (
        <AbsoluteFill
          style={{
            opacity: poiHeaderOpacity,
            background: "linear-gradient(to top, rgba(0,0,0,0.6) 0%, transparent 40%)",
            justifyContent: "flex-end",
            alignItems: "center",
            paddingBottom: 80,
            fontFamily,
          }}
        >
          <div
            style={{
              color: "rgba(255,255,255,0.7)",
              fontSize: 28,
              letterSpacing: 8,
              fontWeight: 400,
            }}
          >
            生活機能
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
