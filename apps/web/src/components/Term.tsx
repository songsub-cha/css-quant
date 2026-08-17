import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { useGlossaryTermQuery } from "../hooks/useGlossaryQuery";

interface TermProps {
  termKey: string;
  children: ReactNode;
}

// Shared inline glossary popover (SoT A6.12 "인라인 도움말"). Tap/click only
// — no hover trigger, since the app is a mobile-PWA-first target (A5.10)
// where hover has no reliable equivalent.
function Term({ termKey, children }: TermProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);
  const { data: term, isError } = useGlossaryTermQuery(termKey);

  useEffect(() => {
    if (!isOpen) return;

    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <span ref={containerRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        className="cursor-help underline decoration-dotted decoration-slate-400 underline-offset-2"
      >
        {children}
      </button>
      {isOpen && (
        <span
          role="tooltip"
          className="absolute left-0 top-full z-10 mt-1 w-64 rounded border border-slate-700 bg-slate-900 p-3 text-sm text-slate-100 shadow-lg"
        >
          {isError && <p>이 용어의 설명을 찾을 수 없어요.</p>}
          {term && (
            <>
              <p className="font-medium">{term.term_ko}</p>
              <p className="mt-1">{term.definition}</p>
              <p className="mt-1 text-slate-300">{term.interpretation}</p>
              {term.caution && (
                <p className="mt-1 text-amber-400">주의: {term.caution}</p>
              )}
              <Link
                to={`/glossary?term=${encodeURIComponent(termKey)}`}
                className="mt-2 inline-block text-sky-400 hover:underline"
                onClick={() => setIsOpen(false)}
              >
                용어집에서 더 보기
              </Link>
            </>
          )}
        </span>
      )}
    </span>
  );
}

export default Term;
