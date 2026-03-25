export type OpeningSceneInput = {
  type: "opening";
  durationInFrames: number;
  pois?: POI[];
};

export type ClipSceneInput = {
  type: "clip";
  src: string;
  label: string;
  durationInFrames: number;
  stagingImage?: string;
};

export type StatsSceneInput = {
  type: "stats";
  durationInFrames: number;
  backgroundSrc?: string;
};

export type CTASceneInput = {
  type: "cta";
  durationInFrames: number;
  backgroundSrc?: string;
};

export type POI = {
  name: string;
  category: "mrt" | "supermarket" | "park" | "school" | "hospital" | "other";
  distance: string;
  lat?: number;
  lng?: number;
};

export type NarrationSubtitle = {
  text: string;
  time_begin: number; // milliseconds
  time_end: number;   // milliseconds
};

export type SceneInput =
  | OpeningSceneInput
  | ClipSceneInput
  | StatsSceneInput
  | CTASceneInput;

export type VideoInput = {
  title: string;
  location: string;
  address: string;
  community?: string;
  propertyType?: string;
  buildingAge?: string;
  size: string;
  layout: string;
  floor: string;
  price: string;
  contact: string;
  line?: string;
  agentName: string;
  scenes: SceneInput[];
  bgm?: string;
  narration?: string;
  narrationSubtitles?: NarrationSubtitle[];
  mapboxToken?: string;
  lat?: number;
  lng?: number;
};
