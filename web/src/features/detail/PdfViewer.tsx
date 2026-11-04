import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url';
import { archiveUrl, errorMessage, openArchived } from '../../lib/api';
import { Button } from '../../ui/Button';
import { Loading, Notice } from '../../ui/States';

const FIRST_PAGES = 3;

function PdfPage({ doc, pageNumber }: { doc: PDFDocumentProxy; pageNumber: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    void (async () => {
      const page = await doc.getPage(pageNumber);
      const canvas = canvasRef.current;
      const wrap = wrapRef.current;
      if (cancelled || !canvas || !wrap) return;
      const base = page.getViewport({ scale: 1 });
      const width = wrap.clientWidth || base.width;
      const dpr = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: (width / base.width) * dpr });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = `${Math.floor(viewport.width / dpr)}px`;
      canvas.style.height = `${Math.floor(viewport.height / dpr)}px`;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const render = page.render({ canvasContext: ctx, viewport });
      task = render;
      await render.promise;
    })().catch(() => undefined);
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, pageNumber]);

  return (
    <div className="pdf-page" ref={wrapRef}>
      <canvas ref={canvasRef} aria-label={`Page ${pageNumber}`} role="img" />
    </div>
  );
}

/** The archived original PDF, drawn page by page with pdf.js, with a download beside it. */
export function PdfViewer({ r2Key, label }: { r2Key: string; label: string }) {
  const urlQ = useQuery({
    queryKey: ['archive-url', r2Key],
    queryFn: () => archiveUrl(r2Key),
    staleTime: 8 * 60_000,
    retry: false,
  });
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);

  useEffect(() => {
    const url = urlQ.data;
    if (!url) return;
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    setDoc(null);
    setLoadError(null);
    setShowAll(false);
    void (async () => {
      try {
        const pdfjs = await import('pdfjs-dist');
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
        const pdf = await pdfjs.getDocument({ url }).promise;
        loaded = pdf;
        if (cancelled) {
          void pdf.destroy();
          return;
        }
        setDoc(pdf);
      } catch (e) {
        if (!cancelled) setLoadError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
      if (loaded) void loaded.destroy();
    };
  }, [urlQ.data]);

  async function download() {
    setOpenError(null);
    try {
      await openArchived(r2Key);
    } catch (e) {
      setOpenError(errorMessage(e));
    }
  }

  const pages = doc ? (showAll ? doc.numPages : Math.min(FIRST_PAGES, doc.numPages)) : 0;

  return (
    <div className="pdf">
      <div className="pdf-bar">
        <span className="small">
          {label}
          {doc ? <span className="soft"> · {doc.numPages} {doc.numPages === 1 ? 'page' : 'pages'}</span> : null}
        </span>
        <Button size="sm" onClick={() => void download()}>
          Download the original
        </Button>
      </div>
      {openError ? <Notice tone="error">The file could not be opened: {openError}</Notice> : null}
      {urlQ.isError ? (
        <Notice tone="error">The archive did not give a link to this file: {errorMessage(urlQ.error)}</Notice>
      ) : loadError ? (
        <Notice tone="error">
          The PDF could not be shown here ({loadError}). Use “Download the original” to open it in a new tab.
        </Notice>
      ) : !doc ? (
        <Loading label="Opening the PDF" />
      ) : (
        <>
          <div className="pdf-pages">
            {Array.from({ length: pages }, (_, i) => (
              <PdfPage key={`${r2Key}-${i + 1}`} doc={doc} pageNumber={i + 1} />
            ))}
          </div>
          {doc.numPages > pages ? (
            <Button size="sm" onClick={() => setShowAll(true)}>
              Show all {doc.numPages} pages
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
