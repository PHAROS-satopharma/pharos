import workerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url';

interface TextItemLike {
  str?: string;
  hasEOL?: boolean;
  transform?: number[];
}

/**
 * The text of a PDF chosen on this computer, one line per printed line, read in the browser. Nothing is
 * uploaded: only the sections found are saved. A scanned PDF has no text layer and returns almost nothing;
 * the screen then asks for the text to be pasted instead.
 */
export async function pdfText(file: File): Promise<string> {
  const pdfjs = await import('pdfjs-dist');
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  const pdf = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
  try {
    const pages: string[] = [];
    for (let p = 1; p <= pdf.numPages; p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      let line = '';
      let lastY: number | null = null;
      const lines: string[] = [];
      for (const raw of content.items as TextItemLike[]) {
        const y = raw.transform?.[5] ?? null;
        // A new printed line: the text moved down, or the item ends its line.
        if (lastY !== null && y !== null && Math.abs(y - lastY) > 2 && line) {
          lines.push(line);
          line = '';
        }
        line += raw.str ?? '';
        lastY = y;
        if (raw.hasEOL) {
          lines.push(line);
          line = '';
        }
      }
      if (line) lines.push(line);
      pages.push(lines.map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n'));
    }
    return pages.join('\n');
  } finally {
    void pdf.destroy();
  }
}
