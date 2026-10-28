import fc from "fast-check";
import { checkFile, checkTotal, formatMb, hasTiffExtension, hasTiffSignature, MAX_UPLOAD_MB } from "./files";

const MB = 1024 * 1024;
const tiffHead = new Uint8Array([0x49, 0x49, 0x2a, 0x00]);

/** File com tamanho declarado sem alocar a memória toda. */
function sizedFile(name: string, size: number, head = tiffHead): File {
  const f = new File([head], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
}

describe("assinatura TIFF", () => {
  it.each([
    [[0x49, 0x49, 0x2a, 0x00], true], // II* little-endian
    [[0x4d, 0x4d, 0x00, 0x2a], true], // MM* big-endian
    [[0x49, 0x49, 0x2b, 0x00], true], // BigTIFF
    [[0x4d, 0x4d, 0x00, 0x2b], true],
    [[0x89, 0x50, 0x4e, 0x47], false], // PNG
    [[0x49, 0x49, 0x2a], false], // curto demais
  ])("%j -> %s", async (bytes, ok) => {
    expect(await hasTiffSignature(new Blob([new Uint8Array(bytes)]))).toBe(ok);
  });
});

describe("extensão", () => {
  it.each([
    ["a.tif", true],
    ["a.TIFF", true],
    ["a.tif.exe", false],
    ["tif", false],
    ["a.png", false],
  ])("%s -> %s", (n, ok) => expect(hasTiffExtension(n)).toBe(ok));
});

describe("checkFile (BVA no limite de tamanho)", () => {
  it("aceita exatamente o máximo", async () => {
    expect(await checkFile("primary", sizedFile("a.tif", MAX_UPLOAD_MB * MB))).toBeNull();
  });
  it("rejeita 1 byte acima", async () => {
    expect(await checkFile("primary", sizedFile("a.tif", MAX_UPLOAD_MB * MB + 1))).toMatch(/excede/);
  });
  it("rejeita vazio", async () => {
    expect(await checkFile("scl", new File([], "a.tif"))).toMatch(/vazio/);
  });
  it("rejeita extensão errada antes de ler bytes", async () => {
    expect(await checkFile("secondary", sizedFile("a.png", 10))).toMatch(/GeoTIFF/);
  });
  it("rejeita .tif que não é TIFF", async () => {
    expect(await checkFile("primary", sizedFile("a.tif", 10, new Uint8Array([1, 2, 3, 4])))).toMatch(/não é um TIFF/);
  });
});

describe("checkTotal", () => {
  it("soma todos os arquivos (o limite do backend é do corpo inteiro)", () => {
    const half = sizedFile("a.tif", (MAX_UPLOAD_MB * MB) / 2);
    expect(checkTotal([half, half])).toBeNull();
    expect(checkTotal([half, half, sizedFile("b.tif", 1)])).toMatch(/somam/);
    expect(checkTotal([null, undefined])).toBeNull();
  });
});

describe("formatMb", () => {
  it("KB abaixo de 1 MB, nunca '0'", () => {
    expect(formatMb(1)).toBe("1 KB");
    expect(formatMb(6731)).toBe("7 KB");
    expect(formatMb(MB)).toBe("1 MB");
  });
  it("propriedade: monotônico em MB", () => {
    fc.assert(
      fc.property(fc.integer({ min: MB, max: 1e10 }), fc.integer({ min: 0, max: 1e9 }), (a, d) => {
        const n = (s: string) => Number(s.replace(" MB", "").replace(/\./g, "").replace(",", "."));
        return n(formatMb(a)) <= n(formatMb(a + d));
      }),
    );
  });
});
