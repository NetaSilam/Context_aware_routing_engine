import { useRef, useState } from "react";

import type { CreatePostRequest } from "../../api/forum";
import { HAZARD_TYPE_LABELS, HAZARD_TYPES } from "../../types/forum";
import type { HazardType } from "../../types/forum";

interface PostFormProps {
  disabled?: boolean;
  onSubmit: (payload: CreatePostRequest, files: File[]) => Promise<void>;
}

export default function PostForm(props: PostFormProps): JSX.Element {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [hazardType, setHazardType] = useState<HazardType>("pothole");
  const [isAnonymous, setIsAnonymous] = useState(false);
  const [longitude, setLongitude] = useState("");
  const [latitude, setLatitude] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function useCurrentLocation() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((position) => {
      setLongitude(String(position.coords.longitude));
      setLatitude(String(position.coords.latitude));
    });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await props.onSubmit(
        {
          title,
          body,
          hazard_type: hazardType,
          is_anonymous: isAnonymous,
          longitude: longitude === "" ? undefined : Number(longitude),
          latitude: latitude === "" ? undefined : Number(latitude),
        },
        files,
      );
      setTitle("");
      setBody("");
      setIsAnonymous(false);
      setLongitude("");
      setLatitude("");
      setFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the report.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="forum-post-form" aria-label="Report a hazard" onSubmit={handleSubmit}>
      {error ? <p className="error-banner">{error}</p> : null}
      <label>
        Title
        <input
          value={title}
          maxLength={200}
          required
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <label>
        Hazard type
        <select value={hazardType} onChange={(event) => setHazardType(event.target.value as HazardType)}>
          {HAZARD_TYPES.map((type) => (
            <option key={type} value={type}>
              {HAZARD_TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Description
        <textarea
          value={body}
          maxLength={5000}
          required
          rows={3}
          onChange={(event) => setBody(event.target.value)}
        />
      </label>
      <div className="forum-post-form__location">
        <label>
          Longitude (optional)
          <input
            type="number"
            step="any"
            min={-180}
            max={180}
            value={longitude}
            onChange={(event) => setLongitude(event.target.value)}
          />
        </label>
        <label>
          Latitude (optional)
          <input
            type="number"
            step="any"
            min={-90}
            max={90}
            value={latitude}
            onChange={(event) => setLatitude(event.target.value)}
          />
        </label>
        <button type="button" className="ghost-button" onClick={useCurrentLocation}>
          Use my current location
        </button>
      </div>
      <label>
        Photos or videos (optional)
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,video/*"
          multiple
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
        />
      </label>
      <label className="forum-post-form__checkbox">
        <input
          type="checkbox"
          checked={isAnonymous}
          onChange={(event) => setIsAnonymous(event.target.checked)}
        />
        Post anonymously
      </label>
      <button type="submit" className="primary-button" disabled={props.disabled || submitting}>
        {submitting ? "Reporting…" : "Report hazard"}
      </button>
    </form>
  );
}
