import { SectionTitle } from "./atoms";

interface ErrorPanelProps {
  title: string;
  message: string;
  action?: { label: string; href: string };
}

export function ErrorPanel({ title, message, action }: ErrorPanelProps) {
  return (
    <section className="panel panel--error">
      <SectionTitle title={title} />
      <div className="error-body">
        <p>{message}</p>
        {action && (
          <a href={action.href} className="action action--primary">
            {action.label}
          </a>
        )}
      </div>
    </section>
  );
}