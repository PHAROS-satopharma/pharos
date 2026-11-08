/** The MedDRA upload (migration 0102), kept apart from the screen so it is tested without a database. */

export const MAX_UPLOAD = 50 * 1024 * 1024;

/** The folder of one upload: uploads/<UTC time>, as ask_meddra_load() takes it. */
export function uploadFolder(now: Date): string {
  return `uploads/${now.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z')}`;
}

/** Which of the chosen files to upload: the release zip, or the .asc files of its MedAscii folder. */
export function filesToUpload(files: File[]): { files: File[]; problem: string | null } {
  const kept = files.filter((f) => /\.(zip|asc)$/i.test(f.name));
  if (!kept.length) return { files: [], problem: 'Choose the zip MSSO sent, or the .asc files of its MedAscii folder.' };
  const big = kept.find((f) => f.size > MAX_UPLOAD);
  if (big) return { files: [], problem: `${big.name} is larger than 50 MB. Upload the .asc files of the MedAscii folder instead.` };
  return { files: kept, problem: null };
}
