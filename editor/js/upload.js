/* Upload pipeline: presign -> PUT to storage -> complete, three files at a
   time. Job objects surface per-file progress; the caller re-renders the
   tray and polls the photo list for ingest results. */
import * as api from './api.js';

const MAX_BYTES = 25 * 1024 * 1024;
const MIME_BY_EXT = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
  heic: 'image/heic', heif: 'image/heif',
};

function guessMime(file) {
  if (file.type && file.type !== 'application/octet-stream') return file.type;
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  return MIME_BY_EXT[ext] || '';
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
        const issued = await api.uploadUrl(creds, {
          filename: job.name, mime: job.mime, bytes: job.file.size,
        });
        // Flaky links (tunnels, mobile networks) get three tries before
        // the card goes red.
        let lastError = null;
        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            await api.putObject(issued.upload_url, job.file, job.mime);
            lastError = null;
            break;
          } catch (e) {
            lastError = e;
            await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
          }
        }
        if (lastError) throw lastError;
        await api.completePhoto(creds, issued.photo_id);
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
