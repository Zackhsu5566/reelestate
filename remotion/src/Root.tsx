import { Composition } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { ReelEstateVideo, calcTotalFrames } from "./ReelEstateVideo";
import type { VideoInput } from "./types";

const FPS = 30;

const calculateMetadata: CalculateMetadataFunction<VideoInput> = async ({ props }) => {
  let { lat, lng } = props;

  // Geocode address → lat/lng via Mapbox
  if (!lat || !lng) {
    if (props.mapboxToken && props.address) {
      try {
        const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(
          props.address
        )}.json?access_token=${props.mapboxToken}&language=zh-TW&country=TW`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.features?.[0]) {
          [lng, lat] = data.features[0].center as [number, number];
        }
      } catch {
        // geocoding failure → map won't show
      }
    }
  }

  // Geocode POIs for location scenes
  const updatedScenes = [...props.scenes];
  if (lat && lng && props.mapboxToken) {
    for (let i = 0; i < updatedScenes.length; i++) {
      const scene = updatedScenes[i];
      // Handle "opening" scenes with POIs
      const scenePois =
        scene.type === "opening" ? scene.pois :
        undefined;
      if (!scenePois?.length) continue;

      const resolved: typeof scenePois = [];
      for (const poi of scenePois) {
        if (poi.lat != null && poi.lng != null) {
          resolved.push(poi);
          continue;
        }
        try {
          const q = encodeURIComponent(poi.name);
          const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${q}.json?access_token=${props.mapboxToken}&proximity=${lng},${lat}&language=zh-TW&country=TW&limit=1`;
          const res = await fetch(url);
          const data = await res.json();
          if (data.features?.[0]) {
            const [poiLng, poiLat] = data.features[0].center as [number, number];
            resolved.push({ ...poi, lat: poiLat, lng: poiLng });
          }
        } catch {
          // skip failed POI
        }
      }
      if (scene.type === "opening") {
        updatedScenes[i] = { ...scene, pois: resolved };
      }
    }
  }

  return {
    durationInFrames: calcTotalFrames(updatedScenes),
    props: { ...props, scenes: updatedScenes, lat, lng },
  };
};

const defaultProps: VideoInput = {
  title: "信義區精裝兩房",
  location: "台北市信義區",
  address: "台北市信義區永吉路 XX 號",
  community: "信義之星",
  propertyType: "電梯大樓",
  buildingAge: "屋齡12年",
  size: "35坪",
  layout: "2房2廳1衛",
  floor: "12F / 15F",
  price: "2,980萬",
  contact: "0912-345-678",
  line: "wang_realestate",
  agentName: "王小明 | 信義房屋",
  scenes: [
    { type: "opening", durationInFrames: 300, pois: [
      { name: "信義安和站", category: "mrt", distance: "步行3分鐘", lat: 25.0410, lng: 121.5530 },
      { name: "全聯福利中心", category: "supermarket", distance: "步行5分鐘", lat: 25.0470, lng: 121.5680 },
      { name: "大安森林公園", category: "park", distance: "步行10分鐘", lat: 25.0380, lng: 121.5580 },
    ]},
    { type: "clip", src: "clips/exterior.mp4", label: "外觀", durationInFrames: 150 },
    { type: "clip", src: "clips/living-room-reversed.mp4", label: "客廳", durationInFrames: 150, stagingImage: "images/staging-living-room.png" },
    { type: "clip", src: "clips/kitchen-reversed.mp4", label: "廚房", durationInFrames: 150, stagingImage: "images/staging-kitchen.jpg" },
    { type: "clip", src: "clips/bedroom-s.mp4", label: "房間", durationInFrames: 105 },
    { type: "stats", durationInFrames: 220, backgroundSrc: "images/exterior-bg.webp" },
    { type: "cta", durationInFrames: 90, backgroundSrc: "images/exterior-bg.webp" },
  ],
  mapboxToken: process.env.MAPBOX_TOKEN || "",
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ReelEstateVideo"
      component={ReelEstateVideo}
      durationInFrames={calcTotalFrames(defaultProps.scenes)}
      fps={FPS}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
      calculateMetadata={calculateMetadata}
    />
  );
};
