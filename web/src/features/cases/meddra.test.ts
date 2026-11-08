import { describe, expect, it } from 'vitest';
import { filesToUpload, uploadFolder } from './meddraUpload';

describe('MedDRA upload', () => {
  it('names the folder as ask_meddra_load() takes it', () => {
    expect(uploadFolder(new Date('2026-11-10T08:05:09.123Z'))).toBe('uploads/20261110T080509Z');
    expect(uploadFolder(new Date())).toMatch(/^uploads\/[0-9]{8}T[0-9]{6}Z$/);
  });

  it('keeps the release zip and the .asc files, nothing else', () => {
    const f = (name: string, size = 10) => new File([new Uint8Array(size)], name);
    expect(filesToUpload([f('MedDRA_28_1_English.zip'), f('readme.pdf')]).files.map((x) => x.name)).toEqual([
      'MedDRA_28_1_English.zip',
    ]);
    expect(filesToUpload([f('llt.asc'), f('PT.ASC')]).files).toHaveLength(2);
    expect(filesToUpload([f('notes.txt')]).problem).toMatch(/MedAscii/);
  });
});
