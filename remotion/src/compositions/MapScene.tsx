import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";
import { MapboxFlyIn, POI_START_FRAME } from "./MapboxFlyIn";
import type { POI } from "../types";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
});

type Props = {
  mapboxToken?: string;
  lat?: number;
  lng?: number;
  pois?: POI[];
};

export const MapScene: React.FC<Props> = ({
  mapboxToken,
  lat,
  lng,
  pois,
}) => {
  const frame = useCurrentFrame();

  const hasCoords = lat !== undefined && lng !== undefined;
  const showMapbox = !!(mapboxToken && hasCoords);
  const showPois = !!(pois && pois.length > 0);

  // "生活機能" header — fades in when POIs start
  const poiHeaderOpacity = showPois
    ? interpolate(frame, [POI_START_FRAME, POI_START_FRAME + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {showMapbox && (
        <AbsoluteFill>
          <MapboxFlyIn lat={lat!} lng={lng!} token={mapboxToken!} pois={showPois ? pois : undefined} />
        </AbsoluteFill>
      )}

      {!showMapbox && (
        <AbsoluteFill
          style={{ background: "linear-gradient(180deg, #0a0a0a 0%, #1a1a2e 100%)" }}
        />
      )}

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
