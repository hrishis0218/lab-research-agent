import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import * as pdfjs from "pdfjs-dist";
import worker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = worker;
export default function Pdf({
  id,
  initialPage,
  pages,
}: {
  id: number;
  initialPage: number;
  pages: number;
}) {
  const [page, setPage] = useState(initialPage);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const canvas = useRef<HTMLCanvasElement>(null);
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => setPage(initialPage), [id, initialPage]);
  useEffect(() => {
    const task = pdfjs.getDocument({ url: `/api/documents/${id}/pdf` });
    let dead = false;
    setLoading(true);
    setError("");
    task.promise
      .then(async (pdf) => {
        const sheet = await pdf.getPage(
          Math.max(1, Math.min(page, pdf.numPages)),
        );
        if (dead || !canvas.current) return;
        const viewport = sheet.getViewport({
          scale:
            Math.min((host.current?.clientWidth || 380) - 24, 900) /
            sheet.getViewport({ scale: 1 }).width,
        });
        const target = canvas.current;
        const ratio = window.devicePixelRatio || 1;
        target.width = viewport.width * ratio;
        target.height = viewport.height * ratio;
        target.style.width = `${viewport.width}px`;
        target.style.height = `${viewport.height}px`;
        await sheet.render({
          canvas: target,
          viewport,
          transform: [ratio, 0, 0, ratio, 0, 0],
        }).promise;
        if (!dead) setLoading(false);
      })
      .catch((e) => {
        if (!dead) {
          setError(`PDF could not be rendered: ${e.message}`);
          setLoading(false);
        }
      });
    return () => {
      dead = true;
      void task.destroy();
    };
  }, [id, page]);
  return (
    <div className="pdf" ref={host}>
      <div className="pdf-tools">
        <button
          aria-label="Previous PDF page"
          disabled={page <= 1}
          onClick={() => setPage(page - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button
          aria-label="Next PDF page"
          disabled={page >= pages}
          onClick={() => setPage(page + 1)}
        >
          <ChevronRight size={16} />
        </button>
        <a
          title="Open original PDF"
          href={`/api/documents/${id}/pdf#page=${page}`}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={15} />
        </a>
      </div>
      {loading && <p role="status">Rendering local PDF…</p>}
      {error && <p role="alert">{error}</p>}
      <canvas ref={canvas} aria-label={`Original PDF page ${page}`} />
    </div>
  );
}
