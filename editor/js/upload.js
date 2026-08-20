/* Upload pipeline: shrink -> presign -> PUT to storage -> complete, three
   files at a time. Job objects surface per-file progress; the caller
   re-renders the tray and polls the photo list for ingest results.

   Phone photos are 12-48MP and 3-12MB each; uploading them untouched over a
   mobile connection is the slowest part of making a book by a wide margin.
   We therefore downscale in the browser BEFORE uploading — but never below
   what the print needs: MAX_EDGE keeps a full-bleed A5 page at 300dpi even
   for a landscape photo cropped to portrait (the worst case). Anything the
   browser cannot decode (HEIC outside Safari) uploads untouched. */
import * as api from './api.js';

// Absurd-file guard only; the shrink step is what actually keeps uploads
// small, and the server enforces its own limit on what arrives.
const MAX_BYTES = 80 * 1024 * 1024;
const MIME_BY_EXT = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
  heic: 'image/heic', heif: 'image/heif',
};

// 3500px long edge: a landscape 4:3 photo cropped to the portrait page still
// yields ~1870x2625px against the 1819x2551px that 300dpi demands.
const MAX_EDGE = 3500;
const JPEG_QUALITY = 0.85;
// Below this the transfer is already quick and re-encoding only loses quality.
const SKIP_SHRINK_BYTES = 900 * 1024;

function guessMime(file) {
  if (file.type && file.type !== 'application/octet-stream') return file.type;
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  return MIME_BY_EXT[ext] || '';
}

/* ---------- JPEG header scan: EXIF date, orientation, raw size ---------- */

function parseExifIfd(view, tiff, littleEndian) {
  const out = { date: null, orientation: 1 };
  const ifd0 = tiff + view.getUint32(tiff + 4, littleEndian);
  const readAscii = (offset, count) => {
    let s = '';
    for (let i = 0; i < count - 1; i += 1) s += String.fromCharCode(view.getUint8(offset + i));
    return s;
  };
  const walk = (dirStart, depth) => {
    const entries = view.getUint16(dirStart, littleEndian);
    for (let i = 0; i < entries; i += 1) {
      const entry = dirStart + 2 + i * 12;
      const tag = view.getUint16(entry, littleEndian);
      const count = view.getUint32(entry + 4, littleEndian);
      const valueAt = entry + 8;
      if (tag === 0x0112) {                       // Orientation
        out.orientation = view.getUint16(valueAt, littleEndian) || 1;
      } else if (tag === 0x9003 || (tag === 0x0132 && !out.date)) {
        // DateTimeOriginal, else DateTime — "YYYY:MM:DD HH:MM:SS"
        const at = count > 4 ? tiff + view.getUint32(valueAt, littleEndian) : valueAt;
        const text = readAscii(at, count);
        if (/^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}/.test(text)) out.date = text.slice(0, 19);
      } else if (tag === 0x8769 && depth === 0) {  // Exif sub-IFD
        walk(tiff + view.getUint32(valueAt, littleEndian), 1);
      }
    }
  };
  walk(ifd0, 0);
  return out;
}

/* One pass over the JPEG markers: EXIF (date + orientation) and the SOF
   frame size. The raw size lets us verify the browser applied EXIF
   orientation the way we asked, instead of trusting it blindly. */
async function readJpegHeader(file) {
  const info = { date: null, orientation: 1, rawWidth: 0, rawHeight: 0 };
  try {
    const buf = await file.slice(0, 256 * 1024).arrayBuffer();
    const view = new DataView(buf);
    if (view.getUint16(0, false) !== 0xffd8) return info;   // not a JPEG
    let offset = 2;
    while (offset + 4 < view.byteLength) {
      if (view.getUint8(offset) !== 0xff) break;
      const marker = view.getUint8(offset + 1);
      const size = view.getUint16(offset + 2, false);
      if (marker === 0xe1 && view.getUint32(offset + 4, false) === 0x45786966) {
        const tiff = offset + 10;                            // after "Exif\0\0"
        const littleEndian = view.getUint16(tiff, false) === 0x4949;
        Object.assign(info, parseExifIfd(view, tiff, littleEndian));
      } else if (marker >= 0xc0 && marker <= 0xcf
                 && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
        info.rawHeight = view.getUint16(offset + 5, false);
        info.rawWidth = view.getUint16(offset + 7, false);
        break;                                               // SOF ends the scan
      } else if (marker === 0xda) {
        break;                                               // start of scan
      }
      offset += 2 + size;
    }
  } catch (e) { /* unreadable header: proceed without hints */ }
  return info;
}

