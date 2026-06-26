import { SectionTitle } from "./atoms";

interface LoadingFallbackProps {
  title: string;
  hint?: string;
}

export function LoadingFallback({ title, hint }: LoadingFallbackProps) {
  return (
    <div className="page">
      <header className="page__header">
        <div>
          <p className="eyebrow">加载中</p>
          <h1>{title}</h1>
          {hint && <span className="page__subtitle">{hint}</span>}
        </div>
      </header>
      <div className="skeleton-grid">
        {Array.from({ length: 4 }).map((_, i) => (
          <div className="skeleton-card" key={i} />
        ))}
      </div>
      <SectionTitle title="数据加载中..." />
      <div className="skeleton-list">
        {Array.from({ length: 5 }).map((_, i) => (
          <div className="skeleton-row" key={i} />
        ))}
      </div>
    </div>
  );
}