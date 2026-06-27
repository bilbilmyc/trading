/**
 * Lightweight markdown renderer for AI analyze reports.
 * Supports: headings, bold, italic, code, lists, paragraphs, line breaks.
 * No external dependencies.
 */

import type { ReactNode } from "react";

interface MdProps {
  text: string;
}

function renderInline(text: string): ReactNode {
  // Process inline patterns: **bold**, *italic*, `code`.
  const parts: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < text.length) {
    if (text[i] === "*" && text[i + 1] === "*") {
      const end = text.indexOf("**", i + 2);
      if (end > 0) {
        parts.push(<strong key={key++}>{text.slice(i + 2, end)}</strong>);
        i = end + 2;
        continue;
      }
    }
    if (text[i] === "*" && text[i + 1] !== "*") {
      const end = text.indexOf("*", i + 1);
      if (end > 0) {
        parts.push(<em key={key++}>{text.slice(i + 1, end)}</em>);
        i = end + 1;
        continue;
      }
    }
    if (text[i] === "`") {
      const end = text.indexOf("`", i + 1);
      if (end > 0) {
        parts.push(<code key={key++} className="md-code">{text.slice(i + 1, end)}</code>);
        i = end + 1;
        continue;
      }
    }
    // Find next special char.
    let next = i + 1;
    while (next < text.length && text[next] !== "*" && text[next] !== "`") next++;
    parts.push(text.slice(i, next));
    i = next;
  }
  return parts;
}

export function Markdown({ text }: MdProps) {
  if (!text) return null;
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let key = 0;
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      blocks.push(
        <h3 key={key++} className={`md-h md-h${level}`}>
          {renderInline(headingMatch[2])}
        </h3>
      );
      i++;
      continue;
    }

    // List item
    if (line.match(/^[\-\*]\s+/)) {
      const items: ReactNode[] = [];
      while (i < lines.length && lines[i].match(/^[\-\*]\s+/)) {
        items.push(
          <li key={key++}>{renderInline(lines[i].replace(/^[\-\*]\s+/, ""))}</li>
        );
        i++;
      }
      blocks.push(<ul key={key++} className="md-list">{items}</ul>);
      continue;
    }

    // Numbered list
    if (line.match(/^\d+\.\s+/)) {
      const items: ReactNode[] = [];
      while (i < lines.length && lines[i].match(/^\d+\.\s+/)) {
        items.push(
          <li key={key++}>{renderInline(lines[i].replace(/^\d+\.\s+/, ""))}</li>
        );
        i++;
      }
      blocks.push(<ol key={key++} className="md-list">{items}</ol>);
      continue;
    }

    // Empty line → skip (paragraph break)
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: collect until empty line / heading / list
    const paragraphLines: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].match(/^(#{1,6})\s+/) &&
      !lines[i].match(/^[\-\*]\s+/) &&
      !lines[i].match(/^\d+\.\s+/)
    ) {
      paragraphLines.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="md-p">
        {renderInline(paragraphLines.join(" "))}
      </p>
    );
  }

  return <div className="markdown">{blocks}</div>;
}
