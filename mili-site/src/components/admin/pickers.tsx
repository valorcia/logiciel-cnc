import { db } from "@/lib/db";

export const STATUS_OPTIONS = [["DRAFT", "Brouillon"], ["SCHEDULED", "Programmé"], ["PUBLISHED", "Publié"], ["ARCHIVED", "Archivé"]] as const;

export type MediaOption = { id: string; fileName: string; visibility: string; placement: string };
export const mediaOptions = (): Promise<MediaOption[]> =>
  db.mediaAsset.findMany({ orderBy: { createdAt: "desc" }, select: { id: true, fileName: true, visibility: true, placement: true }, take: 300 });

/** Image chooser. `publicOnly` hides confidential (Reveal-only) images from places that are visible during the mystery. */
export function MediaSelect({ label, name, value, media, publicOnly, help }: { label: string; name: string; value?: string | null; media: MediaOption[]; publicOnly?: boolean; help?: string }) {
  const list = media.filter((m) => !publicOnly || m.visibility === "PUBLIC" || m.id === value);
  return (
    <div>
      <label htmlFor={`m-${name}`} className="field-label">{label}</label>
      <select id={`m-${name}`} name={name} defaultValue={value ?? ""} className="field">
        <option value="">Aucune image</option>
        {list.map((m) => <option key={m.id} value={m.id}>{m.fileName}{m.visibility === "PUBLIC" ? "" : " — confidentielle"}</option>)}
      </select>
      <p className="mt-1.5 text-xs leading-relaxed text-smoke">{help ?? (publicOnly ? "Seules les images marquées « publiques » dans Médias sont proposées ici." : "Les images s'ajoutent dans Médias.")}</p>
    </div>
  );
}
