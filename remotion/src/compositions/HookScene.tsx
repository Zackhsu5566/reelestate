import { Img, Sequence, staticFile, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";

const { fontFamily } = loadFont("normal", { weights: ["700"] });

type Props = {
  images: string[];
  framesPerImage: number;
};

/**
 * Hook scene: rapid-fire staging images to grab attention.
 * Hard cuts between images, no transitions.
 */
export const HookScene: React.FC<Props> = ({ images, framesPerImage }) => {
  const frame = useCurrentFrame();

  return (
    <>
      {images.map((src, i) => (
        <Sequence key={i} from={i * framesPerImage} durationInFrames={framesPerImage}>
          <Img
            src={staticFile(src)}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        </Sequence>
      ))}

      {/* "Before → After" badge */}
      <div
        style={{
          position: "absolute",
          top: 60,
          right: 40,
          background: "rgba(0,0,0,0.6)",
          backdropFilter: "blur(8px)",
          borderRadius: 12,
          padding: "10px 20px",
          fontFamily,
          fontSize: 28,
          fontWeight: 700,
          color: "#FFD700",
        }}
      >
        ✨ AI 虛擬裝潢
      </div>
    </>
  );
};
