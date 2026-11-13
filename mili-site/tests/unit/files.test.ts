import { describe, expect, it } from "vitest";
import { CHALLENGE_FILE_TYPES, checkUpload, detectFile, extensionOf } from "@/lib/files";

const text = (s: string) => new TextEncoder().encode(s);
const bytes = (...b: number[]) => new Uint8Array([...b, ...new Array(64).fill(1)]);

function binaryStl(triangles: number): Uint8Array {
  const buf = new Uint8Array(84 + triangles * 50);
  new DataView(buf.buffer).setUint32(80, triangles, true);
  return buf;
}

describe("file detection by content", () => {
  it("recognises every accepted format from its bytes", () => {
    expect(detectFile(text("%PDF-1.7\n..."))?.ext).toBe("pdf");
    expect(detectFile(bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))?.ext).toBe("png");
    expect(detectFile(bytes(0xff, 0xd8, 0xff, 0xe0))?.ext).toBe("jpg");
    expect(detectFile(text("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('x'),'2;1');"))?.ext).toBe("step");
    expect(detectFile(text("solid part\n facet normal 0 0 1\n  outer loop\n"))?.ext).toBe("stl");
    expect(detectFile(binaryStl(3))?.ext).toBe("stl");
    expect(detectFile(text("# cube\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\nf 1 2 3\n"))?.ext).toBe("obj");
  });

  it("rejects executables, HTML, SVG and scripts whatever they are called", () => {
    expect(detectFile(bytes(0x4d, 0x5a, 0x90, 0x00))).toBeNull(); // PE executable
    expect(detectFile(text("<html><script>alert(1)</script></html>"))).toBeNull();
    expect(detectFile(text('<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>'))).toBeNull();
    expect(detectFile(text("#!/bin/sh\nrm -rf /\n"))).toBeNull();
  });

  it("normalises extensions", () => {
    expect(extensionOf("Part.STP")).toBe("step");
    expect(extensionOf("photo.JPEG")).toBe("jpg");
    expect(extensionOf("noext")).toBe("");
  });
});

describe("upload validation", () => {
  const max = 1024;
  it("accepts a real file whose extension matches its content", () => {
    const result = checkUpload(text("%PDF-1.4 hello"), "my plan (v2).pdf", CHALLENGE_FILE_TYPES, max);
    expect(result).toMatchObject({ ok: true, file: { ext: "pdf" } });
  });
  it("rejects a renamed file", () => {
    expect(checkUpload(text("<html></html>"), "part.step", CHALLENGE_FILE_TYPES, max)).toEqual({ ok: false, error: "type_not_allowed" });
    expect(checkUpload(text("%PDF-1.4"), "part.png", CHALLENGE_FILE_TYPES, max)).toEqual({ ok: false, error: "extension_mismatch" });
  });
  it("rejects a format outside the allow-list even when the content is valid", () => {
    expect(checkUpload(text("%PDF-1.4"), "doc.pdf", ["png"], max)).toEqual({ ok: false, error: "type_not_allowed" });
    expect(checkUpload(text("x"), "run.exe", CHALLENGE_FILE_TYPES, max)).toEqual({ ok: false, error: "type_not_allowed" });
  });
  it("enforces the size limit and refuses empty files", () => {
    expect(checkUpload(new Uint8Array(max + 1), "a.pdf", CHALLENGE_FILE_TYPES, max)).toEqual({ ok: false, error: "too_large" });
    expect(checkUpload(new Uint8Array(0), "a.pdf", CHALLENGE_FILE_TYPES, max)).toEqual({ ok: false, error: "empty" });
  });
});
