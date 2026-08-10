import { mediaUrl } from "../../api/forum";
import type { MediaItem } from "../../types/forum";

interface MediaGalleryProps {
  items: MediaItem[];
}

export default function MediaGallery(props: MediaGalleryProps): JSX.Element | null {
  if (props.items.length === 0) return null;
  return (
    <div className="forum-media-gallery">
      {props.items.map((item) =>
        item.media_type === "image" ? (
          <img key={item.id} className="forum-media-gallery__item" src={mediaUrl(item.id)} alt="" />
        ) : (
          <video key={item.id} className="forum-media-gallery__item" src={mediaUrl(item.id)} controls />
        ),
      )}
    </div>
  );
}
