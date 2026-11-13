import "server-only";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { DeleteObjectCommand, GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { env } from "../env";

/**
 * Private object storage. Nothing stored here is reachable by URL: files are
 * only streamed through authenticated or mode-gated route handlers.
 */
export interface StorageDriver {
  put(key: string, data: Uint8Array, mime: string): Promise<void>;
  get(key: string): Promise<Uint8Array | null>;
  delete(key: string): Promise<void>;
}

const KEY_PATTERN = /^[a-z0-9][a-z0-9/_.-]{2,200}$/;

function assertKey(key: string): void {
  if (!KEY_PATTERN.test(key) || key.includes("..")) throw new Error(`Invalid storage key: ${key}`);
}

/** Development driver: a directory outside `public/`, ignored by git. */
class LocalStorage implements StorageDriver {
  constructor(private readonly root: string) {}
  private file(key: string): string {
    assertKey(key);
    return path.join(this.root, key);
  }
  async put(key: string, data: Uint8Array): Promise<void> {
    const file = this.file(key);
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, data);
  }
  async get(key: string): Promise<Uint8Array | null> {
    try {
      return await readFile(this.file(key));
    } catch {
      return null;
    }
  }
  async delete(key: string): Promise<void> {
    await rm(this.file(key), { force: true });
  }
}

/** Production driver: any S3-compatible private bucket (AWS S3, Cloudflare R2, Backblaze, MinIO…). */
class S3Storage implements StorageDriver {
  private readonly client: S3Client;
  constructor(private readonly bucket: string) {
    const e = env();
    this.client = new S3Client({
      region: e.S3_REGION,
      endpoint: e.S3_ENDPOINT,
      forcePathStyle: Boolean(e.S3_ENDPOINT),
      credentials: { accessKeyId: e.S3_ACCESS_KEY_ID ?? "", secretAccessKey: e.S3_SECRET_ACCESS_KEY ?? "" },
    });
  }
  async put(key: string, data: Uint8Array, mime: string): Promise<void> {
    assertKey(key);
    await this.client.send(new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: data, ContentType: mime }));
  }
  async get(key: string): Promise<Uint8Array | null> {
    assertKey(key);
    try {
      const out = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }));
      return out.Body ? await out.Body.transformToByteArray() : null;
    } catch (err) {
      if ((err as { name?: string }).name === "NoSuchKey") return null;
      throw err;
    }
  }
  async delete(key: string): Promise<void> {
    assertKey(key);
    await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: key }));
  }
}

let driver: StorageDriver | undefined;

export function storage(): StorageDriver {
  if (driver) return driver;
  const e = env();
  if (e.STORAGE_DRIVER === "s3") {
    if (!e.S3_BUCKET || !e.S3_ACCESS_KEY_ID || !e.S3_SECRET_ACCESS_KEY) {
      throw new Error("STORAGE_DRIVER=s3 requires S3_BUCKET, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY");
    }
    driver = new S3Storage(e.S3_BUCKET);
  } else {
    driver = new LocalStorage(path.resolve(process.cwd(), e.STORAGE_LOCAL_DIR));
  }
  return driver;
}

export function maxUploadBytes(): number {
  return Math.floor(env().UPLOAD_MAX_MB * 1024 * 1024);
}