/* ---------- downscale ---------- */

// Canvas transform per EXIF orientation, expressed in the ORIENTED frame.
const ORIENT_MATRIX = {
  1: [1, 0, 0, 1, 0, 0],
  2: [-1, 0, 0, 1, 1, 0],
  3: [-1, 0, 0, -1, 1, 1],
  4: [1, 0, 0, -1, 0, 1],
  5: [0, 1, 1, 0, 0, 0],
  6: [0, 1, -1, 0, 1, 0],
  7: [0, -1, -1, 0, 1, 1],
  8: [0, -1, 1, 0, 0, 1],
};

function drawOriented(ctx, bitmap, orientation, width, height) {
  const m = ORIENT_MATRIX[orientation] || ORIENT_MATRIX[1];
  ctx.setTransform(m[0], m[1], m[2], m[3], m[4] * width, m[5] * height);
  const swap = orientation >= 5;
  ctx.drawImage(bitmap, 0, 0, swap ? height : width, swap ? width : height);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

/* Returns { blob, mime, takenAt }. Any failure falls back to the original
   file — a slower upload always beats a lost photo. */
export async function prepareFile(file) {
  const mime = guessMime(file);
  const header = await readJpegHeader(file);
  const fallback = { blob: file, mime, takenAt: header.date };
  if (typeof createImageBitmap !== 'function') return fallback;
  if (file.size <= SKIP_SHRINK_BYTES) return fallback;

  let bitmap = null;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    // Did the browser really orient it? Compare against the raw frame size.
    let orientation = 1;
    if (header.rawWidth && header.orientation > 1) {
      const swap = header.orientation >= 5;
      const expectW = swap ? header.rawHeight : header.rawWidth;
      if (bitmap.width !== expectW) orientation = header.orientation;
    }
    const swap = orientation >= 5;
    const srcW = swap ? bitmap.height : bitmap.width;
    const srcH = swap ? bitmap.width : bitmap.height;
    const scale = Math.min(1, MAX_EDGE / Math.max(srcW, srcH));
    const width = Math.max(1, Math.round(srcW * scale));
    const height = Math.max(1, Math.round(srcH * scale));

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingQuality = 'high';
    drawOriented(ctx, bitmap, orientation, width, height);

    const blob = await new Promise((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY);
    });
    canvas.width = canvas.height = 0;   // release the backing store early
    if (!blob || blob.size >= file.size) return fallback;   // never send more
    return { blob, mime: 'image/jpeg', takenAt: header.date };
  } catch (e) {
    return fallback;                    // HEIC outside Safari, decode failure
  } finally {
    if (bitmap && bitmap.close) bitmap.close();
  }
}

export function makeJobs(files) {
  const jobs = [];
  for (const file of files) {
    const mime = guessMime(file);
    const supported = Object.values(MIME_BY_EXT).includes(mime);
    const sizeOk = file.size > 0 && file.size <= MAX_BYTES;
    jobs.push({
      file, mime, name: file.name, photo_id: null,
      status: supported && sizeOk ? 'queued' : 'failed',
    });
  }
  return jobs;
}

export async function runJobs(jobs, creds, onChange) {
  const queue = jobs.filter((j) => j.status === 'queued');
  const workers = Array.from({ length: 3 }, async () => {
    for (;;) {
      const job = queue.shift();
      if (!job) return;
      job.status = 'uploading';
      onChange();
      try {
        const prepared = await prepareFile(job.file);
        const issued = await api.uploadUrl(creds, {
          filename: job.name, mime: prepared.mime, bytes: prepared.blob.size,
        });
        // Flaky links (tunnels, mobile networks) get three tries before
        // the card goes red.
        let lastError = null;
        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            await api.putObject(issued.upload_url, prepared.blob, prepared.mime);
            lastError = null;
            break;
          } catch (e) {
            lastError = e;
            await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
          }
        }
        if (lastError) throw lastError;
        await api.completePhoto(creds, issued.photo_id, prepared.takenAt);
        job.photo_id = issued.photo_id;
        job.status = 'processing';
      } catch (e) {
        job.status = 'failed';
      }
      onChange();
    }
  });
  await Promise.all(workers);
}
