/**
 * Shrinks a photo before it's uploaded. Driver registration uploads up to
 * four photos in one request, often 3-8MB each straight off a phone
 * camera — on a weak mobile connection that's exactly the kind of request
 * that fails outright (see the registration failures diagnosed around
 * 2026-09-30/10-01, which turned out to be connection drops during these
 * uploads, not a server bug). Resizing to a sane max dimension and
 * re-encoding as JPEG cuts a typical photo down to a fraction of its
 * original size without hurting legibility for ID/vehicle verification.
 *
 * Never blocks a real submission: any failure (unsupported format,
 * decode error, canvas unavailable) just returns the original file
 * untouched rather than throwing.
 */

// 1600px on the longer side is comfortably enough resolution to read a
// driver's license or NIN slip, while cutting a typical 3000-4000px phone
// photo down dramatically.
const MAX_DIMENSION = 1600;
const JPEG_QUALITY = 0.8;

function scaledSize(width: number, height: number, maxDimension: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxDimension) return { width, height };
  const scale = maxDimension / longest;
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

async function loadBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === "function") {
    // imageOrientation: "from-image" applies the photo's own EXIF rotation
    // instead of leaving it sideways — most phone cameras write portrait
    // shots as landscape pixels plus an EXIF rotation flag.
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      return await createImageBitmap(file);
    }
  }
  // Older WebView fallback.
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not decode image"));
    };
    img.src = url;
  });
}

export async function compressImageFile(file: File): Promise<File> {
  // Only ever touches actual images — drivers_license and nin_slip_photo
  // also accept a PDF, which this can't (and shouldn't try to) compress.
  if (!file.type.startsWith("image/")) return file;

  try {
    const source = await loadBitmap(file);
    const sourceWidth = "width" in source ? source.width : 0;
    const sourceHeight = "height" in source ? source.height : 0;
    if (!sourceWidth || !sourceHeight) return file;

    const { width, height } = scaledSize(sourceWidth, sourceHeight, MAX_DIMENSION);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(source, 0, 0, width, height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
    );
    if (!blob) return file;
    // A small/already-compressed image can come back larger after
    // re-encoding — keep the original in that case rather than regress it.
    if (blob.size >= file.size) return file;

    const newName = file.name.replace(/\.[^./\\]+$/, "") + ".jpg";
    return new File([blob], newName, { type: "image/jpeg", lastModified: Date.now() });
  } catch {
    return file;
  }
}
