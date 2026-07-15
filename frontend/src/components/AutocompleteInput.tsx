import { useEffect, useId, useMemo, useRef, useState } from "react";

export interface AutocompleteOption {
  value: string;
  label?: string;
  description?: string;
  keywords?: string[];
}

interface AutocompleteInputProps {
  value: string;
  onChange: (value: string) => void;
  options: AutocompleteOption[];
  onOptionSelect?: (option: AutocompleteOption) => void;
  placeholder?: string;
  className?: string;
  inputMode?: "text" | "numeric" | "decimal" | "url";
  autoCapitalize?: "none" | "characters" | "words" | "sentences";
  emptyText?: string;
  maxResults?: number;
  onKeyDown?: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  "aria-label"?: string;
}

function normalize(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function optionMatches(option: AutocompleteOption, query: string): boolean {
  if (!query) return true;
  const haystack = [option.value, option.label, option.description, ...(option.keywords ?? [])]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
  return haystack.includes(query);
}

/**
 * A controlled, keyboard-friendly input that keeps manual entry available while
 * offering a short, filtered list of known values. It is deliberately used for
 * values with an open set (symbols, webhook templates, endpoints) rather than
 * forcing an incomplete <select> list.
 */
export function AutocompleteInput({
  value,
  onChange,
  options,
  onOptionSelect,
  placeholder,
  className,
  inputMode = "text",
  autoCapitalize,
  emptyText = "没有匹配项，可继续手动输入",
  maxResults = 8,
  onKeyDown,
  "aria-label": ariaLabel,
}: AutocompleteInputProps) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const inputId = useId();
  const listboxId = `${inputId}-listbox`;
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const filteredOptions = useMemo(() => {
    const query = normalize(value);
    const seen = new Set<string>();
    return options.filter((option) => {
      const key = option.value.toLocaleLowerCase();
      if (seen.has(key) || !optionMatches(option, query)) return false;
      seen.add(key);
      return true;
    }).slice(0, maxResults);
  }, [maxResults, options, value]);

  useEffect(() => {
    setActiveIndex(0);
  }, [value, options]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  const choose = (option: AutocompleteOption) => {
    onChange(option.value);
    onOptionSelect?.(option);
    setOpen(false);
  };

  return (
    <span className="autocomplete" ref={rootRef}>
      <input
        id={inputId}
        className={className}
        value={value}
        role="combobox"
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-activedescendant={open && filteredOptions[activeIndex] ? `${inputId}-option-${activeIndex}` : undefined}
        placeholder={placeholder}
        inputMode={inputMode}
        autoCapitalize={autoCapitalize}
        autoComplete="off"
        spellCheck={false}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((index) => Math.min(index + 1, Math.max(filteredOptions.length - 1, 0)));
            return;
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((index) => Math.max(index - 1, 0));
            return;
          }
          if (event.key === "Enter" && open && filteredOptions[activeIndex]) {
            event.preventDefault();
            choose(filteredOptions[activeIndex]);
            return;
          }
          if (event.key === "Escape") {
            setOpen(false);
            return;
          }
          onKeyDown?.(event);
        }}
      />
      {open ? (
        <span className="autocomplete__menu" id={listboxId} role="listbox" aria-label="输入建议">
          {filteredOptions.length ? filteredOptions.map((option, index) => (
            <span
              id={`${inputId}-option-${index}`}
              key={option.value}
              role="option"
              aria-selected={activeIndex === index}
              className={`autocomplete__option${activeIndex === index ? " is-active" : ""}`}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(event) => {
                event.preventDefault();
                choose(option);
              }}
            >
              <span className="autocomplete__option-value">{option.label ?? option.value}</span>
              {option.description ? <small>{option.description}</small> : null}
            </span>
          )) : (
            <span className="autocomplete__empty">{emptyText}</span>
          )}
        </span>
      ) : null}
    </span>
  );
}
