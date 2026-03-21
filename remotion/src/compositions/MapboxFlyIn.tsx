import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useRef, useState } from "react";
import {
  continueRender,
  delayRender,
  Easing,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";
import type { POI } from "../types";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
});

const MAPBOX_STYLE_ID = "beingzackhsu/cmmrh4sis008501rndfa72u92";

// Exported for OpeningScene timing
export const FLY_DURATION_FRAMES = 120; // 4s at 30fps
export const POI_START_FRAME = 150; // POIs appear at 5s

const POI_STAGGER = 45; // ~1.5s between each POI
const POI_ANIM_FRAMES = 15; // ~0.5s animation duration

const CATEGORY_COLORS: Record<POI["category"], string> = {
  mrt: "#00B4D8",
  supermarket: "#FFD700",
  park: "#4CAF50",
  school: "#FF9800",
  hospital: "#E91E63",
  other: "#9E9E9E",
};

type ScreenPOI = POI & { x: number; y: number };

type Props = {
  lat: number;
  lng: number;
  token: string;
  pois?: POI[];
};

function cameraAtFrame(frame: number) {
  const t = Math.min(frame / FLY_DURATION_FRAMES, 1);
  const p = Easing.out(Easing.cubic)(t);
  return {
    zoom: interpolate(p, [0, 1], [10, 13]),
    pitch: interpolate(p, [0, 1], [0, 30]),
    bearing: interpolate(p, [0, 1], [0, 0]),
  };
}

export const MapboxFlyIn: React.FC<Props> = ({
  lat,
  lng,
  token,
  pois = [],
}) => {
  const frame = useCurrentFrame();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [screenPois, setScreenPois] = useState<ScreenPOI[]>([]);

  const [initHandle] = useState(() => delayRender("Mapbox init"));

  useEffect(() => {
    if (!containerRef.current) return;

    mapboxgl.accessToken = token;

    const originalError = console.error;
    console.error = (...args: unknown[]) => {
      if (String(args[0] ?? "").includes("Could not load models")) return;
      originalError.apply(console, args);
    };

    const initial = cameraAtFrame(0);
    const styleUrl = `https://api.mapbox.com/styles/v1/${MAPBOX_STYLE_ID}?access_token=${token}&fresh=true`;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: styleUrl,
      center: [lng, lat],
      zoom: initial.zoom,
      pitch: initial.pitch,
      bearing: initial.bearing,
      interactive: false,
      attributionControl: false,
      fadeDuration: 0,
    });

    map.once("idle", () => {
      const style = map.getStyle();
      if (style?.layers) {
        for (const layer of style.layers) {
          if (layer.type === ("model" as unknown as mapboxgl.Layer["type"])) {
            try {
              map.removeLayer(layer.id);
            } catch {}
          }
        }
      }
      // Pin marker
      const el = document.createElement("div");
      el.style.cssText = `
        width: 28px; height: 28px; border-radius: 50%;
        background: #FFD700; border: 3px solid #fff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.5);
      `;
      new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);

      mapRef.current = map;
      setMapReady(true);
      continueRender(initHandle);
    });

    return () => {
      console.error = originalError;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const handle = delayRender("Mapbox frame idle");

    const { zoom, pitch, bearing } = cameraAtFrame(frame);

    map.jumpTo({ center: [lng, lat], zoom, pitch, bearing });

    // Project POIs to screen coordinates after camera settles
    if (pois.length > 0 && frame >= FLY_DURATION_FRAMES) {
      const projected: ScreenPOI[] = [];
      for (const poi of pois) {
        if (poi.lat == null || poi.lng == null) continue;
        const pt = map.project([poi.lng, poi.lat]);
        projected.push({ ...poi, x: pt.x, y: pt.y });
      }
      setScreenPois(projected);
    }

    map.once("idle", () => continueRender(handle));

    return () => continueRender(handle);
  }, [frame, mapReady]);

  return (
    <>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

      {/* POI markers overlay */}
      {screenPois.map((poi, i) => {
        const delay = POI_START_FRAME + i * POI_STAGGER;
        const progress = interpolate(
          frame,
          [delay, delay + POI_ANIM_FRAMES],
          [0, 1],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.out(Easing.cubic),
          },
        );

        const scale = interpolate(progress, [0, 1], [0.3, 1]);
        const color = CATEGORY_COLORS[poi.category] || CATEGORY_COLORS.other;

        return (
          <div
            key={`${poi.name}-${i}`}
            style={{
              position: "absolute",
              left: poi.x,
              top: poi.y,
              transform: `translate(-50%, -100%) scale(${scale})`,
              opacity: progress,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              pointerEvents: "none",
              fontFamily,
            }}
          >
            {/* Label */}
            <div
              style={{
                background: "rgba(0,0,0,0.75)",
                backdropFilter: "blur(6px)",
                borderRadius: 10,
                padding: "8px 18px",
                marginBottom: 8,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 2,
                border: `2px solid ${color}`,
              }}
            >
              <div
                style={{
                  color: "white",
                  fontSize: 24,
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                }}
              >
                {poi.name}
              </div>
              <div
                style={{
                  color: "rgba(255,255,255,0.7)",
                  fontSize: 18,
                  fontWeight: 400,
                  whiteSpace: "nowrap",
                }}
              >
                {poi.distance}
              </div>
            </div>

            {/* Pin dot */}
            <div
              style={{
                width: 18,
                height: 18,
                borderRadius: "50%",
                background: color,
                border: "2px solid #fff",
                boxShadow: "0 2px 6px rgba(0,0,0,0.4)",
              }}
            />
          </div>
        );
      })}
    </>
  );
};
